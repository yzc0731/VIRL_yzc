import os
import json
import argparse
import base64
import requests
import time
import re
from io import BytesIO
from PIL import Image
import matplotlib.pyplot as plt
from typing import List, Dict, Any
import copy

# Constants
TEXTDATA_FOLDER = 'textdata'
GOOGLE_DATA_FOLDER = 'googledata'
ACTION_CHOICES = ['forward', 'turn left', 'turn right', 'turn backward', 'stop']
HEADING_ORDER = ['front', 'right', 'back', 'left']
BOB_HEADING_ORDER_MAPPING = {
    'front': 'back',
    'right': 'left',
    'back': 'front',
    'left': 'right'
}

class VLMAnnotator:
    """
    An automated annotator that uses Vision-Language Models to generate 
    annotations for multiagent rendezvous data.
    """
    def __init__(self, textdata_folder, googledata_folder, seed, api_key, model="gpt-4o-mini", overwrite=False, visualize=True):
        """
        Initialize the VLM Annotator.
        
        Args:
            textdata_folder: Path to the folder containing trajectory data
            googledata_folder: Path to the folder containing Google Street View images
            seed: Trajectory seed number
            api_key: API key for the VLM service
            model: VLM model to use for annotation
            overwrite: Whether to overwrite existing annotations
            visualize: Whether to generate visualization images
        """
        self.textdata_folder = textdata_folder
        self.googledata_folder = googledata_folder
        self.seed = seed
        self.api_key = api_key
        self.model = model
        self.overwrite = overwrite
        self.visualize = visualize
        self.camera_num = len(HEADING_ORDER)
        
        # Set the trajectory folder based on the seed
        self.traj_folder = os.path.join(textdata_folder, f'traj{seed}')
        
        if not os.path.exists(self.traj_folder):
            raise FileNotFoundError(f"Trajectory folder {self.traj_folder} does not exist.")
        
        # Load metainfo
        self.metainfo = self.load_metainfo()

        # Set the place folder based on the metainfo
        self.place_id = self.metainfo['place']
        self.place_folder = os.path.join(googledata_folder, f'place{self.place_id}')
        
        # Create output folder for visualization if needed
        self.output_folder = os.path.join(self.traj_folder, 'vlm_annotations')
        os.makedirs(self.output_folder, exist_ok=True)
        
        # Load annotations file if exists
        self.annotations_path = os.path.join(self.place_folder, 'annotations.json')
        if os.path.exists(self.annotations_path):
            with open(self.annotations_path, 'r') as f:
                self.annotations = json.load(f)
        else:
            print(f"Warning: No annotations found at {self.annotations_path}")
            self.annotations = {}

        # Load existing answer.json if it exists
        self.answer_path = os.path.join(self.traj_folder, 'answer.json')
        self.existing_annotations = {}
        if not self.overwrite and os.path.exists(self.answer_path):
            try:
                with open(self.answer_path, 'r', encoding='utf-8') as f:
                    self.existing_annotations = json.load(f)
                print(f"Loaded {len(self.existing_annotations)} existing annotations from {self.answer_path}")
            except Exception as e:
                print(f"Failed to load existing annotations: {e}")

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
        """Sort images by heading order"""
        heading_order = {h: i for i, h in enumerate(HEADING_ORDER)}
        return sorted(images, key=lambda x: heading_order.get(x['heading'], 999))

    def _process_agent_images(self, pano_id: str, agent_name: str) -> List[Dict]:
        """
        Process images for a single agent at a given panorama ID
        
        Args:
            pano_id: Panorama ID to process
            agent_name: 'Alice' or 'Bob'
        
        Returns:
            List of processed and sorted image entries
        """
        is_bob = agent_name == 'Bob'
        images = []
        
        for view_label in HEADING_ORDER:
            # Create image entry
            actual_view = BOB_HEADING_ORDER_MAPPING[view_label] if is_bob else view_label
            img_path = os.path.join(self.place_folder, f'id_{pano_id}_{actual_view}.jpg')
            
            if os.path.exists(img_path):
                images.append({
                    'heading': view_label,  # Keep original label for display consistency
                    'filename': img_path,
                    'pano_id': pano_id,
                    'view': actual_view,
                    'key': f"id_{pano_id}_{actual_view}" # Key for annotations lookup
                })
        
        return self.sort_by_heading(images)

    def process_images(self) -> List[Dict]:
        """
        Load and process images based on metainfo
        
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

    def _encode_image(self, image_path):
        """
        Encode an image to base64 for API requests
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Base64 encoded image string
        """
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _get_bounding_boxes_for_group(self, alice_images, bob_images, time_idx):
        """
        Extract relevant bounding boxes for images in the current group
        
        Args:
            alice_images: List of Alice's image data
            bob_images: List of Bob's image data
            time_idx: Current time index
            
        Returns:
            Dictionary with bounding box data for current images
        """
        bb_data = {}
        
        for agent_name, image_list in [("Alice", alice_images), ("Bob", bob_images)]:
            for idx, image in enumerate(image_list):
                key = image['key']
                if key in self.annotations:
                    bb_key = f"{agent_name}_{time_idx}_{image['heading']}"
                    bb_data[bb_key] = self.annotations[key]
        
        return bb_data

    def _get_route_image_path(self, time_idx):
        """
        Get the path to the route visualization image
        
        Args:
            time_idx: Current time index
            
        Returns:
            Path to the route image if it exists, None otherwise
        """
        route_path = os.path.join(self.traj_folder, f'route_{time_idx}.png')
        return route_path if os.path.exists(route_path) else None

    def create_prompt(self, image_paths, route_image_path, bbox_data, time_idx):
        """
        Create the prompt for the VLM
        
        Args:
            image_paths: List of image paths to include in the prompt
            route_image_path: Path to the route visualization image
            bbox_data: Bounding box data for the current images
            time_idx: Current time index
            
        Returns:
            Formatted prompt for the VLM
        """
        prompt = """
Suppose my friend Bob and I (my name is Alice) are not far apart in the city. Among the 8 input pictures, the first 4 are from my perspective. From left to right, they are front, right, back, and left in sequence. The last 4 pictures are Bob's perspectives and are arranged in the same order. The green dot in the map is my location, while the red one is Bob. The corresponding arrow denotes our front heading.

Please plan a route so that my friend Bob and I can move toward each other and meet up. You should analyze what landmarks are in the scene, which must be seen from the view of both of us. You don't need to know its exact name. Just describe its attributes and estimate our relative positions to it and the orientation of the front camera.

The final answer should be summarized into the following JSON format. The {Action} is chosen from ['forward', 'turn left', 'turn right', 'turn backward', 'stop'].

You will be given JSON format bounding boxes describing the coordinates and corresponding descriptions that can help you complete the rendezvous. You can also consider other landmarks that are helpful for localization and rendezvous. You can refine the description if needed.

Here are the bounding boxes data that might be helpful:
"""
        prompt += json.dumps(bbox_data, indent=2)
        
        prompt += """

Please output a JSON object in the following format:
{
  "Thought": {
    "Rendezvous Type": "{same road, shared cross, or other scene}",
    "Detection": "{All landmarks or scene features that help localization, separated by ';'}",
    "Orientation": {
      "Alice": "In which direction are the landmarks relative to Alice. Each orientation description should be in one sentence.",
      "Bob": "In which direction are the landmarks relative to Bob. Each orientation description should be in one sentence."
    },
    "Conclusion": "A detailed description of spatial relationship and future plan based on detection and orientation. Predict what will happen if they follow the proposed actions."
  },
  "Answer": {
    "Alice": "{Action}",
    "Bob": "{Action}"
  }
}

IMPORTANT: Output ONLY valid JSON with no additional text before or after.
"""
        return prompt

    def call_vlm_api(self, image_paths, prompt):
        """
        Call the OpenAI Vision API with retry logic
        
        Args:
            image_paths: List of image paths to include in the API call
            prompt: Text prompt for the VLM
            
        Returns:
            VLM response
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Prepare the content with images
        content = [{"type": "text", "text": prompt}]
        
        # Add images to the content
        for img_path in image_paths:
            b64_image = self._encode_image(img_path)
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64_image}"
                }
            })
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user", 
                    "content": content
                }
            ],
            "max_tokens": 2000
        }
        
        # Maximum number of retries
        max_retries = 5
        # Initial retry delay in seconds
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                
                # If successful, return the response
                if response.status_code == 200:
                    return response.json()
                
                # If rate limited, extract wait time and retry
                if response.status_code == 429:
                    print(f"Rate limit reached. Attempt {attempt + 1}/{max_retries}")
                    
                    # Try to extract wait time from error message
                    wait_time = retry_delay
                    try:
                        error_msg = response.json().get('error', {}).get('message', '')
                        wait_match = re.search(r'Please try again in (\d+\.?\d*)s', error_msg)
                        if wait_match:
                            wait_time = float(wait_match.group(1)) + 0.5  # Add a small buffer
                    except:
                        pass
                    
                    print(f"Waiting for {wait_time:.2f} seconds before retrying...")
                    time.sleep(wait_time)
                    
                    # Increase retry delay for next attempt (exponential backoff)
                    retry_delay = min(retry_delay * 2, 60)  # Cap at 60 seconds
                    continue
                
                # For other errors, raise exception
                response.raise_for_status()
                
            except Exception as e:
                print(f"API call failed on attempt {attempt + 1}/{max_retries}: {e}")
                if hasattr(response, 'text'):
                    print(f"Response: {response.text}")
                
                # If this is the last attempt, return None
                if attempt == max_retries - 1:
                    return None
                
                # Otherwise wait and retry
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # Cap at 60 seconds
        
        return None

    def parse_vlm_response(self, response):
        """
        Parse the Meta Llama Vision response to extract the JSON annotation
        
        Args:
            response: Response from the VLM API
            
        Returns:
            Parsed JSON annotation, or None if parsing fails
        """
        if not response or 'choices' not in response:
            return None
            
        try:
            # Extract content from response
            content = response['choices'][0]['message']['content']
            
            # Find JSON content (might be wrapped in markdown code blocks)
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                print("No JSON found in response")
                return None
                
            json_content = content[json_start:json_end]
            
            # Parse the JSON
            return json.loads(json_content)
        except Exception as e:
            print(f"Failed to parse VLM response: {e}")
            print(f"Raw content: {content}")
            return None

    def visualize_annotation(self, image_paths, annotation, output_path):
        """
        Create a visualization of the annotation with the images
        
        Args:
            image_paths: List of image paths
            annotation: The annotation data
            output_path: Path to save the visualization
        """
        # Create a figure with subplots for images and annotation
        fig = plt.figure(figsize=(20, 15))
        
        # Add title
        fig.suptitle("Multi-agent Rendezvous Annotation", fontsize=16)
        
        # Plot Alice's images (first row)
        for i in range(4):
            if i < len(image_paths) and i < 4:
                ax = fig.add_subplot(3, 4, i+1)
                img = Image.open(image_paths[i])
                ax.imshow(img)
                ax.set_title(f"Alice - {HEADING_ORDER[i]}")
                ax.axis('off')
        
        # Plot Bob's images (second row)
        for i in range(4):
            if i+4 < len(image_paths) and i < 4:
                ax = fig.add_subplot(3, 4, i+5)
                img = Image.open(image_paths[i+4])
                ax.imshow(img)
                ax.set_title(f"Bob - {HEADING_ORDER[i]}")
                ax.axis('off')
        
        # Add text annotation (third row)
        ax = fig.add_subplot(3, 1, 3)
        annotation_text = (
            f"Rendezvous Type: {annotation['Thought']['Rendezvous Type']}\n\n"
            f"Detection: {annotation['Thought']['Detection']}\n\n"
            f"Alice Orientation: {annotation['Thought']['Orientation']['Alice']}\n\n"
            f"Bob Orientation: {annotation['Thought']['Orientation']['Bob']}\n\n"
            f"Conclusion: {annotation['Thought']['Conclusion']}\n\n"
            f"Actions: Alice - {annotation['Answer']['Alice']}, Bob - {annotation['Answer']['Bob']}"
        )
        ax.text(0.01, 0.99, annotation_text, verticalalignment='top', wrap=True, fontsize=10)
        ax.axis('off')
        
        # Save the figure
        plt.tight_layout(rect=[0, 0, 1, 0.96])  # Adjust for title
        plt.savefig(output_path)
        plt.close()

    def convert_to_answer_format(self, annotations):
        """
        Convert VLM annotations to the format expected by the answer.json file
        
        Args:
            annotations: Dictionary of annotations keyed by time index
            
        Returns:
            Converted annotations in the format for answer.json
        """
        result = {}
        
        for time_idx, annotation in annotations.items():
            result[str(time_idx)] = {
                "Thought": {
                    "Detection": annotation["Thought"]["Detection"],
                    "Orientation": {
                        "Alice": annotation["Thought"]["Orientation"]["Alice"],
                        "Bob": annotation["Thought"]["Orientation"]["Bob"]
                    },
                    "Conclusion": annotation["Thought"]["Conclusion"]
                },
                "Answer": {
                    "Alice": annotation["Answer"]["Alice"],
                    "Bob": annotation["Answer"]["Bob"]
                }
            }
            
        return result

    def run_annotation(self):
        """
        Run the annotation process for all image groups
        
        Returns:
            Dictionary with all annotations
        """
        image_groups = self.process_images()
        annotations = {}
        
        # First load any existing annotations if we're not overwriting
        if not self.overwrite:
            for time_idx_str, annotation in self.existing_annotations.items():
                try:
                    time_idx = int(time_idx_str)
                    # Convert from answer.json format to internal format
                    annotations[time_idx] = {
                        "Thought": {
                            "Rendezvous Type": "same road",  # Default value as it's not stored in answer.json
                            "Detection": annotation["Thought"]["Detection"],
                            "Orientation": annotation["Thought"]["Orientation"],
                            "Conclusion": annotation["Thought"]["Conclusion"]
                        },
                        "Answer": annotation["Answer"]
                    }
                    print(f"Loaded existing annotation for group {time_idx+1}")
                except (ValueError, KeyError) as e:
                    print(f"Error processing existing annotation for index {time_idx_str}: {e}")
        
        for group in image_groups:
            time_idx = group['time']
            
            # Skip if we already have annotation for this time index and not overwriting
            if not self.overwrite and time_idx in annotations:
                print(f"Skipping group {time_idx+1}/{len(image_groups)} (already annotated)")
                
                # If visualization is enabled and we have the annotation but no visualization, create it
                if self.visualize:
                    vis_path = os.path.join(self.output_folder, f'annotation_{time_idx}.png')
                    if not os.path.exists(vis_path):
                        # Get image paths for visualization
                        all_images = group['alice'] + group['bob']
                        image_paths = [img['filename'] for img in all_images]
                        route_image_path = self._get_route_image_path(time_idx)
                        if route_image_path:
                            image_paths.append(route_image_path)
                        
                        # Create visualization for existing annotation
                        self.visualize_annotation(image_paths, annotations[time_idx], vis_path)
                        print(f"Created visualization for existing annotation at {vis_path}")
                
                continue
                
            print(f"Processing group {time_idx+1}/{len(image_groups)}...")
            
            # Get all image paths for this group
            all_images = group['alice'] + group['bob']
            image_paths = [img['filename'] for img in all_images]
            
            # Get route image
            route_image_path = self._get_route_image_path(time_idx)
            if route_image_path:
                image_paths.append(route_image_path)
            
            # Get bounding box data
            bbox_data = self._get_bounding_boxes_for_group(group['alice'], group['bob'], time_idx)
            
            # Create prompt
            prompt = self.create_prompt(image_paths, route_image_path, bbox_data, time_idx)
            
            # Call VLM API
            response = self.call_vlm_api(image_paths, prompt)
            
            # Parse response
            annotation = self.parse_vlm_response(response)
            
            if annotation:
                annotations[time_idx] = annotation
                
                # Visualize annotation if enabled
                if self.visualize:
                    vis_path = os.path.join(self.output_folder, f'annotation_{time_idx}.png')
                    self.visualize_annotation(image_paths, annotation, vis_path)
                    print(f"Saved visualization to {vis_path}")
            else:
                print(f"Failed to get annotation for group {time_idx}")
        
        return annotations

    def save_annotations(self, annotations):
        """
        Save annotations to the answer.json file
        
        Args:
            annotations: Dictionary of annotations
            
        Returns:
            Path to the saved file
        """
        # Convert to required format
        answer_format = self.convert_to_answer_format(annotations)
        
        # Sort the keys numerically to ensure sequential order from 0
        sorted_answer = {}
        for key in sorted(answer_format.keys(), key=lambda x: int(x)):
            sorted_answer[key] = answer_format[key]
        
        # Save to file
        output_path = os.path.join(self.traj_folder, 'answer.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(sorted_answer, f, indent=4, ensure_ascii=False)
            
        print(f"Saved annotations to {output_path}")
        return output_path


def main():
    """Main function to run the VLM Annotator"""
    parser = argparse.ArgumentParser(description="VLM-based Automatic Annotator")
    parser.add_argument("--seed", type=int, default=0, help="Trajectory seed number")
    parser.add_argument("--api_key", type=str, required=True, help="API key for the VLM service")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="VLM model to use")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing annotations")
    parser.add_argument("--no-visualize", action="store_true", help="Skip generating visualization images")
    args = parser.parse_args()
    
    annotator = VLMAnnotator(
        textdata_folder=TEXTDATA_FOLDER,
        googledata_folder=GOOGLE_DATA_FOLDER,
        seed=args.seed,
        api_key=args.api_key,
        model=args.model,
        overwrite=args.overwrite,
        visualize=not args.no_visualize
    )
    
    annotations = annotator.run_annotation()
    annotator.save_annotations(annotations)
    
    print("Annotation process completed.")


if __name__ == "__main__":
    main()