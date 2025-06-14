from flask import Flask, render_template, request, redirect, url_for, send_from_directory
import os
from glob import glob
import re
from collections import defaultdict

app = Flask(__name__)

BASE_FOLDER = 'googledata'
HEADING_ORDER = ['front', 'front_right', 'back_right', 'back_left', 'front_left']
ACTION_CHOICES = ['forward', 'turn left', 'turn right', 'turn backward', 'stop']
image_filename_pattern = re.compile(r'streetview_(Alice|Bob)_(\d+)_([\w_]+)\.jpg')
'''
e.g. streetview_Alice_0_front.jpg
e.g. streetview_Bob_1_back_left.jpg'''

def get_grouped_images(random_seed):
    """Obtain the grouped image data and group it by time"""
    seed_folder = f"seed{random_seed}"
    image_dir = os.path.join(BASE_FOLDER, seed_folder)
    image_files = glob(os.path.join(image_dir, 'streetview_*.jpg'))

    # Group by time
    time_groups = defaultdict(list)
    for img_path in image_files:
        info = parse_image_info(img_path)
        if info:
            time_groups[info['time']].append(info)

    # Sort and validate each time group
    processed_groups = []
    for time, images in time_groups.items():
        alice_images = [img for img in images if img['agent'] == 'Alice']
        bob_images = [img for img in images if img['agent'] == 'Bob']
        
        alice_sorted = sort_by_heading(alice_images)
        bob_sorted = sort_by_heading(bob_images)
        
        if len(alice_sorted) == 5 and len(bob_sorted) == 5:
            processed_groups.append({
                'time': time,
                'alice': alice_sorted,
                'bob': bob_sorted
            })
        else:
            print(f"Warning: Time {time} has invalid image counts (Alice: {len(alice_sorted)}, Bob: {len(bob_sorted)})")
    
    return processed_groups

def sort_by_heading(images):
    heading_order = {h: i for i, h in enumerate(HEADING_ORDER)}
    return sorted(images, key=lambda x: heading_order.get(x['heading'], 999))

def parse_image_info(full_path):
    """Parse the image filename to extract agent, time, and heading"""
    rel_path = os.path.relpath(full_path, BASE_FOLDER)
    basename = os.path.basename(full_path)
    match = re.match(image_filename_pattern, basename)
    if match:
        return {
            'agent': match.group(1),
            'time': int(match.group(2)),
            'heading': match.group(3),
            'filename': rel_path.replace('\\', '/'),
            'full_path': full_path
        }
    return None

@app.route(f'/{BASE_FOLDER}/<path:filename>')
def custom_static(filename):
    """Serve static files from the googledata folder"""
    return send_from_directory(BASE_FOLDER, filename)

@app.route('/<int:random_seed>', methods=['GET', 'POST'])
def index(random_seed):
    image_groups = get_grouped_images(random_seed)
    if not image_groups:
        return f"No valid image group found in the {BASE_FOLDER}/seed{random_seed}"

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
        
        output_file = os.path.join(BASE_FOLDER, f'seed{random_seed}', 'answer_user.txt')
        
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