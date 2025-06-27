import re
import json
import os
import folium.features
import requests
import folium
import polyline
import time
import tempfile
import webbrowser
from typing import List, Tuple, Dict
from data_utils import calculate_bearing
# import matplotlib.pyplot as plt
# import cartopy.crs as ccrs
# import cartopy.feature as cfeature
# from selenium import webdriver
# from selenium.webdriver.chrome.options import Options
# from webdriver_manager.chrome import ChromeDriverManager
# from selenium.webdriver.chrome.service import Service

class GoogleDataProcessor:
    def __init__(self, seed: int, api_key: str):
        """
        Args:
            seed (int): random seed used for data directory naming
            api_key (str): Google Maps API key
        """
        self.seed = seed
        self.api_key = api_key
        self.coord_pattern_strict = re.compile(r'/@(-?\d+\.\d+),(-?\d+\.\d+),')
        self.pano_pattern = re.compile(r'!1s(.*?)!2e')
        self.street_view_url = "https://maps.googleapis.com/maps/api/streetview"
        self.cam_num = 4
        self.label_list = ['front', 'right', 'back', 'left']

        # Create data directory based on random seed
        self.data_dir = f'./googledata/place{self.seed}'
        os.makedirs(self.data_dir, exist_ok=True)
        self.json_path = os.path.join(self.data_dir, 'pano.json')
        self.url_path = os.path.join(self.data_dir, 'url.txt')
        self.points_html_path = os.path.join(self.data_dir, 'points.html')

    def extract_graph_data(self, strings_list: List[str]) -> Dict:
        """Read urls from a list of strings and extract (lat, lng, pano_id) for all locations"""
        nodes = {}
        
        for _, s in enumerate(strings_list, start=0): # 0 is the start point of Alice, 1 is the waypoint 1 in route.html
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
                nodes[pano_id] = {
                    'lat': lat,
                    'lng': lng
                }
        
        self.plot_points(nodes=nodes)

        return {'nodes': nodes}

    def extract_route_data(self, strings_list: List[str]) -> Dict:
        """Warning: This method is deprecated. Use `extract_graph_data` instead.
        Read urls from a list of strings and extract (lat, lng, pano_id) for all locations"""
        route = {}
        
        for idx, s in enumerate(strings_list, start=0): # 0 is the start point of Alice, 1 is the waypoint 1 in route.html
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
        with open(self.url_path, 'r', encoding='utf-8') as f:
            strings_list = [line.strip() for line in f if line.strip()]
        if not strings_list:
            raise ValueError("Input file is empty or format is incorrect")
        route_data = self.extract_graph_data(strings_list)
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(route_data, f, indent=4, ensure_ascii=False)
        print(f"Saved to {self.json_path}")

    def parse_pano_json_to_dict(self) -> Dict[str, Tuple[float, float]]:
        """
        Parse JSON file to get points

        Return:
            points_list: List of tuples with (pano_id, (lat, lng))
        """ 
        with open(self.json_path, 'r') as f:
            data = json.load(f)
        nodes = data['nodes']
        points_dict = {pano_id: (info['lat'], info['lng']) for pano_id, info in nodes.items()}
        return points_dict
    
    def parse_pano_json_to_list(self) -> List[Tuple[str, Tuple[float, float]]]:
        """
        Parse JSON file to get points

        Return:
            points_list: List of tuples with (pano_id, (lat, lng))
        """ 
        with open(self.json_path, 'r') as f:
            data = json.load(f)
        nodes = data['nodes']
        points_list = [(pano_id, (info['lat'], info['lng'])) for pano_id, info in nodes.items()]
        return points_list
        
        # total_len = len(points_list)
        # Alice_points_list = []
        # Bob_points_list = []
        
        # if total_len % 2 == 0:
        #     Alice_points_list.extend(points_list[:total_len//2][::self.stride])
        #     Bob_points_list.extend(points_list[total_len//2:][::-1][::self.stride])
        #     end_point = (
        #         (points_list[total_len//2 - 1][0] + points_list[total_len//2][0]) / 2,
        #         (points_list[total_len//2 - 1][1] + points_list[total_len//2][1]) / 2
        #     )

        # self.plot_agent_positions_to_image(
        #     alice_coord=Alice_points_list[0],
        #     bob_coord=Bob_points_list[0],
        #     meet_coord=end_point,
        # )
        
        # return Alice_points_list, Bob_points_list, end_point
    
    def add_fore_heading_to_points(
        self, 
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

    def download_streetview_images(self):
        """Download Google Street View images"""
        points_list = self.parse_pano_json_to_list()
        points_dict = self.add_fore_heading_to_points(points_list)

        # self.plot_agent_positions_to_image_w_heading(
        #     alice_coord=(points_dict['Alice'][0][0], points_dict['Alice'][0][1]),
        #     alice_direction=points_dict['Alice'][0][2],
        #     bob_coord=(points_dict['Bob'][0][0], points_dict['Bob'][0][1]),
        #     bob_direction=points_dict['Bob'][0][2],
        #     meet_coord=(points_dict['Alice'][-1][0], points_dict['Alice'][-1][1])
        # )

        for key, value in points_dict.items():
            latitude, longitude, fore_heading = value
            heading_list = [(fore_heading + i * (360 / self.cam_num)) % 360 for i in range(self.cam_num)]
                
            for heading, label in zip(heading_list, self.label_list):
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
    
    def plot_points(self, nodes: Dict[str, Dict[str, float]],
                    zoom_start: int = 20) -> None:
        """
        Plot points on a map using Folium and save to HTML file
        
        Args:
            nodes: Dictionary of nodes with keys as node IDs and values as dictionaries containing 'lat' and 'lng'
            zoom_start: Initial zoom level for the map (default: 20)
        """
        # convert nodes to a list of tuples
        nodes_dict = {key: (value['lat'], value['lng']) for key, value in nodes.items()}
        # nodes_list is the type Dict[str, Tuple[float, float]]

        # Create map centered on the first coordinate
        first_key = next(iter(nodes_dict))
        first_value = nodes_dict[first_key]
        m = folium.Map(location=first_value, zoom_start=zoom_start)
        
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
    
    def sample_points_by_stride(
        self,
        points_list: List[Tuple[str, Tuple[float, float]]],
        traj_id: int = 0,
        stride: int = 1,
    ) -> List[Tuple[str, Tuple[float, float]]]:
        textdata_dir = f'./textdata/traj{traj_id}'
        os.makedirs(textdata_dir, exist_ok=True)
        metainfo_path = os.path.join(textdata_dir, 'metainfo.json')

        len_points = len(points_list)
        renderzvous_point = points_list[len_points // 2]
        renderzvous_point_pano_id = renderzvous_point[0]
        alice_points_list = points_list[:len_points // 2][::stride]
        bob_points_list = points_list[(len_points // 2 + 1):][::-1][::stride]

        # save all the information to a json file
        metainfo = {
            'stride': stride,
            'renderzvous point': renderzvous_point_pano_id,
            'Alice points': [pano_id for pano_id, _ in alice_points_list],
            'Bob points': [pano_id for pano_id, _ in bob_points_list],
        }
        with open(metainfo_path, 'w', encoding='utf-8') as f:
            json.dump(metainfo, f, indent=4, ensure_ascii=False)
        print(f"Saved trajectory metainfo to {metainfo_path} with stride {stride}")
        
        # plot the route
        self.plot_route(
            renderzvous_point=renderzvous_point,
            alice_points_list=alice_points_list,
            bob_points_list=bob_points_list,
            traj_id=traj_id,
        )
        print(f"Route plotted and saved to {textdata_dir}/route.html")

    def write_traj_metainfo(self, traj_id = 0, stride = -1, renderzvous_point_pano_id = None):
        """ Write traj information to a text file
        Args:
            traj_id (int): The trajectory ID, default is 0.
            stride (int): The stride for the trajectory, default is 1.
        """
        # mode 1, only input a stride, calculate the alice route and bob route automatically acoording to the stride. 
        if renderzvous_point_pano_id is not None:
            points_dict = self.parse_pano_json_to_dict()
            # check if the renderzvous point is in the points_dict
            if renderzvous_point_pano_id not in points_dict:
                raise ValueError(f"Renderzvous point {renderzvous_point_pano_id} not found in pano.json")
            
            copy_flag = False
            alice_points_list = []
            bob_points_list = []
            for pano_id, location in points_dict.items():
                if pano_id == renderzvous_point_pano_id:
                    copy_flag = True
                    continue  # skip the renderzvous point itself
                if copy_flag:
                    bob_points_list.append((pano_id, location))
                else:
                    alice_points_list.append((pano_id, location))
                
            # then sample the points by stride
            if stride > 0:
                alice_points_list = alice_points_list[::stride]
                bob_points_list = bob_points_list[::-1][::stride]
                # append alice and bob points to the same length, if bob < alice, then copy the last bob point
                if len(bob_points_list) < len(alice_points_list):
                    last_bob_point = bob_points_list[-1]
                    bob_points_list.extend([last_bob_point] * (len(alice_points_list) - len(bob_points_list)))
                elif len(bob_points_list) > len(alice_points_list):
                    last_alice_point = alice_points_list[-1]
                    alice_points_list.extend([last_alice_point] * (len(bob_points_list) - len(alice_points_list)))

                # save all the information to a json file
                metainfo = {
                    'stride': stride,
                    'renderzvous point': renderzvous_point_pano_id,
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
                renderzvous_point_location = points_dict[renderzvous_point_pano_id]
                self.plot_route(
                    renderzvous_point=(renderzvous_point_pano_id, renderzvous_point_location),
                    alice_points_list=alice_points_list,
                    bob_points_list=bob_points_list,
                    traj_id=traj_id,
                )

        else:
            if stride > 0:
                points_list = self.parse_pano_json_to_list()
                # points_list_only_pano_id = [pano_id for pano_id, _ in points_list]
                len_points = len(points_list)
                assert len_points > 0, "No points found in pano.json"
                if len_points % 2 == 0: # even number of points
                    points_list.pop() # remove the last point
                    len_points -= 1
                # else: # odd number of points, choose the middle point as the end point
                #     pass
                self.sample_points_by_stride(
                    points_list=points_list,
                    traj_id=traj_id,
                    stride=stride,
                )

    def plot_route(self, renderzvous_point: Tuple[str, Tuple[float, float]],
                   alice_points_list: List[Tuple[str, Tuple[float, float]]],
                   bob_points_list: List[Tuple[str, Tuple[float, float]]], 
                   traj_id: int, 
                   zoom_start: int = 20) -> None:
        """
        Plot route on a map using Folium and save to HTML file
        
        Args:
            renderzvous_point: Tuple with pano_id and (lat, lng) of the renderzvous point
            alice_points_list: List of tuples with (pano_id, (lat, lng))
            bob_points_list: List of tuples with (pano_id, (lat, lng))
            traj_id: Trajectory ID for saving the output file
            zoom_start: Initial zoom level for the map (default: 20)
        """
        # Create map centered on the first coordinate
        renderzvous_point_pano_id, renderzvous_point_location = renderzvous_point
        m = folium.Map(location=renderzvous_point_location, zoom_start=zoom_start)

        # Add markers for start and end points
        folium.Marker(
            renderzvous_point_location,
            popup=f'Renderzvous {renderzvous_point_pano_id}',
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
        alice_polyline_coords.append(renderzvous_point_location)
        bob_polyline_coords = [coord for _, coord in bob_points_list]
        bob_polyline_coords.append(renderzvous_point_location)
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
        print(f"Route saved to {full_output_path}")

    def set_api_key(self, api_key: str):
        """Set Google Maps API key"""
        self.api_key = api_key

    def set_seed(self, seed: int):
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
    parser.add_argument("--seed", type=int, help="Random seed for data directory naming")
    parser.add_argument("--mode", choices=["manual", "auto", "interactive"], default="manual",
                        help="Mode: manual (use url.txt), auto (provide start/end), interactive (map selector)")
    parser.add_argument("--start", help="Start location (lat,lng) for auto mode")
    parser.add_argument("--end", help="End location (lat,lng) for auto mode") 
    parser.add_argument("--samples", type=int, default=10, help="Number of sample points for auto mode")
    args = parser.parse_args()

    processor = GoogleDataProcessor(seed=args.seed, api_key=args.api_key)
    
    if args.mode == "auto":
        if not args.start or not args.end:
            parser.error("--start and --end are required with --mode=auto")
        processor.generate_route(args.start, args.end, args.samples)
    elif args.mode == "interactive":
        processor.generate_route_interactive()
    
    # Continue with normal processing
    # processor.process_urls_to_json()
    # processor.download_streetview_images()
    processor.write_traj_metainfo(traj_id=1, stride=2, renderzvous_point_pano_id='9RES6v0M_QVD4Or2bO9k9g')