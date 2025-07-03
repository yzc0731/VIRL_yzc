import os
import json
import time
import argparse
import re
import base64
import requests
from PIL import Image
from tqdm import tqdm
import glob
from typing import List, Dict, Tuple, Optional
import io
import matplotlib.pyplot as plt
import datetime
import uuid

# Import direction utils
from direction_utils import (
    apply_augmentation, 
    transform_ground_truth, 
    update_prompt_for_rotated_images
)

def get_default_output_dir(model_name="unknown"):
    """Generate a default output directory based on model name and timestamp"""
    # Create eval directory if it doesn't exist
    eval_dir = "eval"
    os.makedirs(eval_dir, exist_ok=True)
    
    # Generate timestamp
    timestamp = datetime.datetime.now().strftime("%m-%d-%H-%M-%S")
    
    # Create directory name with model name and timestamp
    model_name = model_name.replace("/", "-")  # Replace slashes in model name
    dir_name = f"{model_name}-{timestamp}"
    
    return os.path.join(eval_dir, dir_name)

class VLMEvaluator:
    """VLM evaluation class for calling OpenAI API for visual question answering and evaluating results"""
    def __init__(self, 
                 textdata_folder: str = "textdata", 
                 googledata_folder: str = "googledata", 
                 output_dir: str = None,
                 api_key: str = None, 
                 model: str = "gpt-4o-mini",
                 include_thought: bool = False,
                 use_augmentation: bool = False,
                 image_resize: Optional[Tuple[int, int]] = None,
                 image_quality: int = 85,
                 resume_eval: bool = True,
                 visualize: bool = False,
                 batch_size: int = 10):
        """
        Initialize the VLM evaluator
        
        Args:
            textdata_folder: Folder containing ground truth answers
            googledata_folder: Folder containing images
            output_dir: Folder for output results
            api_key: OpenAI API key
            model: OpenAI model to use
            include_thought: Whether to include Thought in the prompt
            use_augmentation: Whether to use data augmentation
            image_resize: Optional tuple (width, height) to resize images
            image_quality: JPEG quality for image compression (0-100)
            resume_eval: Whether to resume evaluation from previously saved results
            visualize: Whether to generate visualization images
            batch_size: Maximum number of requests to batch together
        """
        self.textdata_folder = textdata_folder
        self.googledata_folder = googledata_folder
        self.output_dir = output_dir if output_dir else get_default_output_dir(model)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.include_thought = include_thought
        self.use_augmentation = use_augmentation
        self.image_resize = image_resize
        self.image_quality = image_quality
        self.resume_eval = resume_eval
        self.visualize = visualize
        self.batch_size = batch_size
        
        if not self.api_key:
            raise ValueError("API key not provided. Please pass it as a parameter or set the OPENAI_API_KEY environment variable")
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
        print(f"Results will be saved to: {self.output_dir}")
        
        # Create a directory for batch files
        self.batch_files_dir = os.path.join(self.output_dir, "batch_files")
        os.makedirs(self.batch_files_dir, exist_ok=True)
        
        # Set prompt template based on whether to include thought
        self._set_prompt_template()
        
        # Define constants for visualization
        self.heading_order = ['front', 'right', 'back', 'left']

        # Create evaluation log file
        self.log_file = os.path.join(self.output_dir, "evaluation_log.txt")
        self._log_evaluation_start()

    def _log_evaluation_start(self):
        """Log the start of an evaluation session"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"Evaluation started at: {timestamp}\n")
            f.write(f"Model: {self.model}\n")
            f.write(f"Include thought: {self.include_thought}\n")
            f.write(f"Use augmentation: {self.use_augmentation}\n")
            f.write(f"Batch size: {self.batch_size}\n")
            f.write(f"{'='*50}\n\n")

    def _set_prompt_template(self):
        """Set the prompt template based on whether to include thought"""
        if self.include_thought:
            self.prompt_template = """
You are an intelligent AI assistant. Please analyze the following two street view images. These images represent the perspectives of two people (Alice and Bob) who are trying to meet in a city.

1. First, describe in detail the main features and landmarks you see in the images.
2. Then, analyze the relative positions of Alice and Bob.
3. Finally, recommend their next actions to help them meet.

Please answer in JSON format as follows:
{
    "Thought": {
        "Detection": "Description of main features and landmarks seen in the images",
        "Orientation": {
            "Alice": "Description of Alice's position",
            "Bob": "Description of Bob's position"
        },
        "Conclusion": "Analysis of their spatial relationship and recommended action plan"
    },
    "Answer": {
        "Alice": "Recommended next action for Alice (only use one of these exact words: forward, turn left, turn right, turn backward, stop)",
        "Bob": "Recommended next action for Bob (only use one of these exact words: forward, turn left, turn right, turn backward, stop)"
    }
}
            """
        else:
            self.prompt_template = """
You are an intelligent AI assistant. Please analyze the following two street view images. These images represent the perspectives of two people (Alice and Bob) who are trying to meet in a city.

Look at the images and provide directions for Alice and Bob to help them meet each other as efficiently as possible.

Please answer in JSON format as follows:
{
    "Answer": {
        "Alice": "Recommended next action for Alice (only use one of these exact words: forward, turn left, turn right, turn backward, stay)",
        "Bob": "Recommended next action for Bob (only use one of these exact words: forward, turn left, turn right, turn backward, stay)"
    }
}

Do not include any explanations or reasoning in your response, just the JSON with the recommended actions.
            """
    
    def _process_image(self, image_path: str) -> bytes:
        """Process image to reduce size by resizing and compression"""
        try:
            with Image.open(image_path) as img:
                if self.image_resize:
                    img = img.resize(self.image_resize, Image.LANCZOS)
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=self.image_quality, optimize=True)
                return buffer.getvalue()
        except Exception as e:
            print(f"Error processing image {image_path}: {e}")
            with open(image_path, "rb") as f:
                return f.read()

    def _encode_image(self, image_path: str) -> str:
        """Encode image as base64 string with optional processing"""
        image_data = self._process_image(image_path)
        return base64.b64encode(image_data).decode('utf-8')
    
    def _get_image_paths(self, traj: str, pair_id: str) -> Tuple[List[str], List[str]]:
        """
        Get image paths for specified trajectory and pair ID
        
        Args:
            traj: Trajectory ID
            pair_id: Pair ID within the trajectory
            
        Returns:
            Tuple of (Alice's images, Bob's images)
        """
        # Handle numeric trajectory names by adding 'traj' prefix if needed
        traj_folder = f"traj{traj}" if traj.isdigit() else traj
        
        # Load the metainfo.json file
        metainfo_path = os.path.join(self.textdata_folder, traj_folder, 'metainfo.json')
        
        if not os.path.exists(metainfo_path):
            raise FileNotFoundError(f"Could not find metainfo file for trajectory {traj}")
            
        with open(metainfo_path, 'r', encoding='utf-8') as f:
            metainfo = json.load(f)
            
        # Get the place ID from metainfo
        place_id = metainfo['place']
        place_folder = os.path.join(self.googledata_folder, f'place{place_id}')
        
        # Get the appropriate pano IDs based on pair_id
        pair_idx = int(pair_id)
        
        # Check if this is a rendezvous point (when pair_id equals the length of points array)
        is_rendezvous = False
        if pair_idx >= len(metainfo['Alice points']):
            # This is a rendezvous point
            if 'rendezvous point' in metainfo:
                is_rendezvous = True
                alice_pano_id = metainfo['rendezvous point']
                bob_pano_id = metainfo['rendezvous point']
            else:
                raise ValueError(f"Invalid pair ID {pair_id} for trajectory {traj} - no rendezvous point defined")
        else:
            # Normal point
            alice_pano_id = metainfo['Alice points'][pair_idx]
            bob_pano_id = metainfo['Bob points'][pair_idx]
        
        # Bob's perspective is flipped
        bob_heading_mapping = {
            'front': 'back',
            'right': 'left',
            'back': 'front',
            'left': 'right'
        }
        
        # Get Alice images
        alice_images = []
        for heading in self.heading_order:
            img_path = os.path.join(place_folder, f'id_{alice_pano_id}_{heading}.jpg')
            if os.path.exists(img_path):
                alice_images.append(img_path)
        
        # Get Bob images
        bob_images = []
        for heading in self.heading_order:
            # Use the flipped heading for Bob's perspective
            actual_heading = bob_heading_mapping[heading]
            img_path = os.path.join(place_folder, f'id_{bob_pano_id}_{actual_heading}.jpg')
            if os.path.exists(img_path):
                bob_images.append(img_path)
        
        if not alice_images or not bob_images:
            raise FileNotFoundError(f"Could not find images for trajectory {traj} with pair ID {pair_id}")
        
        return alice_images, bob_images

    def _load_ground_truth(self, traj: str) -> Dict:
        """
        Load ground truth answers from answer.json
        
        Args:
            traj: Trajectory ID
            
        Returns:
            Dictionary with ground truth data
        """
        traj_folder = f"traj{traj}" if traj.isdigit() else traj
        
        answer_path = os.path.join(self.textdata_folder, traj_folder, 'answer.json')
        if not os.path.exists(answer_path):
            raise FileNotFoundError(f"Could not find ground truth answer file for trajectory {traj} at {answer_path}")
        
        with open(answer_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def parse_vlm_response(self, response):
        """
        Parse the response from the VLM API to extract the model's prediction
        
        Args:
            response: Response from the VLM API
            
        Returns:
            Parsed answer or None if parsing fails
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
                print(f"Raw content: {content}")
                return None
                
            json_content = content[json_start:json_end]
            
            # Parse the JSON
            result = json.loads(json_content)
            
            # Ensure the required fields are present
            if "Answer" not in result:
                print("Missing 'Answer' field in response")
                print(f"Parsed content: {result}")
                return None
                
            if "Alice" not in result["Answer"] or "Bob" not in result["Answer"]:
                print("Missing 'Alice' or 'Bob' in Answer field")
                print(f"Parsed content: {result}")
                return None
            
            # If the result doesn't have Thought field but include_thought is True, add empty thought
            if self.include_thought and "Thought" not in result:
                result["Thought"] = {
                    "Detection": "",
                    "Orientation": {"Alice": "", "Bob": ""},
                    "Conclusion": ""
                }
            
            return result
        except Exception as e:
            print(f"Failed to parse VLM response: {e}")
            print(f"Raw content: {response.get('choices', [{}])[0].get('message', {}).get('content', 'No content')}")
            return None

    def visualize_evaluation(self, traj: str, pair_id: str, alice_images: List[str], bob_images: List[str], 
                             pred_answer: Dict, gt_answer: Dict, is_correct: bool) -> str:
        """
        Create a visualization image of the evaluation results
        
        Args:
            traj: Trajectory ID
            pair_id: Pair ID within the trajectory
            alice_images: List of Alice's image paths
            bob_images: List of Bob's image paths
            pred_answer: Model's prediction
            gt_answer: Ground truth answer
            is_correct: Whether the prediction is correct
            
        Returns:
            Path to the saved visualization image
        """
        # Create output directory
        traj_folder = f"traj{traj}" if traj.isdigit() else traj
        vis_dir = os.path.join(self.output_dir, traj_folder, "visualizations")
        os.makedirs(vis_dir, exist_ok=True)
        
        # Create figure
        fig = plt.figure(figsize=(20, 10))
        fig.suptitle(f"Trajectory {traj}, Pair {pair_id} - {'CORRECT' if is_correct else 'WRONG'}", fontsize=16)
        
        # Prepare grid for images
        gs = fig.add_gridspec(2, 5, height_ratios=[3, 1])
        
        # Add Alice's images
        for i, img_path in enumerate(alice_images[:4]):  # Only show first 4 images
            ax = fig.add_subplot(gs[0, i])
            img = plt.imread(img_path)
            ax.imshow(img)
            ax.set_title(f"Alice - {self.heading_order[i]}")
            ax.axis('off')
        
        # Add Bob's images
        for i, img_path in enumerate(bob_images[:4]):  # Only show first 4 images
            ax = fig.add_subplot(gs[1, i])
            img = plt.imread(img_path)
            ax.imshow(img)
            ax.set_title(f"Bob - {self.heading_order[i]}")
            ax.axis('off')
        
        # Add text with predictions and ground truth
        ax_text = fig.add_subplot(gs[:, 4])
        ax_text.axis('off')
        
        text = (
            f"PREDICTION:\n"
            f"Alice: {pred_answer['Answer']['Alice']}\n"
            f"Bob: {pred_answer['Answer']['Bob']}\n\n"
            f"GROUND TRUTH:\n"
            f"Alice: {gt_answer['Answer']['Alice']}\n"
            f"Bob: {gt_answer['Answer']['Bob']}\n"
        )
        
        # Add augmentation info if available
        if "_augmentation" in pred_answer:
            text += (
                f"\nAUGMENTATION:\n"
                f"Alice rotation: {pred_answer['_augmentation']['alice_rotation']}\n"
                f"Bob rotation: {pred_answer['_augmentation']['bob_rotation']}\n"
            )
        
        # Add thought if available
        if "Thought" in pred_answer:
            thought_text = "\nTHOUGHT:\n"
            if isinstance(pred_answer["Thought"], dict):
                if "Detection" in pred_answer["Thought"]:
                    thought_text += f"Detection: {pred_answer['Thought']['Detection'][:200]}...\n"
                if "Orientation" in pred_answer["Thought"]:
                    if isinstance(pred_answer["Thought"]["Orientation"], dict):
                        thought_text += f"Orientation - Alice: {pred_answer['Thought']['Orientation'].get('Alice', '')[:100]}...\n"
                        thought_text += f"Orientation - Bob: {pred_answer['Thought']['Orientation'].get('Bob', '')[:100]}...\n"
                    else:
                        thought_text += f"Orientation: {str(pred_answer['Thought']['Orientation'])[:200]}...\n"
                if "Conclusion" in pred_answer["Thought"]:
                    thought_text += f"Conclusion: {pred_answer['Thought']['Conclusion'][:200]}...\n"
            else:
                thought_text += str(pred_answer["Thought"])[:500] + "...\n"
            
            text += thought_text
        
        ax_text.text(0, 0.95, text, fontsize=10, verticalalignment='top', wrap=True)
        
        # Save figure
        output_path = os.path.join(vis_dir, f"eval_{pair_id}.png")
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        
        return output_path

    def _create_batch_jsonl(self, batch_items):
        """
        Create a JSONL file for OpenAI's Batch API containing all batch requests
        
        Args:
            batch_items: List of dictionaries with traj, pair_id, and image_paths keys
        
        Returns:
            Tuple of (file_path, custom_id_mapping)
        """
        # Create a unique ID for this batch
        batch_id = str(uuid.uuid4())
        batch_dir = os.path.join(self.batch_files_dir, batch_id)
        os.makedirs(batch_dir, exist_ok=True)
        
        # Create a JSONL file for the batch
        batch_file_path = os.path.join(batch_dir, "batch_requests.jsonl")
        
        # Create a mapping from custom_id to traj and pair_id
        custom_id_mapping = {}
        
        with open(batch_file_path, 'w', encoding='utf-8') as f:
            for item in batch_items:
                traj = item['traj']
                pair_id = item['pair_id']
                image_paths = item['image_paths']
                
                # Generate a unique ID for this request
                custom_id = f"{traj}_{pair_id}_{uuid.uuid4()}"
                custom_id_mapping[custom_id] = {"traj": traj, "pair_id": pair_id}
                
                # Prepare prompt template
                prompt_template = self.prompt_template
                
                # If augmentation is used, adjust direction descriptions in the prompt
                if self.use_augmentation and ('alice_rotation' in item or 'bob_rotation' in item):
                    alice_rotation = item.get('alice_rotation', 0)
                    bob_rotation = item.get('bob_rotation', 0)
                    prompt_template = update_prompt_for_rotated_images(
                        prompt_template, 
                        alice_rotation,
                        bob_rotation
                    )
                
                # Prepare content with images
                content = [{"type": "text", "text": prompt_template}]
                
                # Add images to content
                for img_path in image_paths:
                    b64_image = self._encode_image(img_path)
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}"
                        }
                    })
                
                # Create batch request
                batch_request = {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.model,
                        "messages": [
                            {
                                "role": "user", 
                                "content": content
                            }
                        ],
                        "max_tokens": 2000
                    }
                }
                
                # Write to JSONL file
                f.write(json.dumps(batch_request) + '\n')
        
        return batch_file_path, custom_id_mapping # Add id_mapping_path to return

    def _upload_batch_file(self, file_path):
        """Upload a JSONL file to OpenAI's Batch API and return the file ID"""
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        with open(file_path, 'rb') as f:
            files = {
                'file': f
            }
            
            response = requests.post(
                "https://api.openai.com/v1/files",
                headers=headers,
                files=files,
                data={"purpose": "batch"}
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to upload batch file: {response.text}")
                
            file_id = response.json()['id']
            return file_id
    
    def _create_batch(self, file_id):
        """Create a batch job with the uploaded file and return the batch ID"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "input_file_id": file_id,
            "completion_window": "24h",
            "endpoint": "/v1/chat/completions"
        }
        
        response = requests.post(
            "https://api.openai.com/v1/batches",
            headers=headers,
            json=payload
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to create batch: {response.text}")
            
        batch_id = response.json()['id']
        return batch_id
    
    def _check_batch_status(self, batch_id):
        """Check the status of a batch job and return the status information"""
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        response = requests.get(
            f"https://api.openai.com/v1/batches/{batch_id}",
            headers=headers
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to check batch status: {response.text}")
            
        return response.json()
    
    def _download_batch_results(self, file_id):
        """Download batch results and return the path to the downloaded file"""
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        response = requests.get(
            f"https://api.openai.com/v1/files/{file_id}/content",
            headers=headers
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to download batch results: {response.text}")
            
        # Save to a file
        results_file = os.path.join(self.batch_files_dir, f"results_{file_id}.jsonl")
        with open(results_file, 'wb') as f:
            f.write(response.content)
            
        return results_file
    
    def _download_batch_errors(self, file_id):
        """Download batch errors and return the path to the downloaded file"""
        if not file_id:
            return None
            
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        response = requests.get(
            f"https://api.openai.com/v1/files/{file_id}/content",
            headers=headers
        )
        
        if response.status_code != 200:
            print(f"Warning: Failed to download batch errors: {response.text}")
            return None
            
        # Save to a file
        errors_file = os.path.join(self.batch_files_dir, f"errors_{file_id}.jsonl")
        with open(errors_file, 'wb') as f:
            f.write(response.content)
            
        return errors_file
    
    
    def _process_batch_results(self, results_path, errors_path, id_mapping):
        """Process batch results and return processed results"""
        results = {}
        
        # Process successful results
        with open(results_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    result_json = json.loads(line)
                    custom_id = result_json.get('custom_id')
                    
                    if custom_id not in id_mapping:
                        print(f"Warning: Unknown custom_id in batch results: {custom_id}")
                        continue
                        
                    traj = id_mapping[custom_id]['traj']
                    pair_id = id_mapping[custom_id]['pair_id']
                    
                    # Handle the nested structure from batch API
                    if 'response' in result_json and 'body' in result_json['response']:
                        # Extract the actual response body from the batch API format
                        response_body = result_json['response']['body']
                        # Parse the response content
                        parsed_result = self.parse_vlm_response(response_body)
                    else:
                        # Try parsing as a regular response (for backwards compatibility)
                        parsed_result = self.parse_vlm_response(result_json)
                    
                    if traj not in results:
                        results[traj] = {}
                    
                    results[traj][pair_id] = parsed_result
                except Exception as e:
                    print(f"Error processing batch result: {e}")
                    print(f"Raw JSON line: {line[:100]}...")
                    
        # Add this return statement
        return results  # Missing return statement in your original code

    def process_batch(self, batch_items):
        """
        Process a batch of items using OpenAI's Batch API
        
        Args:
            batch_items: List of dictionaries with traj, pair_id, and image_paths keys
        
        Returns:
            Dictionary with trajectory and pair results
        """
        if not batch_items:
            return {}
        
        try:
            # Step 1: Create JSONL file for batch processing
            batch_file_path, custom_id_mapping = self._create_batch_jsonl(batch_items)
            print(f"Created batch JSONL file with {len(batch_items)} items")
            
            # Step 2: Upload batch file
            file_id = self._upload_batch_file(batch_file_path)
            print(f"Uploaded batch file with ID: {file_id}")
            
            # Step 3: Create batch
            batch_id = self._create_batch(file_id)
            print(f"Created batch job with ID: {batch_id}")
            
            # Step 4: Wait for batch to complete
            print("Waiting for batch to complete...")
            while True:
                batch_status = self._check_batch_status(batch_id)
                status = batch_status.get('status', '')
                
                total_requests = batch_status.get('request_counts', {}).get('total', 0)
                completed_requests = batch_status.get('request_counts', {}).get('completed', 0)
                failed_requests = batch_status.get('request_counts', {}).get('failed', 0)
                
                print(f"Batch status: {status} - Completed: {completed_requests}/{total_requests}, Failed: {failed_requests}")
                
                if status in ['completed', 'failed', 'expired', 'cancelled']:
                    break
                
                # Wait before checking again
                time.sleep(30)
            
            # Even if the batch failed, try to get any available results
            output_file_id = batch_status.get('output_file_id')
            if output_file_id:
                # Step 5: Download batch results
                output_file_path = self._download_batch_results(output_file_id)
                
                # Download errors if available
                error_file_id = batch_status.get('error_file_id')
                error_file_path = self._download_batch_errors(error_file_id) if error_file_id else None
                
                # Step 6: Process batch results
                results = self._process_batch_results(output_file_path, error_file_path, custom_id_mapping)
                
                return results
            else:
                raise Exception(f"No output file available for batch with status: {batch_status.get('status')}")
            
        except Exception as e:
            print(f"Error processing batch: {e}")
            print("Returning empty results due to batch processing error.")
            return {}

    def collect_all_evaluation_pairs(self, traj_ids=None):
        """
        Collect all pairs from all trajectories that need to be evaluated
        
        Args:
            traj_ids: Optional list of trajectory IDs to evaluate. If None, all trajectories will be collected.
            
        Returns:
            List of dictionaries with traj, pair_id, and image_paths keys
        """
        # Find all trajectory folders if not specified
        if traj_ids is None:
            traj_pattern = os.path.join(self.textdata_folder, "traj*")
            traj_folders = glob.glob(traj_pattern)
            
            traj_ids = []
            for folder in traj_folders:
                folder_name = os.path.basename(folder)
                # Handle both "traj123" and other formats
                if folder_name.startswith("traj") and folder_name[4:].isdigit():
                    traj_ids.append(folder_name[4:])  # Extract numeric part
                else:
                    traj_ids.append(folder_name)
        
        # Create overall results file path
        overall_results_file = os.path.join(self.output_dir, "overall_results.json")
        
        # Check if overall results already exist and which trajectories are already completed
        completed_trajs = set()
        if self.resume_eval and os.path.exists(overall_results_file):
            try:
                with open(overall_results_file, 'r', encoding='utf-8') as f:
                    existing_results = json.load(f)
                
                # Check which trajectories are already completed
                if "trajectory_metrics" in existing_results:
                    for traj, metrics in existing_results["trajectory_metrics"].items():
                        # Extract trajectory ID without 'traj' prefix if present
                        traj_id = traj[4:] if traj.startswith("traj") else traj
                        completed_trajs.add(traj_id)
            except Exception as e:
                print(f"Error loading existing overall results: {e}")
        
        # Collect all pairs that need evaluation
        batch_items = []
        
        for traj in tqdm(traj_ids, desc="Collecting evaluation pairs"):
            # Skip completed trajectories if resume is enabled
            if self.resume_eval and traj in completed_trajs:
                print(f"Skipping trajectory {traj} as it's already completed")
                continue
                
            # Check if this trajectory has results file
            traj_folder = f"traj{traj}" if traj.isdigit() else traj
            traj_results_file = os.path.join(self.output_dir, traj_folder, "trajectory_results.json")
            
            completed_pairs = set()
            if self.resume_eval and os.path.exists(traj_results_file):
                try:
                    with open(traj_results_file, 'r', encoding='utf-8') as f:
                        traj_results = json.load(f)
                    
                    # Check if pairs are already completed
                    if "pairs" in traj_results:
                        for pair_id, result in traj_results["pairs"].items():
                            if result is not None:  # Only count as completed if result exists
                                completed_pairs.add(pair_id)
                except Exception as e:
                    print(f"Error loading existing trajectory results for {traj}: {e}")
            
            # Load ground truth to get all pair IDs
            try:
                gt_data = self._load_ground_truth(traj)
            except FileNotFoundError:
                print(f"Skipping trajectory {traj} - no ground truth file found")
                continue
                
            # For each pair, check if it needs evaluation
            for pair_id in gt_data.keys():
                # Skip completed pairs if resume is enabled
                if self.resume_eval and pair_id in completed_pairs:
                    continue
                    
                try:
                    # Get image paths
                    alice_images, bob_images = self._get_image_paths(traj, pair_id)
                    
                    # Reset rotation angles
                    alice_rotation = 0
                    bob_rotation = 0
                    
                    # Prepare images
                    image_paths = alice_images + bob_images
                    
                    # Apply data augmentation (if enabled)
                    if self.use_augmentation:
                        image_paths, alice_rotation, bob_rotation = apply_augmentation(image_paths)
                    
                    # Add to batch items
                    batch_item = {
                        "traj": traj,
                        "pair_id": pair_id,
                        "image_paths": image_paths
                    }
                    
                    # Store augmentation parameters if used
                    if self.use_augmentation:
                        batch_item["alice_rotation"] = alice_rotation
                        batch_item["bob_rotation"] = bob_rotation
                    
                    batch_items.append(batch_item)
                except Exception as e:
                    print(f"Error preparing pair {pair_id} for trajectory {traj}: {e}")
        
        print(f"Collected {len(batch_items)} pairs for evaluation")
        return batch_items
    
    def evaluate_all_trajectories(self) -> Dict:
        """
        Evaluate all trajectories in the textdata folder
        
        Returns:
            Dictionary with results for all trajectories
        """
        # Find all trajectory folders
        traj_pattern = os.path.join(self.textdata_folder, "traj*")
        traj_folders = glob.glob(traj_pattern)
        
        if not traj_folders:
            print(f"No trajectory folders found in {self.textdata_folder}")
            return {"trajectories": {}, "overall_metrics": {"total": 0, "correct": 0, "accuracy": 0.0}}
        
        # Extract trajectory IDs
        traj_ids = []
        for folder in traj_folders:
            folder_name = os.path.basename(folder)
            # Handle both "traj123" and other formats
            if folder_name.startswith("traj") and folder_name[4:].isdigit():
                traj_ids.append(folder_name[4:])  # Extract numeric part
            else:
                traj_ids.append(folder_name)
        
        print(f"Found {len(traj_ids)} trajectories to evaluate")
        
        # Results file for all trajectories
        all_results_file = os.path.join(self.output_dir, "all_results.json")
        
        # Check if all results already exist
        if self.resume_eval and os.path.exists(all_results_file):
            try:
                with open(all_results_file, 'r', encoding='utf-8') as f:
                    all_results = json.load(f)
                    
                # Check if all trajectories are completed
                all_completed = True
                for traj_id in traj_ids:
                    if traj_id not in all_results["trajectories"] or not all_results["trajectories"][traj_id].get("completed", False):
                        all_completed = False
                        break
                        
                if all_completed:
                    print("All trajectories already evaluated, loading results")
                    return all_results
                    
                print("Resuming evaluation from existing results")
            except Exception as e:
                print(f"Error loading existing all results: {e}")
                all_results = {"trajectories": {}}
        else:
            all_results = {"trajectories": {}}
        
        # Evaluate each trajectory
        total_correct = 0
        total_pairs = 0
        
        for traj_id in tqdm(traj_ids, desc="Evaluating trajectories"):
            # Check if this trajectory is already completed
            if traj_id in all_results["trajectories"] and all_results["trajectories"][traj_id].get("completed", False):
                print(f"Trajectory {traj_id} already evaluated, skipping")
                # Add to totals
                metrics = all_results["trajectories"][traj_id]["metrics"]
                total_correct += metrics["correct"]
                total_pairs += metrics["total"]
                continue
                
            # Evaluate the trajectory
            traj_result = self.evaluate_trajectory(traj_id)
            
            # Add to all results
            all_results["trajectories"][traj_id] = traj_result
            
            # Add to totals
            total_correct += traj_result["metrics"]["correct"]
            total_pairs += traj_result["metrics"]["total"]
            
            # Save after each trajectory
            all_results["overall_metrics"] = {
                "total": total_pairs,
                "correct": total_correct,
                "accuracy": total_correct / total_pairs if total_pairs > 0 else 0.0
            }
            
            with open(all_results_file, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, indent=2, ensure_ascii=False)
                
            print(f"Trajectory {traj_id} accuracy: {traj_result['metrics']['accuracy']:.4f} ({traj_result['metrics']['correct']}/{traj_result['metrics']['total']})")
            print(f"Overall accuracy so far: {all_results['overall_metrics']['accuracy']:.4f} ({all_results['overall_metrics']['correct']}/{all_results['overall_metrics']['total']})")
        
        # Final save
        with open(all_results_file, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
            
        print(f"Overall evaluation completed with accuracy: {all_results['overall_metrics']['accuracy']:.4f} ({all_results['overall_metrics']['correct']}/{all_results['overall_metrics']['total']})")
        
        return all_results

    def evaluate_and_save_results(self, batch_results, visualize=False):
        """
        Evaluate batch results against ground truth and save to files
        
        Args:
            batch_results: Dictionary with trajectory and pair results
            visualize: Whether to generate visualization images
            
        Returns:
            Dictionary with overall evaluation metrics
        """
        # Initialize overall metrics
        overall_metrics = {
            "correct": 0,
            "total": 0,
            "accuracy": 0.0
        }
        
        # Initialize trajectory metrics
        trajectory_metrics = {}
        
        # Process each trajectory's results
        for traj, pairs in batch_results.items():
            # Create trajectory output directory
            traj_folder = f"traj{traj}" if traj.isdigit() else traj
            traj_output_dir = os.path.join(self.output_dir, traj_folder)
            os.makedirs(traj_output_dir, exist_ok=True)
            
            # Load ground truth
            try:
                gt_data = self._load_ground_truth(traj)
            except FileNotFoundError:
                print(f"Skipping trajectory {traj} - no ground truth file found")
                continue
            
            # Evaluate each pair
            traj_correct = 0
            traj_total = 0
            
            for pair_id, result in pairs.items():
                if result and pair_id in gt_data:
                    gt_answer = gt_data[pair_id]
                    
                    # If data augmentation was used, transform ground truth
                    if self.use_augmentation and "_augmentation" in result:
                        aug_info = result["_augmentation"]
                        alice_rotation = aug_info.get("alice_rotation", 0)
                        bob_rotation = aug_info.get("bob_rotation", 0)
                        
                        gt_answer = transform_ground_truth(gt_data[pair_id], alice_rotation, bob_rotation)
                    
                    # Check if prediction is correct
                    alice_correct = result["Answer"]["Alice"].lower() == gt_answer["Answer"]["Alice"].lower()
                    bob_correct = result["Answer"]["Bob"].lower() == gt_answer["Answer"]["Bob"].lower()
                    
                    is_correct = alice_correct and bob_correct
                    if is_correct:
                        traj_correct += 1
                    
                    traj_total += 1
                    
                    # Generate visualization if enabled
                    if visualize:
                        try:
                            alice_images, bob_images = self._get_image_paths(traj, pair_id)
                            self.visualize_evaluation(
                                traj, pair_id, alice_images, bob_images, 
                                result, gt_answer, is_correct
                            )
                        except Exception as e:
                            print(f"Error creating visualization for pair {pair_id}: {e}")
            
            # Save trajectory results
            traj_metrics = {
                "correct": traj_correct,
                "total": traj_total,
                "accuracy": traj_correct / traj_total if traj_total > 0 else 0.0
            }
            
            trajectory_metrics[f"traj{traj}"] = traj_metrics
            
            # Update overall metrics
            overall_metrics["correct"] += traj_correct
            overall_metrics["total"] += traj_total
            
            # Save trajectory results
            traj_result = {
                "traj_id": traj,
                "pairs": pairs,
                "metrics": traj_metrics
            }
            
            with open(os.path.join(traj_output_dir, "trajectory_results.json"), 'w', encoding='utf-8') as f:
                json.dump(traj_result, f, indent=2, ensure_ascii=False)
        
        # Calculate overall accuracy
        if overall_metrics["total"] > 0:
            overall_metrics["accuracy"] = overall_metrics["correct"] / overall_metrics["total"]
        
        # Save overall results
        overall_results = {
            "overall_metrics": overall_metrics,
            "trajectory_metrics": trajectory_metrics
        }
        
        with open(os.path.join(self.output_dir, "overall_results.json"), 'w', encoding='utf-8') as f:
            json.dump(overall_results, f, indent=2, ensure_ascii=False)
        
        # Log completion
        with open(self.log_file, 'a', encoding='utf-8') as f:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"Evaluation completed at: {timestamp}\n")
            f.write(f"Overall accuracy: {overall_metrics['accuracy']:.4f} ({overall_metrics['correct']}/{overall_metrics['total']})\n")
            f.write(f"Trajectories evaluated: {len(trajectory_metrics)}\n\n")
        
        return overall_results

    def evaluate(self, traj_ids=None):
        """
        Main evaluation function
        
        Args:
            traj_ids: Optional list of trajectory IDs to evaluate. If None, all trajectories will be evaluated.
            
        Returns:
            Dictionary with evaluation results
        """
        # Step 1: Collect all pairs that need evaluation
        batch_items = self.collect_all_evaluation_pairs(traj_ids)
        
        if not batch_items:
            print("No items to evaluate")
            return None
        
        # Step 2: Process items in batches
        all_results = {}
        for i in range(0, len(batch_items), self.batch_size):
            batch = batch_items[i:i + self.batch_size]
            print(f"Processing batch {i//self.batch_size + 1}/{(len(batch_items) + self.batch_size - 1)//self.batch_size}")
            
            # Process batch
            batch_results = self.process_batch(batch)
            
            # Merge results
            for traj, pairs in batch_results.items():
                if traj not in all_results:
                    all_results[traj] = {}
                
                all_results[traj].update(pairs)
        
        # Step 3: Evaluate and save results
        evaluation_results = self.evaluate_and_save_results(all_results, self.visualize)
        
        return evaluation_results
    

    def process_existing_batch_file(self, batch_file_path, id_mapping_path):
        """
        Process an existing batch results file without making new API calls
        
        Args:
            batch_file_path: Path to the existing batch results file
            id_mapping_path: Path to the corresponding ID mapping file
            
        Returns:
            Dictionary with processed results
        """
        try:
            # Load ID mapping
            with open(id_mapping_path, 'r', encoding='utf-8') as f:
                id_mapping = json.load(f)
            
            # Process the batch file
            results = self._process_batch_results(batch_file_path, None, id_mapping)
            
            return results
        except Exception as e:
            print(f"Error processing existing batch file: {e}")
            return {}

def main():
    parser = argparse.ArgumentParser(description='VLM Evaluation Tool')
    parser.add_argument('--textdata_folder', type=str, default="textdata", help='Folder containing ground truth answers')
    parser.add_argument('--googledata_folder', type=str, default="googledata", help='Folder containing images')
    parser.add_argument('--output_dir', type=str, default=None, help='Folder for output results (default: "eval_results")')
    parser.add_argument('--api_key', type=str, default=None, help='OpenAI API key')
    parser.add_argument('--model', type=str, default="gpt-4o-mini", help='OpenAI model to use')
    parser.add_argument('--traj', type=str, default=None, help='Specific trajectory to evaluate')
    parser.add_argument('--pair_id', type=str, default=None, help='Specific pair ID to evaluate (must be used with --traj)')
    parser.add_argument('--include_thought', action='store_true', help='Include Thought in the output')
    parser.add_argument('--use_augmentation', action='store_true', help='Use data augmentation for evaluation')
    parser.add_argument('--image_width', type=int, default=None, help='Width to resize images (default: original size)')
    parser.add_argument('--image_height', type=int, default=None, help='Height to resize images (default: original size)')
    parser.add_argument('--image_quality', type=int, default=85, help='JPEG quality for image compression (0-100)')
    parser.add_argument('--no_resume', action='store_true', help='Disable resuming from previous evaluation results')
    parser.add_argument('--visualize', action='store_true', help='Generate visualization images for evaluation results')
    parser.add_argument('--batch_size', type=int, default=500, help='Number of requests to batch together')
    parser.add_argument('--process_batch_file', type=str, default=None, help='Process an existing batch results file without making new API calls')
    parser.add_argument('--id_mapping_file', type=str, default=None, help='Path to the ID mapping file for the batch results')
    
    
    args = parser.parse_args()
    
    # Configure image resize settings
    image_resize = None
    if args.image_width and args.image_height:
        image_resize = (args.image_width, args.image_height)
    
    evaluator = VLMEvaluator(
        textdata_folder=args.textdata_folder,
        googledata_folder=args.googledata_folder,
        output_dir=args.output_dir,
        api_key=args.api_key,
        model=args.model,
        include_thought=args.include_thought,
        use_augmentation=args.use_augmentation,
        image_resize=image_resize,
        image_quality=args.image_quality,
        resume_eval=not args.no_resume,
        visualize=args.visualize,
        batch_size=args.batch_size
    )
    
    # Determine which trajectories to evaluate
    traj_ids = None
    if args.process_batch_file:
        if not args.id_mapping_file:
            print("Error: --id_mapping_file is required when using --process_batch_file")
            return
            
        print(f"Processing existing batch file: {args.process_batch_file}")
        results = evaluator.process_existing_batch_file(args.process_batch_file, args.id_mapping_file)
        
        # Evaluate and save the results
        evaluator.evaluate_and_save_results(results, args.visualize)
    elif args.traj:
        # Single trajectory or specific pair
        if args.pair_id:
            print(f"Evaluating specific pair {args.pair_id} in trajectory {args.traj}")
            # Create a single batch item for the specified pair
            traj_folder = f"traj{args.traj}" if args.traj.isdigit() else args.traj
            traj_output_dir = os.path.join(evaluator.output_dir, traj_folder)
            os.makedirs(traj_output_dir, exist_ok=True)
            
            try:
                alice_images, bob_images = evaluator._get_image_paths(args.traj, args.pair_id)
                image_paths = alice_images + bob_images
                batch_item = [{
                    "traj": args.traj,
                    "pair_id": args.pair_id,
                    "image_paths": image_paths
                }]
                
                results = evaluator.process_batch(batch_item)
                
                # Save individual pair result
                if results and args.traj in results and args.pair_id in results[args.traj]:
                    result = results[args.traj][args.pair_id]
                    
                    # Try to visualize if requested
                    if args.visualize and result:
                        try:
                            gt_data = evaluator._load_ground_truth(args.traj)
                            gt_answer = gt_data[args.pair_id]
                            
                            alice_correct = gt_answer["Answer"]["Alice"].lower() == result["Answer"]["Alice"].lower()
                            bob_correct = gt_answer["Answer"]["Bob"].lower() == result["Answer"]["Bob"].lower()
                            is_correct = alice_correct and bob_correct
                            
                            vis_path = evaluator.visualize_evaluation(
                                args.traj, args.pair_id, alice_images, bob_images, 
                                result, gt_answer, is_correct
                            )
                            print(f"Visualization saved to: {vis_path}")
                        except Exception as e:
                            print(f"Error creating visualization: {e}")
                    
                    # Print result
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    print("Failed to evaluate pair")
            except Exception as e:
                print(f"Error evaluating pair: {e}")
        else:
            # Just a single trajectory
            traj_ids = [args.traj]
            print(f"Evaluating trajectory {args.traj}")
            evaluator.evaluate(traj_ids)
    else:
        # All trajectories
        print("Evaluating all trajectories")
        evaluator.evaluate()


if __name__ == "__main__":
    main()
