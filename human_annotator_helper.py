import argparse
import subprocess
import os
import time
import webbrowser
import signal
import sys
import glob

# Constants
TEXTDATA_FOLDER = 'textdata'
PORT = 5000
HOST = "127.0.0.1"

def get_existing_traj_ids():
    """
    Get a list of all existing trajectory IDs
    
    Returns:
        List of integers representing existing trajectory IDs
    """
    traj_folders = glob.glob(f'{TEXTDATA_FOLDER}/traj*')
    traj_ids = []
    
    for folder in traj_folders:
        try:
            # Extract traj ID from folder name
            traj_id = int(folder.split('traj')[-1])
            traj_ids.append(traj_id)
        except ValueError:
            # Skip if the folder name doesn't follow the expected format
            continue
    
    return sorted(traj_ids)

def check_answer_exists(traj_id):
    """
    Check if an answer.json file already exists for a trajectory
    
    Args:
        traj_id: ID of the trajectory to check
        
    Returns:
        True if answer.json exists, False otherwise
    """
    answer_path = f'{TEXTDATA_FOLDER}/traj{traj_id}/answer.json'
    return os.path.exists(answer_path)

def wait_for_file_change(file_path, initial_size=None, timeout=300):
    """
    Wait for a file to change size, indicating user has added annotations
    
    Args:
        file_path: Path to the file to monitor
        initial_size: Initial file size to compare against
        timeout: Maximum time to wait in seconds
    
    Returns:
        True if file changed, False if timeout occurred
    """
    if initial_size is None:
        initial_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if os.path.exists(file_path):
            current_size = os.path.getsize(file_path)
            if current_size > initial_size:
                return True
        time.sleep(1)
    
    return False

def run_annotation_server(traj_id):
    """
    Start the annotation server for a specific trajectory ID
    
    Args:
        traj_id: ID of the trajectory to annotate
        
    Returns:
        Subprocess object representing the server process
    """
    cmd = f"python googledataannotator.py --mode open --seed {traj_id} --view_mode label --port {PORT} --host {HOST}"
    process = subprocess.Popen(cmd, shell=True)
    
    # Give the server time to start
    time.sleep(2)
    
    return process

def convert_annotations(traj_id):
    """
    Convert answer_user.txt to answer.json for a trajectory
    
    Args:
        traj_id: ID of the trajectory to convert
        
    Returns:
        True if conversion was successful, False otherwise
    """
    cmd = f"python googledataannotator.py --mode convert --seed {traj_id}"
    result = subprocess.run(cmd, shell=True, capture_output=True)
    return result.returncode == 0

def annotate_trajectory(traj_id, wait_timeout=300):
    """
    Handle the annotation process for a single trajectory
    
    Args:
        traj_id: ID of the trajectory to annotate
        wait_timeout: Maximum time to wait for user input in seconds
        
    Returns:
        True if annotation was completed, False otherwise
    """
    print(f"\n{'='*50}")
    print(f"Starting annotation for trajectory {traj_id}")
    print(f"{'='*50}")
    
    # Check if answer_user.txt exists and get its initial size
    answer_user_path = f'{TEXTDATA_FOLDER}/traj{traj_id}/answer_user.txt'
    initial_size = os.path.getsize(answer_user_path) if os.path.exists(answer_user_path) else 0
    
    # Start the annotation server
    server_process = run_annotation_server(traj_id)
    
    # Open the browser
    annotation_url = f"http://{HOST}:{PORT}/{traj_id}/label"
    webbrowser.open(annotation_url)
    
    print(f"Please annotate the trajectory in your browser at {annotation_url}")
    print(f"Waiting for annotations (timeout: {wait_timeout} seconds)...")
    
    # Wait for the user to make annotations AND complete the entire trajectory
    # We'll monitor for changes to answer_user.txt and also check if it has the expected number of entries
    completed = False
    start_time = time.time()
    
    while time.time() - start_time < wait_timeout:
        # Check if the file has changed
        if os.path.exists(answer_user_path):
            current_size = os.path.getsize(answer_user_path)
            
            # File has changed, check if all entries have been annotated
            if current_size > initial_size:
                # Check if annotations are complete by counting the number of entries in answer_user.txt
                with open(answer_user_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    line_count = len([line for line in content.split('\n') if line.strip()])
                
                # Get the expected number of entries from metainfo.json
                metainfo_path = f'{TEXTDATA_FOLDER}/traj{traj_id}/metainfo.json'
                if os.path.exists(metainfo_path):
                    with open(metainfo_path, 'r', encoding='utf-8') as f:
                        import json
                        metainfo = json.load(f)
                        # Expected entries = Alice points length + 1 (for rendezvous point)
                        expected_entries = len(metainfo.get('Alice points', [])) + 1
                        
                        if line_count >= expected_entries:
                            completed = True
                            break
        
        time.sleep(1)
    
    # Stop the server
    server_process.terminate()
    
    if not completed:
        print(f"Annotation for trajectory {traj_id} was not completed within the timeout period.")
        return False
    
    # Convert annotations to JSON
    print(f"Converting annotations for trajectory {traj_id}...")
    success = convert_annotations(traj_id)
    
    if success:
        print(f"Successfully annotated and converted trajectory {traj_id}")
        return True
    else:
        print(f"Failed to convert annotations for trajectory {traj_id}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Human annotation helper for multiple trajectories")
    
    # Add arguments for trajectory selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--traj-id", type=int, help="Single trajectory ID to annotate")
    group.add_argument("--traj-range", type=str, help="Range of trajectory IDs to annotate (e.g., '0-5')")
    group.add_argument("--traj-list", type=str, help="Comma-separated list of trajectory IDs to annotate (e.g., '0,1,3')")
    group.add_argument("--all-trajs", action="store_true", help="Annotate all existing trajectories")
    group.add_argument("--unannotated", action="store_true", help="Annotate all trajectories without answer.json")
    
    # Additional options
    parser.add_argument("--wait-time", type=int, default=300, 
                        help="Maximum time to wait for user input per trajectory (in seconds)")
    parser.add_argument("--skip-existing", action="store_true", 
                        help="Skip trajectories that already have answer.json files")
    
    args = parser.parse_args()
    
    # Determine which trajectories to annotate
    traj_ids = []
    
    if args.traj_id is not None:
        traj_ids = [args.traj_id]
    elif args.traj_range:
        try:
            start, end = map(int, args.traj_range.split('-'))
            traj_ids = list(range(start, end + 1))
        except ValueError:
            print("Error: Invalid range format. Please use 'start-end' (e.g., '0-5')")
            return
    elif args.traj_list:
        try:
            traj_ids = [int(traj_id) for traj_id in args.traj_list.split(',')]
        except ValueError:
            print("Error: Invalid list format. Please use comma-separated integers (e.g., '0,1,3')")
            return
    elif args.all_trajs or args.unannotated:
        existing_traj_ids = get_existing_traj_ids()
        if not existing_traj_ids:
            print("No trajectory folders found")
            return
            
        if args.unannotated:
            traj_ids = [traj_id for traj_id in existing_traj_ids if not check_answer_exists(traj_id)]
            if not traj_ids:
                print("All existing trajectories have already been annotated")
                return
        else:
            traj_ids = existing_traj_ids
    
    # Validate trajectories exist
    valid_traj_ids = []
    for traj_id in traj_ids:
        traj_path = f'{TEXTDATA_FOLDER}/traj{traj_id}'
        if os.path.exists(traj_path):
            if args.skip_existing and check_answer_exists(traj_id):
                print(f"Skipping trajectory {traj_id} as it already has annotations")
                continue
            valid_traj_ids.append(traj_id)
        else:
            print(f"Warning: Trajectory folder for traj{traj_id} does not exist")
    
    if not valid_traj_ids:
        print("No valid trajectories to annotate")
        return
    
    print(f"Will annotate the following trajectories: {valid_traj_ids}")
    input("Press Enter to begin the annotation process...")
    
    # Handle CTRL+C gracefully
    def signal_handler(sig, frame):
        print("\nProcess interrupted by user")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Annotate each trajectory
    completed = 0
    for i, traj_id in enumerate(valid_traj_ids):
        print(f"\nProcessing trajectory {traj_id} ({i+1}/{len(valid_traj_ids)})")
        
        try:
            success = annotate_trajectory(traj_id, args.wait_time)
            if success:
                completed += 1
            
            # Wait for user confirmation before proceeding to the next trajectory
            if i < len(valid_traj_ids) - 1:  # If not the last trajectory
                input(f"\nAnnotation for trajectory {traj_id} completed. Press Enter to continue to the next trajectory...")
        except Exception as e:
            print(f"Error annotating trajectory {traj_id}: {e}")
    
    print(f"\nAnnotation process completed. Successfully annotated {completed}/{len(valid_traj_ids)} trajectories.")

if __name__ == "__main__":
    main()
