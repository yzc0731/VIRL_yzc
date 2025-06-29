import math
import os
import json
import time
from typing import List, Dict, Tuple
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from typing import Tuple

def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the bearing from point A (lat1, lon1) to point B (lat2, lon2)
    
    Args:
        lat1: Latitude of point A in decimal degrees
        lon1: Longitude of point A in decimal degrees
        lat2: Latitude of point B in decimal degrees
        lon2: Longitude of point B in decimal degrees
    
    Returns:
        Bearing in degrees from north, measured clockwise (0-360)
    """
    # Convert decimal degrees to radians
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)
    
    # Calculate longitude difference
    dLon = lon2 - lon1
    
    # Calculate bearing components
    y = math.sin(dLon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    bearing = math.atan2(y, x)
    
    # Convert radians to degrees and normalize to 0-360
    bearing = math.degrees(bearing)
    bearing = (bearing + 360) % 360
    
    return bearing

def get_panoids_from_json(json_path: str) -> List[str]:
    """Get all available panoids from the pano.json"""
    assert os.path.exists(json_path), f'file {json_path} not found'
    with open(json_path, 'r') as f:
        data = json.load(f)
    nodes = data.get("nodes", [])
    panoids = list(nodes.keys())
    return panoids


def parse_pano_json_to_dict(json_path: str) -> Dict[str, Tuple[float, float]]:
    """
    Parse JSON file to get points as a dict

    Return:
        points_list: List of tuples with (pano_id, (lat, lng))
    """ 
    with open(json_path, 'r') as f:
        data = json.load(f)
    nodes = data['nodes']
    points_dict = {pano_id: (info['lat'], info['lng']) for pano_id, info in nodes.items()}
    return points_dict

def parse_pano_json_to_list(json_path: str) -> List[Tuple[str, Tuple[float, float]]]:
    """
    Parse JSON file to get points as a list of tuples

    Return:
        points_list: List of tuples with (pano_id, (lat, lng))
    """ 
    with open(json_path, 'r') as f:
        data = json.load(f)
    nodes = data['nodes']
    points_list = [(pano_id, (info['lat'], info['lng'])) for pano_id, info in nodes.items()]
    return points_list

def html_to_screenshot(
        html_file_path: str,
        output_file: str,
        window_size: Tuple[int, int] = (512, 512),
    ) -> None:
    """
    Open an HTML file and create a screenshot of it.

    Args:
        html_file_path: Path to the HTML file to be rendered.
        output_file: Output image file path (default: 'screenshot.png').
        window_size: Browser window size (width, height) for screenshot (default: 800x600).
    """
    # Verify the input file exists
    if not os.path.exists(html_file_path):
        raise FileNotFoundError(f"HTML file not found: {html_file_path}")
    
    # Use selenium to take a screenshot
    options = Options()
    options.add_argument("--headless")  # Run in background
    options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
    
    try:
        service = Service(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        driver = webdriver.Chrome(service=service, options=options)
        absolute_path = os.path.abspath(html_file_path)
        driver.get(f"file://{absolute_path}")
        time.sleep(1)  # Wait for page to load
        
        driver.save_screenshot(output_file)
        driver.quit()
        
        print(f"Screenshot saved to {output_file}")
    except Exception as e:
        print(f"Error creating screenshot: {str(e)}")
        if 'driver' in locals():
            driver.quit()
        raise