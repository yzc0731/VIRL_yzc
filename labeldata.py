from flask import Flask, render_template, request, redirect, url_for, send_from_directory
import os
from glob import glob
import re
from collections import defaultdict
import json

app = Flask(__name__)

BASE_FOLDER = 'textdata'
GoogleDataFolder = 'googledata'
HEADING_ORDER = ['front', 'right', 'back', 'left']
Bob_HEADING_ORDER_MAPPING = {
    'front': 'back',
    'right': 'left',
    'back': 'front',
    'left': 'right'
}
ACTION_CHOICES = ['forward', 'turn left', 'turn right', 'turn backward', 'stop']
image_filename_pattern = re.compile(r'streetview_(Alice|Bob)_(\d+)_([\w_]+)\.jpg')
'''
e.g. streetview_Alice_0_front.jpg
e.g. streetview_Bob_1_back_left.jpg'''

def get_grouped_images(random_seed):
    """Obtain the grouped image data and group it by time"""
    # Load the `metainfo.json` file
    traj_folder = f"{BASE_FOLDER}/traj{random_seed}"
    metainfo_path = os.path.join(traj_folder, 'metainfo.json')
    if not os.path.exists(metainfo_path):
        raise FileNotFoundError(f"Metainfo file not found: {metainfo_path}")
    # Load the metainfo file to get the image files
    metainfo = {}
    with open(metainfo_path, 'r', encoding='utf-8') as f:
        metainfo = json.load(f)

    # Check if the required keys are present in the metainfo
    place_id = metainfo.get('place', None)
    rendezvous_point_pano_id = metainfo.get('rendezvous point', None)
    alice_points_list_only_pano_id = metainfo.get('Alice points', [])
    bob_points_list_only_pano_id = metainfo.get('Bob points', [])
    assert place_id is not None, "Place ID is missing in metainfo"
    assert rendezvous_point_pano_id is not None, "Rendezvous point pano ID is missing in metainfo"
    assert len(alice_points_list_only_pano_id) == len(bob_points_list_only_pano_id), \
        "Alice and Bob points lists must have the same length"

    # Get the image files for Alice and Bob
    processed_groups = []
    image_path = os.path.join(GoogleDataFolder, f'place{place_id}')
    for time_index in range(len(alice_points_list_only_pano_id)):
        time_groups = defaultdict(list)
        time_groups['time'] = time_index
        alice_images = []
        bob_images = []
        alice_pano_id = alice_points_list_only_pano_id[time_index]
        bob_pano_id = bob_points_list_only_pano_id[time_index]
        
        # Construct the image filenames based on the pano IDs
        for view_label in HEADING_ORDER:
            alice_image_path = os.path.join(image_path, f'id_{alice_pano_id}_{view_label}.jpg')
            alice_image_relpath = os.path.join(f'place{place_id}', f'id_{alice_pano_id}_{view_label}.jpg')
            bob_view_label = Bob_HEADING_ORDER_MAPPING[view_label]
            bob_image_path = os.path.join(image_path, f'id_{bob_pano_id}_{bob_view_label}.jpg')
            bob_image_relpath = os.path.join(f'place{place_id}', f'id_{bob_pano_id}_{bob_view_label}.jpg')

            # Check if both images exist and add them to the respective lists
            if os.path.exists(alice_image_path) and os.path.exists(bob_image_path):
                alice_images.append({
                    'agent': 'Alice',
                    'time': time_index,
                    'heading': view_label,
                    'filename': alice_image_relpath.replace('\\', '/'),
                    # 'full_path': alice_image_path
                })
                bob_images.append({
                    'agent': 'Bob',
                    'time': time_index,
                    'heading': view_label,
                    'filename': bob_image_relpath.replace('\\', '/'),
                    # 'full_path': bob_image_path
                })
        
        # add alice and bob images to the time_groups
        time_groups['alice'] = alice_images
        time_groups['bob'] = bob_images
        processed_groups.append(time_groups)
    
    return processed_groups

@app.route(f'/{GoogleDataFolder}/<path:filename>')
def custom_static(filename):
    """Serve static files from the googledata folder"""
    return send_from_directory(GoogleDataFolder, filename)

@app.route('/<int:random_seed>', methods=['GET', 'POST'])
def index(random_seed):
    image_groups = get_grouped_images(random_seed)
    if not image_groups:
        return f"No valid image group"

    # Obtain the index of the currently processed group (either from the URL parameter or defaulted to 0)
    current_group_index = int(request.args.get('group', 0))
    
    if request.method == 'POST':
        # Save user input
        data = {
            'time': request.form['time'],
            'landmark': request.form['landmark'],
            'alice_direction': request.form['alice_direction'],
            'bob_direction': request.form['bob_direction'],
            'conclusion': request.form['conclusion'],
            'alice_action': request.form['alice_action'],
            'bob_action': request.form['bob_action']
        }
        
        output_file = os.path.join(BASE_FOLDER, f'traj{random_seed}', 'answer_user.txt')
        
        with open(output_file, 'a', encoding='utf-8') as f:
            f.write(f"{data['time']}|")
            f.write(f"{data['landmark']}|")
            f.write(f"Alice:{data['alice_direction']}|")
            f.write(f"Bob:{data['bob_direction']}|")
            f.write(f"{data['conclusion']}|")
            f.write(f"Alice_action:{data['alice_action']}|")
            f.write(f"Bob_action:{data['bob_action']}\n")
        # After processing the current group, check if there are any more groups
        if current_group_index + 1 < len(image_groups):
            return redirect(url_for('index', 
                                random_seed=random_seed,
                                group=current_group_index + 1))
        else:
            return "All image groups have been annotated!"
    
    # Ensure the index is within a valid range
    current_group_index = min(current_group_index, len(image_groups) - 1)
    current_group = image_groups[current_group_index]
    
    return render_template('index.html',
                         alice_images=current_group['alice'],
                         bob_images=current_group['bob'],
                         current_time=current_group['time'],
                         random_seed=random_seed,
                         action_choices=ACTION_CHOICES,
                         current_group_index=current_group_index,
                         total_groups=len(image_groups))

if __name__ == '__main__':
    app.run(debug=True)