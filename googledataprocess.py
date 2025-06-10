import re
import json
import os
import requests
import folium
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

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Google Street View 数据下载工具")
    parser.add_argument(
        "--api-key",
        required=True,
    )
    parser.add_argument(
        "--seed",
        type=int,
    )
    args = parser.parse_args()

    processor = GoogleDataProcessor(random_seed=args.seed)
    processor.process_urls_to_json()
    # processor.plot_route()
    processor.set_api_key(args.api_key)
    processor.download_streetview_images()