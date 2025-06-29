from flask import Flask, render_template, request, redirect, url_for, send_from_directory
import os
import json
import re
from typing import List, Tuple, Dict
import argparse

app = Flask(__name__)

TEXTDATA_FOLDER = 'textdata'
GOOGLE_DATA_FOLDER = 'googledata'
ACTION_CHOICES = ['forward', 'turn left', 'turn right', 'turn backward', 'stop']
HEADING_ORDER = ['front', 'right', 'back', 'left']
Bob_HEADING_ORDER_MAPPING = {
    'front': 'back',
    'right': 'left',
    'back': 'front',
    'left': 'right'
}

class GoogleDataAnnotator:
    def __init__(self, textdata_folder, googledata_folder, seed):
        self.textdata_folder = textdata_folder
        self.googledata_folder = googledata_folder
        self.seed = seed
        self.camera_num = len(HEADING_ORDER)
        # set the trajectory folder based on the seed
        self.traj_folder = os.path.join(textdata_folder, f'traj{seed}')
        
        if not os.path.exists(self.traj_folder):
            raise FileNotFoundError(f"Trajectory folder {self.traj_folder} does not exist.")
        
        # Load metainfo
        self.metainfo = self.load_metainfo()

        # set the place folder based on the metainfo
        self.place_id = self.metainfo['place']
        self.place_folder = os.path.join(googledata_folder, f'place{self.place_id}')

    def load_metainfo(self):
        """Load the metainfo.json file"""
        metainfo_path = os.path.join(self.traj_folder, 'metainfo.json')
        if not os.path.exists(metainfo_path):
            raise FileNotFoundError(f"Metainfo file not found: {metainfo_path}")
        
        with open(metainfo_path, 'r', encoding='utf-8') as f:
            metainfo = json.load(f)
        
        # Validate metainfo
        assert 'place' in metainfo, "Place ID is missing in metainfo"
        assert 'rendezvous point' in metainfo, "Rendezvous point pano ID is missing in metainfo"
        assert 'Alice points' in metainfo, "Alice points are missing in metainfo"
        assert 'Bob points' in metainfo, "Bob points are missing in metainfo"
        assert len(metainfo['Alice points']) == len(metainfo['Bob points']), \
            "Alice and Bob points lists must have the same length"
        
        return metainfo

    def sort_by_heading(self, images):
        heading_order = {h: i for i, h in enumerate(HEADING_ORDER)}
        return sorted(images, key=lambda x: heading_order.get(x['heading'], 999))

    def _process_agent_images(self, 
            pano_id: int,
            agent_name: str
        ) -> List[Dict]:
        """Process images for a single agent at a given time (internal helper method)
        
        Args:
            pano_id: Panorama ID to process
            time_idx: Time index for the images
            agent_name: 'Alice' or 'Bob'
        
        Returns:
            List of processed and sorted image entries
        """
        is_bob = agent_name == 'Bob'
        images = []
        
        for view_label in HEADING_ORDER:
            # Create image entry
            actual_view = Bob_HEADING_ORDER_MAPPING[view_label] if is_bob else view_label
            img_path = os.path.join(self.place_folder, f'id_{pano_id}_{actual_view}.jpg')
            
            if os.path.exists(img_path):
                images.append({
                    'heading': view_label,  # Keep original label for display consistency
                    'filename': img_path.replace('\\', '/')
                })
        
        return self.sort_by_heading(images)

    def process_images(self) -> List[Dict]:
        """Load and process the images data based on metainfo
        
        Returns:
            List of processed image groups, each containing Alice's and Bob's images
            for a specific time point
        """
        processed_groups = []
        alice_points = self.metainfo['Alice points']
        bob_points = self.metainfo['Bob points']
        
        # Process regular time points
        for time_idx, (alice_pano, bob_pano) in enumerate(zip(alice_points, bob_points)):
            processed_groups.append({
                'time': time_idx,
                'alice': self._process_agent_images(alice_pano, 'Alice'),
                'bob': self._process_agent_images(bob_pano, 'Bob')
            })
        
        # Process rendezvous point
        rendezvous_pano = self.metainfo['rendezvous point']
        time_idx = len(alice_points)  # Add to the end of the list
        
        processed_groups.append({
            'time': time_idx,
            'alice': self._process_agent_images(rendezvous_pano, 'Alice'),
            'bob': self._process_agent_images(rendezvous_pano, 'Bob')
        })

        return processed_groups

    def load_answers(self) -> Dict:
        """Load answers from the json file"""
        answer_file = os.path.join(self.traj_folder, 'answer.json')
        if os.path.exists(answer_file):
            with open(answer_file, 'r') as f:
                answers = json.load(f)
        else:
            answers = {}
        return answers

    def process_images_and_answers(self) -> List[Dict]:
        """Load and process the images data and answers"""
        image_groups = self.process_images()
        answers = self.load_answers()

        # Merge answers with image groups
        processed_groups = []
        for group in image_groups:
            time_str = str(group['time'])
            group_answers = answers.get(time_str, {
                "Thought": {
                    "Detection": "",
                    "Orientation": {"Alice": "", "Bob": ""},
                    "Conclusion": ""
                },
                "Answer": {"Alice": "", "Bob": ""}
            })
            
            processed_groups.append({
                'time': group['time'],
                'alice': group['alice'],
                'bob': group['bob'],
                'answers': group_answers
            })
        
        return processed_groups

    def parse_line(self, line: str) -> Dict:
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

    def txt_to_json(self,
            input_file: str,
            output_file: str
        ) -> None:
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

@app.route(f'/<path:filename>')
def custom_static(filename):
    """Serve static files from the googledata folder"""
    return send_from_directory('.', filename)

def handle_label(annotator):
    image_groups = annotator.process_images()
    if not image_groups:
        return f"No valid image group"

    current_group_index = int(request.args.get('group', 0))
    
    if request.method == 'POST':
        data = {
            'time': request.form['time'],
            'landmark': request.form['landmark'],
            'alice_direction': request.form['alice_direction'],
            'bob_direction': request.form['bob_direction'],
            'conclusion': request.form['conclusion'],
            'alice_action': request.form['alice_action'],
            'bob_action': request.form['bob_action']
        }

        output_file = os.path.join(annotator.traj_folder, 'answer_user.txt')

        with open(output_file, 'a', encoding='utf-8') as f:
            f.write(f"{data['time']}|")
            f.write(f"{data['landmark']}|")
            f.write(f"Alice:{data['alice_direction']}|")
            f.write(f"Bob:{data['bob_direction']}|")
            f.write(f"{data['conclusion']}|")
            f.write(f"Alice_action:{data['alice_action']}|")
            f.write(f"Bob_action:{data['bob_action']}\n")
        
        if current_group_index + 1 < len(image_groups):
            return redirect(url_for('handle_request', 
                                seed=annotator.seed,
                                mode='label',
                                group=current_group_index + 1))
        else:
            return "All image groups have been annotated!"
    
    current_group_index = min(current_group_index, len(image_groups) - 1)
    current_group = image_groups[current_group_index]
    
    print(current_group_index, len(image_groups))
    route_image = os.path.join(annotator.traj_folder, f'route_{current_group_index}.png').replace('\\', '/')
    return render_template('index.html',
                         alice_images=current_group['alice'],
                         bob_images=current_group['bob'],
                         current_time=current_group['time'],
                         action_choices=ACTION_CHOICES,
                         current_group_index=current_group_index,
                         total_groups=len(image_groups),
                         route_image=route_image)

def handle_convert(annotator):
    """Convert the answer_user.txt to answer.json"""
    input_file = os.path.join(annotator.traj_folder, 'answer_user.txt')
    output_file = os.path.join(annotator.traj_folder, 'answer.json')
    annotator.txt_to_json(input_file, output_file)
    return f"Converted {input_file} to {output_file}"

def handle_view(annotator):
    image_groups = annotator.process_images_and_answers()
    if not image_groups:
        return f"No valid image group found in {annotator.traj_folder}"
    
    current_group_index = int(request.args.get('group', 0))
    current_group_index = min(current_group_index, len(image_groups) - 1)
    
    if current_group_index >= len(image_groups):
        return "All image groups have been checked!"
    
    current_group = image_groups[current_group_index]
    
    prev_group_url = url_for('handle_request', seed=annotator.seed, mode='view', group=current_group_index - 1) if current_group_index > 0 else None
    next_group_url = url_for('handle_request', seed=annotator.seed, mode='view', group=current_group_index + 1) if current_group_index < len(image_groups) - 1 else None
    
    print(current_group_index, len(image_groups))
    route_image = os.path.join(annotator.traj_folder, f'route_{current_group_index}.png').replace('\\', '/')
    return render_template('viewer.html',
                         alice_images=current_group['alice'],
                         bob_images=current_group['bob'],
                         answers=current_group['answers'],
                         current_group_index=current_group_index,
                         total_groups=len(image_groups),
                         seed=annotator.seed,
                         prev_group_url=prev_group_url,
                         next_group_url=next_group_url,
                         route_image=route_image)

@app.route('/<int:seed>/<string:mode>', methods=['GET', 'POST'])
def handle_request(seed, mode):
    annotator = GoogleDataAnnotator(TEXTDATA_FOLDER, GOOGLE_DATA_FOLDER, seed)
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
    parser.add_argument("--seed", type=int, default=0, help="Trajectory seed number")
    parser.add_argument("--mode", choices=['web', 'convert'], help="Mode of operation: web for web interface, convert only for converting txt to json")
    args = parser.parse_args()
    
    if args.mode == 'convert':
        input_file = os.path.join(TEXTDATA_FOLDER, f'traj{args.seed}', 'answer_user.txt')
        output_file = os.path.join(TEXTDATA_FOLDER, f'traj{args.seed}', 'answer.json')
        annotator = GoogleDataAnnotator(TEXTDATA_FOLDER, GOOGLE_DATA_FOLDER, args.seed)
        annotator.txt_to_json(input_file, output_file)
        print(f"Converted {input_file} to {output_file}")
    else:
        app.run(debug=True)