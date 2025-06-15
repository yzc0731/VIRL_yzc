from flask import Flask, render_template, request, redirect, url_for, send_from_directory
import os
import json
from glob import glob
import re
from collections import defaultdict
import argparse

app = Flask(__name__)

BASE_FOLDER = 'googledata'
ACTION_CHOICES = ['forward', 'turn left', 'turn right', 'turn backward', 'stop']

class GoogleDataAnnotator:
    def __init__(self, base_folder, seed):
        self.base_folder = base_folder
        self.seed = seed
        self.camera_num = 4
        self.folder = os.path.join(base_folder, f'seed{seed}')
        if not os.path.exists(self.folder):
            raise FileNotFoundError(f"Seed folder {self.folder} does not exist.")
        self.image_filename_pattern = re.compile(r'streetview_(Alice|Bob)_(\d+)_([\w_]+)\.jpg')
        self.heading_order = ['front', 'right', 'back', 'left']

    def sort_by_heading(self, images):
        heading_order = {h: i for i, h in enumerate(self.heading_order)}
        return sorted(images, key=lambda x: heading_order.get(x['heading'], 999))

    def parse_image_info(self, full_path):
        """Parse the image filename to extract agent, time, and heading"""
        rel_path = os.path.relpath(full_path, self.base_folder)
        basename = os.path.basename(full_path)
        match = re.match(self.image_filename_pattern, basename)
        if match:
            return {
                'agent': match.group(1),
                'time': int(match.group(2)),
                'heading': match.group(3),
                'filename': rel_path.replace('\\', '/'),
                'full_path': full_path
            }
        return None

    def load_images(self):
        """Load images and group them by time"""
        image_files = glob(os.path.join(self.folder, 'streetview_*.jpg'))
        time_groups_images = defaultdict(list)
        for img_path in image_files:
            info = self.parse_image_info(img_path)
            if info:
                time_groups_images[info['time']].append(info)
        return time_groups_images

    def load_answers(self):
        """Load answers from the json file"""
        answer_file = os.path.join(self.folder, 'answer.json')
        if os.path.exists(answer_file):
            with open(answer_file, 'r') as f:
                answers = json.load(f)
        else:
            answers = {}
        return answers

    def process_images(self):
        """Load and process the images data"""
        time_groups_images = self.load_images()

        # process each time group and sort images by agent and heading
        processed_groups = []
        for time, images in time_groups_images.items():
            alice_images = [img for img in images if img['agent'] == 'Alice']
            bob_images = [img for img in images if img['agent'] == 'Bob']
            
            alice_sorted = self.sort_by_heading(alice_images)
            bob_sorted = self.sort_by_heading(bob_images)
            
            if len(alice_sorted) == self.camera_num and len(bob_sorted) == self.camera_num:
                processed_groups.append({
                    'time': time,
                    'alice': alice_sorted,
                    'bob': bob_sorted
                })
            else:
                print(f"Warning: Time {time} has invalid image counts (Alice: {len(alice_sorted)}, Bob: {len(bob_sorted)})")
        
        return processed_groups

    def process_images_and_answers(self):
        """Load and process the images data and answers"""
        time_groups_images = self.load_images()
        answers = self.load_answers()

        # process each time group and sort images by agent and heading, and append answers
        processed_groups = []
        for time, images in time_groups_images.items():
            alice_images = [img for img in images if img['agent'] == 'Alice']
            bob_images = [img for img in images if img['agent'] == 'Bob']
            
            alice_sorted = self.sort_by_heading(alice_images)
            bob_sorted = self.sort_by_heading(bob_images)

            if len(alice_sorted) == self.camera_num and len(bob_sorted) == self.camera_num:
                time_str = str(time)
                group_answers = answers.get(time_str, {
                    "Thought": {
                        "Detection": "",
                        "Orientation": {"Alice": "", "Bob": ""},
                        "Conclusion": ""
                    },
                    "Answer": {"Alice": "", "Bob": ""}
                }) # Here is the default structure for answers if not found
                
                processed_groups.append({
                    'time': time,
                    'alice': alice_sorted,
                    'bob': bob_sorted,
                    'answers': group_answers
                })
        
        return processed_groups

    def parse_line(self, line):
        """Parse a single line of data and return a dictionary"""
        result = {}
        pattern = re.compile(
            r"(?P<id>\d+)\|"
            r"(?P<detection>[^|]+)\|"
            r"Alice:(?P<alice_orientation>[^|]+)\|"
            r"Bob:(?P<bob_orientation>[^|]+)\|"
            r"(?P<conclusion>[^|]+)\|"
            r"Alice_action:(?P<alice_action>\w+)\|"
            r"Bob_action:(?P<bob_action>\w+)"
        )
        
        match = pattern.match(line)
        if not match:
            raise ValueError(f"Line format doesn't match expected pattern: {line}")

        experiment_id = match.group('id')
        result[experiment_id] = {
            "Thought": {
                "Detection": match.group('detection').strip(),
                "Orientation": {
                    "Alice": match.group('alice_orientation').strip(),
                    "Bob": match.group('bob_orientation').strip()
                },
                "Conclusion": match.group('conclusion').strip()
            },
            "Answer": {
                "Alice": match.group('alice_action').strip(),
                "Bob": match.group('bob_action').strip()
            }
        }
        
        return result

    def txt_to_json(self, input_file, output_file):
        """Convert the entire txt file to json"""
        final_result = {}
        
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    line_data = self.parse_line(line)
                    final_result.update(line_data)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, indent=4, ensure_ascii=False)

@app.route(f'/{BASE_FOLDER}/<path:filename>')
def custom_static(filename):
    """Serve static files from the googledata folder"""
    return send_from_directory(BASE_FOLDER, filename)

def handle_label(annotator):
    image_groups = annotator.process_images()
    if not image_groups:
        return f"No valid image group found in the {BASE_FOLDER}/seed{annotator.seed}"

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

        output_file = os.path.join(BASE_FOLDER, f'seed{annotator.seed}', 'answer_user.txt')

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
            return redirect(url_for('handle_request', 
                                seed=annotator.seed,
                                mode='label',
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
                         action_choices=ACTION_CHOICES,
                         current_group_index=current_group_index,
                         total_groups=len(image_groups))

def handle_convert(annotator):
    """Convert the answer_user.txt to answer.json"""
    input_file = os.path.join(annotator.folder, 'answer_user.txt')
    output_file = os.path.join(annotator.folder, 'answer.json')
    annotator.txt_to_json(input_file, output_file)
    return f"Converted {input_file} to {output_file}"

def handle_view(annotator):
    image_groups = annotator.process_images_and_answers()
    if not image_groups:
        return f"No valid image group found in the {BASE_FOLDER}/seed{annotator.seed}"
    
    current_group_index = int(request.args.get('group', 0))
    current_group_index = min(current_group_index, len(image_groups) - 1)
    
    if current_group_index >= len(image_groups):
        return "All image groups have been checked!"
    
    current_group = image_groups[current_group_index]
    
    # Generate navigation links
    prev_group_url = url_for('handle_request', seed=annotator.seed, mode='view', group=current_group_index - 1) if current_group_index > 0 else None
    next_group_url = url_for('handle_request', seed=annotator.seed, mode='view', group=current_group_index + 1) if current_group_index < len(image_groups) - 1 else None
    
    # Render the template with the current group data and navigation links
    return render_template('viewer.html',
                         alice_images=current_group['alice'],
                         bob_images=current_group['bob'],
                         answers=current_group['answers'],
                         current_group_index=current_group_index,
                         total_groups=len(image_groups),
                         seed=annotator.seed,
                         prev_group_url=prev_group_url,
                         next_group_url=next_group_url)

@app.route('/<int:seed>/<string:mode>', methods=['GET', 'POST'])
def handle_request(seed, mode):
    annotator = GoogleDataAnnotator(BASE_FOLDER, seed)
    if mode == 'label':
        return handle_label(annotator)
    elif mode == 'view':
        return handle_view(annotator)
    elif mode == 'convert':
        return handle_convert(annotator)
    else:
        return "Invalid mode", 404

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Google Data Annotator")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for data directory naming, only used in convert mode")
    parser.add_argument("--mode", choices=['web', 'convert'], help="Mode of operation: website for web interface(it can do label, view, and convert), convert only for converting txt to json")
    args = parser.parse_args()
    if args.mode == 'convert':
        input_file = os.path.join(BASE_FOLDER, f'seed{args.seed}', 'answer_user.txt')
        output_file = os.path.join(BASE_FOLDER, f'seed{args.seed}', 'answer.json')
        annotator = GoogleDataAnnotator(BASE_FOLDER, args.seed)
        annotator.txt_to_json(input_file, output_file)
        print(f"Converted {input_file} to {output_file}")
    else:
        app.run(debug=True)