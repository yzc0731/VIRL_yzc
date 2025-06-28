import re
import json
import os
import requests
import folium
import polyline
import time
import tempfile
import webbrowser
from typing import List, Tuple, Dict
from data_utils import calculate_bearing, parse_pano_json_to_list

class GoogleDataProcessor:
    def __init__(self, seed: int, api_key: str):
        """
        Args:
            seed (int): id for place in google data
            api_key (str): Google Map API key
        """
        self.seed = seed
        self.api_key = api_key
        self.coord_pattern_strict = re.compile(r'/@(-?\d+\.\d+),(-?\d+\.\d+),')
        self.pano_pattern = re.compile(r'!1s(.*?)!2e')
        self.street_view_url = "https://maps.googleapis.com/maps/api/streetview"
        self.cam_num = 4
        self.view_label_list = ['front', 'right', 'back', 'left']

        # Create data directory based on place id
        self.data_dir = f'./googledata/place{self.seed}'
        os.makedirs(self.data_dir, exist_ok=True)
        self.json_path = os.path.join(self.data_dir, 'pano.json')
        self.url_path = os.path.join(self.data_dir, 'url.txt')
        self.points_html_path = os.path.join(self.data_dir, 'points.html')

    def extract_graph_data(self, 
            strings_list: List[str]
        ) -> Dict:
        """
        Read urls from a list of strings and extract (lat, lng, pano_id) for all locations
        
        Args:
            strings_list: List of strings containing URLs with coordinates and pano_id
        Returns:
            Dictionary with keys 'nodes' containing lat, lng, pano_id for each location
        """
        nodes = {}

        for _, s in enumerate(strings_list, start=0):
            # Get lat and lng from the string
            lat, lng = None, None
            strict_match = self.coord_pattern_strict.search(s)
            if strict_match:
                lat, lng = float(strict_match.group(1)), float(strict_match.group(2))
                assert -90 <= lat <= 90, "lat must be between -90 and 90"
                assert -180 <= lng <= 180, "lng must be between -180 and 180"
            else:
                raise ValueError(f"No valid coordinates found in string: {s}")

            # Extract pano_id
            pano_match = self.pano_pattern.search(s)
            pano_id = pano_match.group(1) if pano_match else None

            # Store in dictionary
            if lat is not None and lng is not None:
                nodes[pano_id] = {'lat': lat, 'lng': lng}
        
        # Plot points on a map
        self.plot_points(nodes=nodes)

        return {'nodes': nodes}

    def process_urls_to_json(self) -> None:
        """Process URLs from the text file and save to JSON"""
        # read urls from the text file
        with open(self.url_path, 'r', encoding='utf-8') as f:
            strings_list = [line.strip() for line in f if line.strip()]
        if not strings_list:
            raise ValueError("Input file is empty or format is incorrect")
        
        # Parse graph data from the list of strings
        route_data = self.extract_graph_data(strings_list)

        # Save the route data to JSON file
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(route_data, f, indent=4, ensure_ascii=False)
        print(f"Points saved to {self.json_path}")
    
    def add_fore_heading_to_points(self, 
            points_list: List[Tuple[str, Tuple[float, float]]]
        ) -> Dict[str, Tuple[float, float, float]]:
        """
        Add fore_heading to each point tuple in points_dict.
        The heading is calculated from the current point to the next point.
        The last point's heading is set to the previous heading (since there's no next point).

        Args:
            points_dict: Dictionary with pano_id as key and tuple (lat, lng) as value.
        Returns:
            Dictionary with pano_id as key and tuple (lat, lng, fore_heading) as value.
        """
        points_dict = {}
        
        # Handle all points except the last one
        for i in range(len(points_list) - 1):
            current_pano_id, (current_lat, current_lng) = points_list[i]
            next_pano_id, (next_lat, next_lng) = points_list[i + 1]
            
            heading = calculate_bearing(current_lat, current_lng, next_lat, next_lng)
            points_dict[current_pano_id] = (current_lat, current_lng, heading)
        
        # Handle the last point (use previous heading)
        last_pano_id, (last_lat, last_lng) = points_list[-1]
        if len(points_list) > 1:
            # Use the heading from the second-to-last point to the last point
            points_dict[last_pano_id] = (last_lat, last_lng, heading)
        else:
            # Only one point, set heading to 0 (or any default value)
            points_dict[last_pano_id] = (last_lat, last_lng, 0.0)
        
        return points_dict

    def download_streetview_images(self) -> None:
        """Download Google Street View images"""
        points_list = parse_pano_json_to_list(self.json_path)
        points_dict = self.add_fore_heading_to_points(points_list)

        for key, value in points_dict.items():
            latitude, longitude, fore_heading = value
            heading_list = [(fore_heading + i * (360 / self.cam_num)) % 360 for i in range(self.cam_num)]
                
            for heading, label in zip(heading_list, self.view_label_list):
                filename = f"id_{key}_{label}.jpg"
                if os.path.exists(os.path.join(self.data_dir, filename)):
                    print(f"File {filename} already exists, skipping download.")
                    continue

                params = {
                    'size': '640x640',
                    'location': f'{latitude},{longitude}',
                    'heading': heading,
                    'source': 'outdoor',
                    'fov': 90,
                    'pitch': 30,
                    'key': self.api_key
                }

                response = requests.get(self.street_view_url, params=params)
                if response.status_code == 200:   
                    filepath = os.path.join(self.data_dir, filename)
                    with open(filepath, "wb") as f:
                        f.write(response.content)
                    print(f"Saved to {filepath}")
                else:
                    print(f"Error state: {response.status_code}. Error msg: {response.text}")
    
    def plot_points(self, nodes: Dict[str, Dict[str, float]]) -> None:
        """
        Plot points on a map using Folium and save to HTML file
        
        Args:
            nodes: Dictionary of nodes with keys as node IDs and values as dictionaries containing 'lat' and 'lng'
        """
        # convert nodes to a list of tuples
        nodes_dict = {key: (value['lat'], value['lng']) for key, value in nodes.items()}
        # nodes_list is the type Dict[str, Tuple[float, float]]

        # Create map centered on the first coordinate
        first_key = next(iter(nodes_dict))
        first_value = nodes_dict[first_key]
        m = folium.Map(location=first_value, zoom_start=20)
        
        # Add markers for all points (same style for all)
        for key, value in nodes_dict.items():
            folium.CircleMarker(
                location=value,
                radius=5,
                color='orange',
                fill=True,
                fill_color='orange',
                popup=f'Point {key}'
            ).add_to(m)
        
        # Save to HTML file in the data directory
        m.save(self.points_html_path)
        print(f"Nodes saved to {self.points_html_path}")

    def plot_route(self, 
            rendezvous_point: Tuple[str, Tuple[float, float]],
            alice_points_list: List[Tuple[str, Tuple[float, float]]],
            bob_points_list: List[Tuple[str, Tuple[float, float]]], 
            traj_id: int
        ) -> None:
        """
        Plot route on a map using Folium and save to HTML file
        
        Args:
            rendezvous_point: Tuple with pano_id and (lat, lng) of the rendezvous point
            alice_points_list: List of tuples with (pano_id, (lat, lng))
            bob_points_list: List of tuples with (pano_id, (lat, lng))
            traj_id: Trajectory ID for saving the output file
        """
        # Create map centered on the first coordinate
        rendezvous_point_pano_id, rendezvous_point_location = rendezvous_point
        m = folium.Map(location=rendezvous_point_location, zoom_start=20)

        # Add markers for start and end points
        folium.Marker(
            rendezvous_point_location,
            popup=f'Renderzvous {rendezvous_point_pano_id}',
            icon=folium.Icon(color='green')
        ).add_to(m)
        
        # Add clickable markers for all waypoints (excluding first and last)
        for pano_id, coord in alice_points_list:
            folium.CircleMarker(
                location=coord,
                radius=5,
                color='orange',
                fill=True,
                fill_color='orange',
                popup=f'Alice {pano_id}'
            ).add_to(m)
        for pano_id, coord in bob_points_list:
            folium.CircleMarker(
                location=coord,
                radius=5,
                color='red',
                fill=True,
                fill_color='red',
                popup=f'Bob {pano_id}'
            ).add_to(m)

        alice_polyline_coords = [coord for _, coord in alice_points_list]
        alice_polyline_coords.append(rendezvous_point_location)
        bob_polyline_coords = [coord for _, coord in bob_points_list]
        bob_polyline_coords.append(rendezvous_point_location)
        # Add the route as a polyline
        folium.PolyLine(
            locations=alice_polyline_coords,
            color='orange',
            weight=5,
            opacity=0.8,
            tooltip="orange"
        ).add_to(m)
        folium.PolyLine(
            locations=bob_polyline_coords,
            color='red',
            weight=5,
            opacity=0.8,
            tooltip="red"
        ).add_to(m)
        
        # Save to HTML file in the data directory
        full_output_path = f'./textdata/traj{traj_id}/route.html'
        m.save(full_output_path)
        print(f"Route plotted and saved to {full_output_path}")

    def write_traj_metainfo(self, traj_id: int = -1, 
                            stride: int = 1, 
                            rendezvous_point_pano_id: str = None) -> None:
        """
        Write traj information to a text file.
        This function samples points from the pano.json file based on the given stride.
        If a rendezvous point is provided, it will split the points into Alice's and Bob's routes based on the stride.
        If no rendezvous point is provided, it will sample points from the pano.json file and create a route with Alice's points in the first half and Bob's points in the second half.
        The rendezvous point is the middle point of the list, and Alice's points are sampled from the first half, while Bob's points are sampled from the second half.
        This function saves the trajectory metainfo to a JSON file and plots the route on a map.

        Args:
            traj_id (int): The trajectory ID, default is -1.
            stride (int): The stride for the trajectory, default is 1.
            rendezvous_point_pano_id (str): The panorama ID of the rendezvous point, default is None.
        """
        points_list = parse_pano_json_to_list(self.json_path)
        alice_points_list = []
        bob_points_list = []
        rendezvous_point = None
        # split the points list into two parts.
        # mode 1: if rendezvous_point_pano_id is not None, split the points into Alice's and Bob's routes
        if rendezvous_point_pano_id is not None:
            found_flag = False
            for point in points_list:
                pano_id, location = point
                if pano_id == rendezvous_point_pano_id:
                    rendezvous_point = (rendezvous_point_pano_id, location)
                    found_flag = True
                    continue
                if found_flag:
                    bob_points_list.append(point)
                else:
                    alice_points_list.append(point)
            if rendezvous_point is None:
                raise ValueError(f"Rendezvous point {rendezvous_point_pano_id} not found in pano.json")
        else: # mode 2: if rendezvous_point_pano_id is None, split the points into half
            len_points = len(points_list)
            assert len_points > 0, "No points found in pano.json"
            if len_points % 2 == 0: # even number of points
                points_list.pop() # remove the last point
                len_points -= 1
            # else: # odd number of points, choose the middle point as the end point
            #     pass
            len_points = len(points_list)
            middle_index = len_points // 2
            rendezvous_point = points_list[middle_index]
            alice_points_list = points_list[:middle_index]
            bob_points_list = points_list[(middle_index + 1):]

        # then sample the points by stride
        assert stride > 0, "Stride must be greater than 0"
        if stride > 1:
            alice_points_list = alice_points_list[::stride]
            bob_points_list = bob_points_list[::stride]
        # else: # if stride is 1, then just use the original points
        #   pass

        # reverse the Bob's points list
        bob_points_list.reverse()
        # Balance the lengths by extending with last point
        len_diff = len(alice_points_list) - len(bob_points_list)
        if len_diff > 0:
            bob_points_list.extend([bob_points_list[-1]] * len_diff)
        elif len_diff < 0:
            alice_points_list.extend([alice_points_list[-1]] * (-len_diff))

        # save all the information to a json file
        metainfo = {
            'place': self.seed,
            'stride': stride,
            'rendezvous point': rendezvous_point[0],
            'Alice points': [pano_id for pano_id, _ in alice_points_list],
            'Bob points': [pano_id for pano_id, _ in bob_points_list],
        }
        textdata_dir = f'./textdata/traj{traj_id}'
        os.makedirs(textdata_dir, exist_ok=True)
        metainfo_path = os.path.join(textdata_dir, 'metainfo.json')
        with open(metainfo_path, 'w', encoding='utf-8') as f:
            json.dump(metainfo, f, indent=4, ensure_ascii=False)
        print(f"Saved trajectory metainfo to {metainfo_path} with stride {stride}")

        # plot the route
        self.plot_route(
            rendezvous_point=rendezvous_point,
            alice_points_list=alice_points_list,
            bob_points_list=bob_points_list,
            traj_id=traj_id,
        )

    def set_api_key(self, api_key: str) -> None:
        """Set Google Maps API key"""
        self.api_key = api_key

    def set_seed(self, seed: int) -> None:
        """Set random seed and update related paths"""
        self.seed = seed
        self.data_dir = f'./googledata/seed{self.seed}'
        os.makedirs(self.data_dir, exist_ok=True)
        self.json_path = os.path.join(self.data_dir, 'pano.json')
        self.url_path = os.path.join(self.data_dir, 'url.txt')
        
    def generate_route(self, start_location, end_location, sample_count=10, mode="walking"):
        """
        Generate a route between two points and save to url.txt
        
        Args:
            start_location: Start coordinates as "lat,lng" or [lat, lng]
            end_location: End coordinates as "lat,lng" or [lat, lng]
            sample_count: Number of sample points (default: 10)
            mode: Travel mode - "walking", "driving", "bicycling", "transit" (default: "walking")
        
        Returns:
            List of generated Street View URLs
        """
        if not self.api_key:
            raise ValueError("API Key not set. Use set_api_key() method first.")
            
        # Format locations if they're lists or tuples
        if isinstance(start_location, (list, tuple)):
            start_location = f"{start_location[0]},{start_location[1]}"
        if isinstance(end_location, (list, tuple)):
            end_location = f"{end_location[0]},{end_location[1]}"
            
        print(f"Generating route from {start_location} to {end_location}...")
            
        # Call Directions API
        url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": start_location,
            "destination": end_location,
            "key": self.api_key,
            "mode": mode
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if data["status"] != "OK":
            raise Exception(f"Failed to get directions: {data['status']}")
        
        # Decode route polyline
        route = data["routes"][0]
        encoded_points = route["overview_polyline"]["points"]
        coordinates = polyline.decode(encoded_points)
        
        # Sample route points evenly
        sample_indices = [int(i * (len(coordinates) - 1) / (sample_count - 1)) for i in range(sample_count)]
        sampled_coords = [coordinates[i] for i in sample_indices]
        
        # Get Street View URLs for each point
        urls = []
        for lat, lng in sampled_coords:
            # Get panorama ID
            metadata_url = f"https://maps.googleapis.com/maps/api/streetview/metadata?location={lat},{lng}&key={self.api_key}"
            meta_response = requests.get(metadata_url)
            meta_data = meta_response.json()
            
            if meta_data["status"] == "OK":
                pano_id = meta_data["pano_id"]
                street_view_url = f"https://www.google.com/maps/@{lat},{lng},3a,90y,0h,90t/data=!3m1!1e1!3m2!1s{pano_id}!2e0"
                urls.append(street_view_url)
                print(f"Found Street View at {lat}, {lng}")
            else:
                print(f"No Street View available at {lat}, {lng}")
            
            # Avoid rate limiting
            time.sleep(0.2)
        
        # Save to url.txt
        with open(self.url_path, "w", encoding="utf-8") as f:
            f.write("\n".join(urls))
        
        print(f"Generated {len(urls)} Street View URLs and saved to {self.url_path}")
        return urls
    
    def generate_route_interactive(self):
        """
        Create an interactive map to select start and end points for route generation
        
        Returns:
            List of generated Street View URLs
        """
        # Create a simple HTML file with a map
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Route Generator</title>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
            <style>
                #map { height: 600px; }
                .controls { padding: 10px; background: white; border: 1px solid #ccc; }
            </style>
        </head>
        <body>
            <div id="map"></div>
            <div class="controls">
                <h3>Route Generator</h3>
                <p>Click to set start point, then click again to set end point.</p>
                <div id="start">Start: Not set</div>
                <div id="end">End: Not set</div>
                <button id="clear">Clear</button>
                <button id="generate" disabled>Generate Route</button>
                <div id="output"></div>
            </div>
            <script>
                var map = L.map('map').setView([40.7128, -74.0060], 13);
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
                
                var start = null;
                var end = null;
                var startMarker = null;
                var endMarker = null;
                
                function updateUI() {
                    document.getElementById('start').innerHTML = start ? 
                        `Start: ${start.lat.toFixed(6)}, ${start.lng.toFixed(6)}` : 'Start: Not set';
                    document.getElementById('end').innerHTML = end ? 
                        `End: ${end.lat.toFixed(6)}, ${end.lng.toFixed(6)}` : 'End: Not set';
                    
                    document.getElementById('generate').disabled = !(start && end);
                }
                
                map.on('click', function(e) {
                    if (!start) {
                        start = e.latlng;
                        startMarker = L.marker(start).addTo(map)
                            .bindPopup('Start').openPopup();
                    } else if (!end) {
                        end = e.latlng;
                        endMarker = L.marker(end).addTo(map)
                            .bindPopup('End').openPopup();
                        L.polyline([start, end], {color: 'blue'}).addTo(map);
                    }
                    updateUI();
                });
                
                document.getElementById('clear').addEventListener('click', function() {
                    if (startMarker) map.removeLayer(startMarker);
                    if (endMarker) map.removeLayer(endMarker);
                    start = null;
                    end = null;
                    updateUI();
                    map.eachLayer(function(layer) {
                        if (layer instanceof L.Polyline) {
                            map.removeLayer(layer);
                        }
                    });
                });
                
                document.getElementById('generate').addEventListener('click', function() {
                    var output = document.getElementById('output');
                    output.innerHTML = 'Generating route...';
                    
                    // Save coordinates to a temporary file that will be read by Python
                    var coordinates = JSON.stringify({
                        start: [start.lat, start.lng],
                        end: [end.lat, end.lng]
                    });
                    
                    // Use navigator.clipboard API to copy to clipboard
                    navigator.clipboard.writeText(coordinates).then(function() {
                        output.innerHTML = 'Coordinates copied to clipboard! Paste into the Python terminal.';
                    }).catch(function() {
                        output.innerHTML = coordinates;
                    });
                });
            </script>
        </body>
        </html>
        """
        
        # Create temporary file
        fd, path = tempfile.mkstemp(suffix='.html')
        with os.fdopen(fd, 'w') as f:
            f.write(html)
        
        # Open in browser
        webbrowser.open('file://' + path)
        
        print("Map opened in your browser. After selecting points, the coordinates will be copied to clipboard.")
        print("When ready, paste the coordinates here:")
        
        try:
            coords_json = input()
            import json
            coords = json.loads(coords_json)
            
            start = coords['start']
            end = coords['end']
            
            # Ask for sample count
            sample_count = int(input("Enter number of sample points (default: 10): ") or "10")
            
            # Generate route
            return self.generate_route(start, end, sample_count)
            
        except json.JSONDecodeError:
            print("Invalid coordinates format. Please try again.")
        except Exception as e:
            print(f"Error: {str(e)}")
        finally:
            # Clean up temporary file
            try:
                os.unlink(path)
            except:
                pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Google Street View Data Download Tool")
    parser.add_argument("--api-key", required=True, help="Google Maps API Key")
    parser.add_argument("--seed", type=int, help="Data ID")

    parser.add_argument("--mode", choices=["manual", "auto", "interactive"], default="manual",
                        help="Mode: manual (use url.txt), auto (provide start/end), interactive (map selector)")
    
    parser.add_argument("--start", help="Start location (lat,lng) for auto mode")
    parser.add_argument("--end", help="End location (lat,lng) for auto mode") 
    parser.add_argument("--samples", type=int, default=10, help="Number of sample points for auto mode")
    
    parser.add_argument("--function", choices=["process", "download", "write"], default="process",
                        help="Function to execute: process (process urls to json), download (download street view images), write (write trajectory metainfo)")
    parser.add_argument("--traj-id", type=int, default=-1, help="Trajectory ID for write mode")
    parser.add_argument("--stride", type=int, default=1, help="Stride for sampling points in write mode")
    parser.add_argument("--pano-id", type=str, default=None, help="Pano ID for write mode, if not provided, will sample points automatically")
    args = parser.parse_args()

    processor = GoogleDataProcessor(seed=args.seed, api_key=args.api_key)
    
    if args.mode == "auto":
        if not args.start or not args.end:
            parser.error("--start and --end are required with --mode=auto")
        processor.generate_route(args.start, args.end, args.samples)
    elif args.mode == "interactive":
        processor.generate_route_interactive()
    
    # Continue with normal processing
    if args.function == "process":
        processor.process_urls_to_json()
    elif args.function == "download":
        processor.download_streetview_images()
    elif args.function == "write":
        processor.write_traj_metainfo(
            traj_id=args.traj_id,
            stride=args.stride,
            rendezvous_point_pano_id=args.pano_id
        )