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
from data_utils import calculate_bearing

class GoogleDataProcessor:
    def __init__(self, random_seed: int = 19, api_key: str = None):
        """
        Args:
            random_seed (int): random seed used for data directory naming
            api_key (str): Google Maps API key
        """
        self.random_seed = random_seed
        self.api_key = api_key
        self.coord_pattern_strict = re.compile(r'/@(-?\d+\.\d+),(-?\d+\.\d+),3a')
        self.pano_pattern = re.compile(r'!1s(.*?)!2e')
        self.stride = 2
        self.street_view_url = "https://maps.googleapis.com/maps/api/streetview"
        self.cam_num = 5
        self.label_list = ['0front', '1front_right', '2back_right', '3back_left', '4front_left']

        # Create data directory based on random seed
        self.data_dir = f'./googledata/seed{self.random_seed}'
        os.makedirs(self.data_dir, exist_ok=True)
        self.json_path = os.path.join(self.data_dir, 'pano.json')
        self.txt_path = os.path.join(self.data_dir, 'url.txt')

    def extract_route_data(self, strings_list: List[str]) -> Dict:
        """Read urls from a list of strings and extract (lat, lng, pano_id) for all locations"""
        route = {}
        
        for idx, s in enumerate(strings_list, start=1):
            # 1. Get lat and lng from the string
            lat, lng = None, None
            strict_match = self.coord_pattern_strict.search(s)
            if strict_match:
                lat, lng = float(strict_match.group(1)), float(strict_match.group(2))
                assert -90 <= lat <= 90, "lat must be between -90 and 90"
                assert -180 <= lng <= 180, "lng must be between -180 and 180"
            else:
                raise ValueError(f"No valid coordinates found in string: {s}")

            # 2. Extract pano_id
            pano_match = self.pano_pattern.search(s)
            pano_id = pano_match.group(1) if pano_match else None

            # 3. Store in dictionary
            if lat is not None and lng is not None:
                route[idx] = {
                    'lat': lat,
                    'lng': lng,
                    'panoid': pano_id
                }
        
        return {'route': route}

    def process_urls_to_json(self):
        """Process URLs from the text file and save to JSON"""
        with open(self.txt_path, 'r', encoding='utf-8') as f:
            strings_list = [line.strip() for line in f if line.strip()]
        if not strings_list:
            raise ValueError("Input file is empty or format is incorrect")
        route_data = self.extract_route_data(strings_list)
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(route_data, f, indent=4, ensure_ascii=False)
        print(f"Saved to {self.json_path}")

    def parse_pano_json(self) -> Tuple[List, List, Tuple]:
        """
        Parse JSON file to get Alice and Bob's route points and the end point

        Return:
            Alice_points_list: Alice route points
            Bob_points_list: Bob route points
            end_point
        """ 
        with open(self.json_path, 'r') as f:
            data = json.load(f)
        
        points_dict = data['route']
        points_list = []
        for key, value in points_dict.items():
            points_list.append((value['lat'], value['lng']))

        # plot route
        self.plot_route(coordinates=points_list)
        
        total_len = len(points_list)
        Alice_points_list = []
        Bob_points_list = []
        
        if total_len % 2 == 0:
            Alice_points_list.extend(points_list[:total_len//2][::self.stride])
            Bob_points_list.extend(points_list[total_len//2:][::-1][::self.stride])
            end_point = (
                (points_list[total_len//2 - 1][0] + points_list[total_len//2][0]) / 2,
                (points_list[total_len//2 - 1][1] + points_list[total_len//2][1]) / 2
            )
        else:
            Alice_points_list.extend(points_list[:total_len//2][::self.stride])
            Bob_points_list.extend(points_list[(total_len//2 + 1):][::-1][::self.stride])
            end_point = points_list[total_len//2]

        # plot route only end
        only_end_points_list = [Alice_points_list[0], end_point, Bob_points_list[0]]
        self.plot_route(coordinates=only_end_points_list, output_file='route_only_end.html')
        
        return Alice_points_list, Bob_points_list, end_point

    def download_streetview_images(self):
        """Download Google Street View images"""
        if not self.api_key:
            raise ValueError("API Key not set")

        Alice_points_list, Bob_points_list, end_point = self.parse_pano_json()
        points_dict = {
            'Alice': Alice_points_list,
            'Bob': Bob_points_list
        }
        
        for key, value in points_dict.items():
            for index, loc in enumerate(value):
                latitude, longitude = loc
                fore_heading = calculate_bearing(latitude, longitude, end_point[0], end_point[1])
                heading_list = [(fore_heading + i * (360 / self.cam_num)) % 360 for i in range(self.cam_num)]
                
                for heading, label in zip(heading_list, self.label_list):
                    params = {
                        'size': '640x640',
                        'location': f'{latitude},{longitude}',
                        'heading': heading,
                        'source': 'outdoor',
                        'fov': 90, 
                        'key': self.api_key
                    }

                    response = requests.get(self.street_view_url, params=params)
                    if response.status_code == 200:
                        filename = f"streetview_{key}_{index}_{label}.jpg"
                        filepath = os.path.join(self.data_dir, filename)
                        with open(filepath, "wb") as f:
                            f.write(response.content)
                        print(f"Saved to {filepath}")
                    else:
                        print(f"Error state: {response.status_code}")
                        print(f"Error msg: {response.text}")

    def plot_route(self, coordinates: List[Tuple[float, float]] = None, 
                  output_file: str = 'route.html', 
                  zoom_start: int = 15) -> None:
        """
        Plot route on a map using Folium and save to HTML file
        
        Args:
            coordinates: List of (latitude, longitude) tuples representing the route
            output_file: Path to save the HTML map file (default: 'route.html')
            zoom_start: Initial zoom level for the map (default: 15)

        Returns:
            None
        """
        if not coordinates:
            with open(self.json_path, 'r') as f:
                data = json.load(f)
            
            points_dict = data['route']
            points_list = []
            for key, value in points_dict.items():
                points_list.append((value['lat'], value['lng']))
            coordinates = points_list

        # Create map centered on the first coordinate
        m = folium.Map(location=coordinates[0], zoom_start=zoom_start)
        
        # Add the route as a polyline
        folium.PolyLine(
            coordinates,
            color='blue',
            weight=5,
            opacity=0.8,
            tooltip="Route"
        ).add_to(m)
        
        # Add markers for start and end points
        folium.Marker(
            coordinates[0],
            popup='Start',
            icon=folium.Icon(color='green')
        ).add_to(m)
        
        folium.Marker(
            coordinates[-1],
            popup='End',
            icon=folium.Icon(color='red')
        ).add_to(m)
        
        # Add clickable markers for all waypoints (excluding first and last)
        for i, coord in enumerate(coordinates[1:-1], start=1):
            folium.CircleMarker(
                location=coord,
                radius=5,
                color='orange',
                fill=True,
                fill_color='orange',
                popup=f'Waypoint {i}'
            ).add_to(m)
        
        # Save to HTML file in the data directory
        full_output_path = os.path.join(self.data_dir, output_file)
        m.save(full_output_path)
        print(f"Map saved to {full_output_path}")

    def set_api_key(self, api_key: str):
        """Set Google Maps API key"""
        self.api_key = api_key

    def set_random_seed(self, random_seed: int):
        """Set random seed and update related paths"""
        self.random_seed = random_seed
        self.data_dir = f'./googledata/seed{self.random_seed}'
        os.makedirs(self.data_dir, exist_ok=True)
        self.json_path = os.path.join(self.data_dir, 'pano.json')
        self.txt_path = os.path.join(self.data_dir, 'url.txt')
        
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
        with open(self.txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(urls))
        
        print(f"Generated {len(urls)} Street View URLs and saved to {self.txt_path}")
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
    parser.add_argument("--seed", type=int, default=19, help="Random seed for data directory naming")
    parser.add_argument("--mode", choices=["manual", "auto", "interactive"], default="manual",
                        help="Mode: manual (use url.txt), auto (provide start/end), interactive (map selector)")
    parser.add_argument("--start", help="Start location (lat,lng) for auto mode")
    parser.add_argument("--end", help="End location (lat,lng) for auto mode") 
    parser.add_argument("--samples", type=int, default=10, help="Number of sample points for auto mode")
    args = parser.parse_args()

    processor = GoogleDataProcessor(random_seed=args.seed)
    processor.set_api_key(args.api_key)
    
    if args.mode == "auto":
        if not args.start or not args.end:
            parser.error("--start and --end are required with --mode=auto")
        processor.generate_route(args.start, args.end, args.samples)
    elif args.mode == "interactive":
        processor.generate_route_interactive()
    
    # Continue with normal processing
    processor.process_urls_to_json()
    processor.download_streetview_images()