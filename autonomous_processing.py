import os
import argparse
import subprocess
import glob
import json

def get_available_place_ids():
    """
    Scan the googledata directory to find all place folders.
    Returns a list of place IDs.
    """
    place_folders = glob.glob('googledata/place*')
    place_ids = []
    
    for folder in place_folders:
        try:
            # Extract place ID from folder name
            place_id = int(folder.split('place')[-1])
            place_ids.append(place_id)
        except ValueError:
            # Skip if the folder name doesn't follow the expected format
            continue
    
    return sorted(place_ids)

def should_process_url(place_id):
    """
    Check if a place folder has url.txt but no pano.json.
    Returns True if processing is needed, False otherwise.
    """
    url_path = f'googledata/place{place_id}/url.txt'
    pano_path = f'googledata/place{place_id}/pano.json'
    
    return os.path.exists(url_path) and not os.path.exists(pano_path)

def should_download_images(place_id):
    """
    Check if a place folder has pano.json but no images at all.
    Returns True if downloading is needed (no images found), False otherwise.
    """
    pano_path = f'googledata/place{place_id}/pano.json'
    
    if not os.path.exists(pano_path):
        return False
    
    # Check if there are any JPG images in the folder
    image_count = len(glob.glob(f'googledata/place{place_id}/id_*.jpg'))
    
    # Only download if there are no images at all
    return image_count == 0

def get_places_with_images():
    """
    Return a list of place IDs that have both pano.json and images.
    """
    place_ids = get_available_place_ids()
    result = []
    
    for place_id in place_ids:
        pano_path = f'googledata/place{place_id}/pano.json'
        if os.path.exists(pano_path):
            # Check if there are any JPG images in the folder
            image_count = len(glob.glob(f'googledata/place{place_id}/id_*.jpg'))
            if image_count > 0:
                result.append(place_id)
    
    return result

def get_highest_traj_id():
    """
    Find the highest existing trajectory ID.
    Returns 0 if no trajectories exist.
    """
    traj_folders = glob.glob('textdata/traj*')
    traj_ids = []
    
    for folder in traj_folders:
        try:
            # Extract traj ID from folder name
            traj_id = int(folder.split('traj')[-1])
            traj_ids.append(traj_id)
        except ValueError:
            # Skip if the folder name doesn't follow the expected format
            continue
    
    return max(traj_ids, default=-1)  # Return -1 if no trajectories exist

def should_create_trajectory(place_id, traj_id):
    """
    Check if a trajectory needs to be created.
    Returns True if creation is needed, False otherwise.
    """
    traj_path = f'textdata/traj{traj_id}'
    metainfo_path = f'{traj_path}/metainfo.json'
    
    # If the trajectory folder doesn't exist or doesn't have metainfo.json
    if not os.path.exists(metainfo_path):
        # Create the directory if it doesn't exist
        os.makedirs(traj_path, exist_ok=True)
        return True
    
    # Check if metainfo.json references this place_id
    try:
        with open(metainfo_path, 'r') as f:
            metainfo = json.load(f)
        return metainfo.get('place') != place_id
    except:
        # If there's any error reading or parsing the file, assume we need to create
        return True

def execute_command(command):
    """
    Execute a shell command and print its output.
    """
    print(f"Executing: {command}")
    process = subprocess.Popen(
        command, 
        shell=True, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        universal_newlines=True
    )
    
    stdout, stderr = process.communicate()
    
    if stdout:
        print(f"Output:\n{stdout}")
    if stderr:
        print(f"Error:\n{stderr}")
    
    return process.returncode

def process_url_files(api_key, place_ids=None):
    """
    Process all place folders that have url.txt but no pano.json.
    """
    if place_ids is None:
        place_ids = get_available_place_ids()
    
    processed_count = 0
    for place_id in place_ids:
        if should_process_url(place_id):
            print(f"Processing URL for place{place_id}...")
            command = f"python googledataprocess.py --api-key {api_key} --seed {place_id} --function process"
            
            if execute_command(command) == 0:
                processed_count += 1
                print(f"Successfully processed URL for place{place_id}")
            else:
                print(f"Failed to process URL for place{place_id}")
    
    return processed_count

def download_street_views(api_key, place_ids=None):
    """
    Download street view images for all place folders that have pano.json.
    """
    if place_ids is None:
        place_ids = get_available_place_ids()
    
    downloaded_count = 0
    for place_id in place_ids:
        if should_download_images(place_id):
            print(f"Downloading street view images for place{place_id}...")
            command = f"python googledataprocess.py --api-key {api_key} --seed {place_id} --function download"
            
            if execute_command(command) == 0:
                downloaded_count += 1
                print(f"Successfully downloaded street view images for place{place_id}")
            else:
                print(f"Failed to download street view images for place{place_id}")
    
    return downloaded_count

def create_trajectories(api_key, start_traj_id, stride, place_ids=None, rendezvous_pano_id=None):
    """
    Create trajectories for all place folders that have pano.json and images.
    Start from the given traj_id and increment for each place.
    """
    if place_ids is None:
        place_ids = get_places_with_images()
    
    if not place_ids:
        print("No places with images found!")
        return 0
    
    created_count = 0
    current_traj_id = start_traj_id
    
    for place_id in place_ids:
        print(f"Creating trajectory from place{place_id} to traj{current_traj_id}...")
        
        command = f"python googledataprocess.py --api-key {api_key} --seed {place_id} --function write --traj-id {current_traj_id} --stride {stride}"
        
        if rendezvous_pano_id:
            command += f" --pano-id {rendezvous_pano_id}"
        
        if execute_command(command) == 0:
            created_count += 1
            print(f"Successfully created trajectory from place{place_id} to traj{current_traj_id}")
        else:
            print(f"Failed to create trajectory from place{place_id} to traj{current_traj_id}")
        
        # Increment traj_id for the next place
        current_traj_id += 1
    
    return created_count

def main():
    parser = argparse.ArgumentParser(description="Autonomous processing for Google Street View data")
    
    parser.add_argument("--api-key", type=str, required=True, help="Google Maps API key")
    parser.add_argument("--process-url", action="store_true", help="Process URL files to create pano.json")
    parser.add_argument("--download", action="store_true", help="Download street view images")
    parser.add_argument("--create-trajectory", action="store_true", help="Create trajectories")
    parser.add_argument("--traj-id", type=int, default=None, help="Starting trajectory ID for creation (optional, defaults to highest existing + 1)")
    parser.add_argument("--stride", type=int, default=2, help="Stride for trajectory creation")
    parser.add_argument("--pano-id", type=str, help="Rendezvous panorama ID (optional)")
    parser.add_argument("--place-ids", type=str, help="Comma-separated list of place IDs to process (optional)")
    
    args = parser.parse_args()
    
    # Parse place IDs if provided
    place_ids = None
    if args.place_ids:
        try:
            place_ids = [int(pid.strip()) for pid in args.place_ids.split(",")]
        except ValueError:
            print("Error: place-ids should be a comma-separated list of integers")
            return
    
    # Execute the requested operations
    if args.process_url:
        print("=== Processing URL files ===")
        count = process_url_files(args.api_key, place_ids)
        print(f"Processed {count} place folders")
    
    if args.download:
        print("=== Downloading street view images ===")
        count = download_street_views(args.api_key, place_ids)
        print(f"Downloaded images for {count} place folders")
    
    if args.create_trajectory:
        print("=== Creating trajectories ===")
        # If traj_id is not specified, find the highest existing one and add 1
        start_traj_id = args.traj_id
        if start_traj_id is None:
            start_traj_id = get_highest_traj_id() + 1
            print(f"No trajectory ID specified, starting from {start_traj_id} (highest existing + 1)")
        
        # If place_ids is not specified, use all places with images
        if place_ids is None:
            place_ids = get_places_with_images()
            print(f"Using {len(place_ids)} places with images: {place_ids}")
        
        count = create_trajectories(args.api_key, start_traj_id, args.stride, place_ids, args.pano_id)
        print(f"Created {count} trajectories")

if __name__ == "__main__":
    main()
