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
from typing import List, Dict, Tuple, Optional, Union
import io
import matplotlib.pyplot as plt

# Import direction utils
from direction_utils import (
    apply_augmentation, 
    transform_ground_truth, 
    update_prompt_for_rotated_images
)

class VLMEvaluator:
    """
    VLM evaluation class for calling OpenAI API for visual question answering and evaluating results
    """
    def __init__(self, 
                 textdata_folder: str = "textdata", 
                 googledata_folder: str = "googledata", 
                 output_dir: str = "eval_results",
                 api_key: str = None, 
                 model: str = "gpt-4o-mini",
                 include_thought: bool = False,
                 use_augmentation: bool = False,
                 image_resize: Optional[Tuple[int, int]] = None,
                 image_quality: int = 85,
                 request_delay: float = 0.0,
                 resume_eval: bool = True,
                 visualize: bool = False):
        """
        Initialize the VLM evaluator
        
        Args:
            textdata_folder: Folder containing ground truth answers
            googledata_folder: Folder containing images
            output_dir: Folder for output results
            api_key: OpenAI API key
            model: OpenAI model to use
            include_thought: Whether to include Thought in the prompt (default: False)
            use_augmentation: Whether to use data augmentation (default: False)
            image_resize: Optional tuple (width, height) to resize images (default: None)
            image_quality: JPEG quality for image compression (0-100, default: 85)
            request_delay: Delay in seconds between API requests to avoid rate limits (default: 0.0)
            resume_eval: Whether to resume evaluation from previously saved results (default: True)
            visualize: Whether to generate visualization images (default: False)
        """
        self.textdata_folder = textdata_folder
        self.googledata_folder = googledata_folder
        self.output_dir = output_dir
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.include_thought = include_thought
        self.use_augmentation = use_augmentation
        self.image_resize = image_resize
        self.image_quality = image_quality
        self.request_delay = request_delay
        self.resume_eval = resume_eval
        self.visualize = visualize
        
        # Store current augmentation parameters
        self.current_alice_rotation = 0
        self.current_bob_rotation = 0
        
        if not self.api_key:
            raise ValueError("API key not provided. Please pass it as a parameter or set the OPENAI_API_KEY environment variable")
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Set prompt template based on whether to include thought
        self._set_prompt_template()
        
        # Define constants for visualization
        self.heading_order = ['front', 'right', 'back', 'left']
        
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
        "Alice": "Recommended next action for Alice (only use one of these exact words: forward, turn left, turn right, turn backward, stay)",
        "Bob": "Recommended next action for Bob (only use one of these exact words: forward, turn left, turn right, turn backward, stay)"
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
                # Resize image if specified
                if self.image_resize:
                    img = img.resize(self.image_resize, Image.LANCZOS)
                
                # Save with compression
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=self.image_quality, optimize=True)
                return buffer.getvalue()
        except Exception as e:
            print(f"Error processing image {image_path}: {e}")
            # Fallback to original image
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
        if pair_idx >= len(metainfo['Alice points']) or pair_idx < 0:
            raise ValueError(f"Invalid pair ID {pair_id} for trajectory {traj}")
            
        alice_pano_id = metainfo['Alice points'][pair_idx]
        bob_pano_id = metainfo['Bob points'][pair_idx]
        
        # Define heading order
        heading_order = ['front', 'right', 'back', 'left']
        # Bob's perspective is flipped
        bob_heading_mapping = {
            'front': 'back',
            'right': 'left',
            'back': 'front',
            'left': 'right'
        }
        
        # Get Alice images
        alice_images = []
        for heading in heading_order:
            img_path = os.path.join(place_folder, f'id_{alice_pano_id}_{heading}.jpg')
            if os.path.exists(img_path):
                alice_images.append(img_path)
        
        # Get Bob images
        bob_images = []
        for heading in heading_order:
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
        # Handle numeric trajectory names by adding 'traj' prefix if needed
        traj_folder = f"traj{traj}" if traj.isdigit() else traj
        
        answer_path = os.path.join(self.textdata_folder, traj_folder, 'answer.json')
        if not os.path.exists(answer_path):
            raise FileNotFoundError(f"Could not find ground truth answer file for trajectory {traj} at {answer_path}")
        
        with open(answer_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def call_vlm_api(self, image_paths: List[str]) -> Dict:
        """Call OpenAI API for visual question answering"""
        # Add delay before making the request to avoid rate limits
        if self.request_delay > 0:
            time.sleep(self.request_delay)
            
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Prepare prompt template
        prompt_template = self.prompt_template
        
        # If augmentation is used, adjust direction descriptions in the prompt
        if self.use_augmentation and (self.current_alice_rotation > 0 or self.current_bob_rotation > 0):
            prompt_template = update_prompt_for_rotated_images(
                prompt_template, 
                self.current_alice_rotation, 
                self.current_bob_rotation
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
        
        # Maximum retry attempts
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
                
                # If successful, return response
                if (response.status_code == 200):
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
                            wait_time = float(wait_match.group(1))
                    except:
                        pass
                    
                    print(f"Waiting {wait_time} seconds before retrying...")
                    time.sleep(wait_time)
                    continue
                
                # Other errors
                print(f"API error: {response.status_code}")
                print(response.text)
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                
            except Exception as e:
                print(f"Request error: {str(e)}")
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
        
        raise Exception("Maximum retry attempts reached, could not complete API request")
    
    def parse_vlm_response(self, response: Dict) -> Optional[Dict]:
        """Parse OpenAI API response to extract JSON answer"""
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
            
            # Parse JSON
            return json.loads(json_content)
        except Exception as e:
            print(f"Failed to parse VLM response: {e}")
            print(f"Raw content: {content if 'content' in locals() else 'not retrieved'}")
            return None
    
    def _get_route_image_path(self, traj: str, pair_id: str) -> Optional[str]:
        """
        Get the path to the route visualization image
        
        Args:
            traj: Trajectory ID
            pair_id: Pair ID within the trajectory
            
        Returns:
            Path to the route image if it exists, None otherwise
        """
        # Handle numeric trajectory names by adding 'traj' prefix if needed
        traj_folder = f"traj{traj}" if traj.isdigit() else traj
        
        route_path = os.path.join(self.textdata_folder, traj_folder, f'route_{pair_id}.png')
        return route_path if os.path.exists(route_path) else None
    
    def visualize_evaluation(self, traj: str, pair_id: str, alice_images: List[str], 
                             bob_images: List[str], prediction: Dict, ground_truth: Dict, 
                             is_correct: bool) -> str:
        """
        Create a visualization of the evaluation results
        
        Args:
            traj: Trajectory ID
            pair_id: Pair ID within the trajectory
            alice_images: List of Alice's image paths
            bob_images: List of Bob's image paths
            prediction: Model prediction
            ground_truth: Ground truth answer
            is_correct: Whether the prediction is correct
            
        Returns:
            Path to the saved visualization image
        """
        # Create a figure with subplots
        fig = plt.figure(figsize=(20, 15))
        
        # Add title with accuracy indication
        accuracy_indicator = "✓ Correct" if is_correct else "✗ Incorrect"
        fig.suptitle(f"Evaluation Results: Trajectory {traj}, Pair {pair_id} - {accuracy_indicator}", 
                    fontsize=16, color='green' if is_correct else 'red')
        
        # Determine actual heading labels based on rotation (if augmentation was used)
        alice_rotation = prediction.get("_augmentation", {}).get("alice_rotation", 0) if isinstance(prediction, dict) else 0
        bob_rotation = prediction.get("_augmentation", {}).get("bob_rotation", 0) if isinstance(prediction, dict) else 0
        
        # Calculate rotated heading orders
        rotated_alice_headings = self._get_rotated_headings(self.heading_order, alice_rotation)
        rotated_bob_headings = self._get_rotated_headings(self.heading_order, bob_rotation)
        
        # Plot Alice's images (first row)
        for i in range(min(4, len(alice_images))):
            ax = fig.add_subplot(3, 4, i+1)
            img = Image.open(alice_images[i])
            ax.imshow(img)
            ax.set_title(f"Alice - {rotated_alice_headings[i]}")
            ax.axis('off')
        
        # Plot Bob's images (second row)
        for i in range(min(4, len(bob_images))):
            ax = fig.add_subplot(3, 4, i+5)
            img = Image.open(bob_images[i])
            ax.imshow(img)
            ax.set_title(f"Bob - {rotated_bob_headings[i]}")
            ax.axis('off')
        
        # Add text for predictions and ground truth
        ax = fig.add_subplot(3, 4, (9, 12))
        text_content = []
        
        # Add model prediction
        text_content.append("Model Prediction:")
        text_content.append(f"Alice: {prediction['Answer']['Alice']}")
        text_content.append(f"Bob: {prediction['Answer']['Bob']}")
        
        if "Thought" in prediction:
            text_content.append("\nModel Reasoning:")
            if "Detection" in prediction["Thought"]:
                text_content.append(f"Detection: {prediction['Thought']['Detection']}")
            if "Orientation" in prediction["Thought"] and "Alice" in prediction["Thought"]["Orientation"]:
                text_content.append(f"Alice Orientation: {prediction['Thought']['Orientation']['Alice']}")
            if "Orientation" in prediction["Thought"] and "Bob" in prediction["Thought"]["Orientation"]:
                text_content.append(f"Bob Orientation: {prediction['Thought']['Orientation']['Bob']}")
            if "Conclusion" in prediction["Thought"]:
                text_content.append(f"Conclusion: {prediction['Thought']['Conclusion']}")
        
        # Add ground truth
        text_content.append("\nGround Truth:")
        text_content.append(f"Alice: {ground_truth['Answer']['Alice']}")
        text_content.append(f"Bob: {ground_truth['Answer']['Bob']}")
        
        # Add augmentation info if available
        if alice_rotation != 0 or bob_rotation != 0:
            text_content.append(f"\nAugmentation Applied:")
            text_content.append(f"Alice rotation: {alice_rotation}°")
            text_content.append(f"Bob rotation: {bob_rotation}°")
        
        ax.text(0.01, 0.99, "\n".join(text_content), verticalalignment='top', 
                wrap=True, fontsize=12)
        ax.axis('off')
        
        # Save the figure
        traj_folder = f"traj{traj}" if traj.isdigit() else traj
        vis_dir = os.path.join(self.output_dir, traj_folder, "visualizations")
        os.makedirs(vis_dir, exist_ok=True)
        
        output_path = os.path.join(vis_dir, f"eval_{pair_id}.png")
        plt.tight_layout(rect=[0, 0, 1, 0.96])  # Adjust for title
        plt.savefig(output_path)
        plt.close()
        
        return output_path

    def _get_rotated_headings(self, headings: List[str], rotation_degrees: int) -> List[str]:
        """
        Get rotated heading labels based on the applied rotation
        
        Args:
            headings: Original heading order
            rotation_degrees: Rotation applied in degrees
        
        Returns:
            Rotated heading labels
        """
        if rotation_degrees == 0:
            return headings
        
        # Calculate how many positions to shift (90 degrees = 1 position)
        shifts = (rotation_degrees // 90) % 4
        if shifts < 0:
            shifts += 4  # Handle negative rotations
        
        # Rotate the headings
        rotated = headings[shifts:] + headings[:shifts]
        return rotated
    
    def evaluate_single_pair(self, traj: str, pair_id: str, save_results: bool = True) -> Dict:
        """Evaluate a single image pair"""
        print(f"Evaluating trajectory {traj} pair ID {pair_id}")
        
        # Reset current rotation angles
        self.current_alice_rotation = 0
        self.current_bob_rotation = 0
        
        # Get image paths
        alice_images, bob_images = self._get_image_paths(traj, pair_id)
        
        # Handle numeric trajectory names for result saving
        traj_folder = f"traj{traj}" if traj.isdigit() else traj
        
        # Check if results already exist and resume_eval is enabled
        results_path = os.path.join(self.output_dir, traj_folder, f"{pair_id}_result.json")
        if os.path.exists(results_path) and (self.resume_eval or not self.use_augmentation):
            print(f"Evaluation result already exists, loading: {results_path}")
            with open(results_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # Prepare images
        image_paths = []
        image_paths.extend(alice_images)
        image_paths.extend(bob_images)
        
        # Apply data augmentation (if enabled)
        if self.use_augmentation:
            image_paths, self.current_alice_rotation, self.current_bob_rotation = apply_augmentation(image_paths)
            print(f"Applied data augmentation with rotations: Alice={self.current_alice_rotation}°, Bob={self.current_bob_rotation}°")
        
        # Call API
        response = self.call_vlm_api(image_paths)
        
        # Parse response
        result = self.parse_vlm_response(response)
        
        # If augmentation is enabled and parsing is successful, record the augmentation parameters used
        if result and self.use_augmentation:
            result["_augmentation"] = {
                "alice_rotation": self.current_alice_rotation,
                "bob_rotation": self.current_bob_rotation
            }
        
        if result and save_results:
            # Ensure directory exists
            os.makedirs(os.path.dirname(results_path), exist_ok=True)
            
            # Save result
            with open(results_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
        
        # If we have a result and visualize is enabled, create visualization
        if result and save_results and self.visualize:
            try:
                # Try to load ground truth for visualization
                gt_data = self._load_ground_truth(traj)
                if pair_id in gt_data:
                    gt_answer = gt_data[pair_id]
                    
                    # Calculate accuracy
                    is_correct_alice = gt_answer["Answer"]["Alice"].lower() == result["Answer"]["Alice"].lower()
                    is_correct_bob = gt_answer["Answer"]["Bob"].lower() == result["Answer"]["Bob"].lower()
                    is_correct = is_correct_alice and is_correct_bob
                    
                    # Create visualization
                    vis_path = self.visualize_evaluation(
                        traj, pair_id, alice_images, bob_images, 
                        result, gt_answer, is_correct
                    )
                    print(f"Visualization saved to: {vis_path}")
            except Exception as e:
                print(f"Warning: Failed to create visualization: {e}")
        
        return result
    
    def evaluate_trajectory(self, traj: str, pairs: List[str] = None) -> Dict:
        """Evaluate an entire trajectory or specified pairs"""
        # Load ground truth
        gt_data = self._load_ground_truth(traj)
        
        # If no pairs specified, evaluate all pairs
        if not pairs:
            pairs = list(gt_data.keys())
        
        # Handle numeric trajectory names for result saving
        traj_folder = f"traj{traj}" if traj.isdigit() else traj
        
        # Check if trajectory results already exist and we should resume evaluation
        results_path = os.path.join(self.output_dir, traj_folder, "trajectory_results.json")
        existing_results = {}
        existing_metrics = {"correct": 0, "total": 0}
        
        # Load metainfo to check available pairs
        try:
            metainfo_path = os.path.join(self.textdata_folder, traj_folder, 'metainfo.json')
            with open(metainfo_path, 'r', encoding='utf-8') as f:
                metainfo = json.load(f)
            
            # Calculate the maximum valid pair ID based on metainfo
            max_valid_pair = min(len(metainfo.get('Alice points', [])), len(metainfo.get('Bob points', []))) - 1
            
            # Filter pairs to only include valid ones
            valid_pairs = [p for p in pairs if int(p) <= max_valid_pair]
            
            if len(valid_pairs) < len(pairs):
                print(f"Warning: Found {len(pairs) - len(valid_pairs)} invalid pair IDs in trajectory {traj}.")
                print(f"Valid pair IDs range from 0 to {max_valid_pair}.")
                pairs = valid_pairs
        except Exception as e:
            print(f"Warning: Could not validate pair IDs against metainfo: {e}")
        
        if os.path.exists(results_path) and self.resume_eval:
            try:
                with open(results_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    existing_results = existing_data.get("results", {})
                    existing_metrics = existing_data.get("metrics", {"correct": 0, "total": 0})
                
                # Check if we have results for all valid pairs
                all_evaluated = True
                for pair_id in pairs:
                    if pair_id not in existing_results:
                        all_evaluated = False
                        break
                
                if all_evaluated:
                    print(f"All pairs in trajectory {traj} have already been evaluated. Loading existing results.")
                    
                    # Recalculate metrics to ensure they are correct
                    recalculated_metrics = {"correct": 0, "total": 0}
                    for pair_id, result in existing_results.items():
                        recalculated_metrics["total"] += 1
                        if result.get("is_correct", False):
                            recalculated_metrics["correct"] += 1
                    
                    if recalculated_metrics["total"] > 0:
                        recalculated_metrics["accuracy"] = recalculated_metrics["correct"] / recalculated_metrics["total"]
                    else:
                        recalculated_metrics["accuracy"] = 0
                    
                    # If the metrics don't match what's in the file, update and save
                    if recalculated_metrics["correct"] != existing_metrics["correct"] or \
                       recalculated_metrics["total"] != existing_metrics["total"]:
                        print(f"Metrics mismatch detected. Updating from {existing_metrics['correct']}/{existing_metrics['total']} to {recalculated_metrics['correct']}/{recalculated_metrics['total']}")
                        existing_data["metrics"] = recalculated_metrics
                        with open(results_path, 'w', encoding='utf-8') as f:
                            json.dump(existing_data, f, indent=2, ensure_ascii=False)
                    
                    # Generate visualizations for existing results if visualize flag is set
                    if self.visualize:
                        print("Generating visualizations for existing results...")
                        vis_dir = os.path.join(self.output_dir, traj_folder, "visualizations")
                        os.makedirs(vis_dir, exist_ok=True)
                        
                        for pair_id, result_data in existing_results.items():
                            # Check if visualization already exists
                            vis_path = os.path.join(vis_dir, f"eval_{pair_id}.png")
                            if not os.path.exists(vis_path):
                                try:
                                    # Get image paths for this pair
                                    alice_images, bob_images = self._get_image_paths(traj, pair_id)
                                    
                                    # Extract prediction and ground truth
                                    prediction = result_data.get("prediction", {})
                                    ground_truth = result_data.get("ground_truth", {})
                                    is_correct = result_data.get("is_correct", False)
                                    
                                    # Create visualization
                                    vis_path = self.visualize_evaluation(
                                        traj, pair_id, alice_images, bob_images, 
                                        prediction, ground_truth, is_correct
                                    )
                                    print(f"Created visualization for pair {pair_id}: {vis_path}")
                                except Exception as e:
                                    print(f"Failed to create visualization for pair {pair_id}: {e}")
                    
                    return {"metrics": recalculated_metrics, "results": existing_results}
                else:
                    print(f"Resuming evaluation for trajectory {traj} with {len([p for p in pairs if p not in existing_results])} remaining pairs.")
                    print(f"Existing metrics: {existing_metrics['correct']}/{existing_metrics['total']} correct")
                    
                    # Filter out pairs that have already been evaluated
                    pairs = [p for p in pairs if p not in existing_results]
            except Exception as e:
                print(f"Error loading existing results: {e}. Starting fresh evaluation.")
                existing_results = {}
                existing_metrics = {"correct": 0, "total": 0}
        
        results = existing_results.copy()
        metrics = {"correct": 0, "total": 0}
        
        for pair_id in tqdm(pairs, desc=f"Evaluating trajectory {traj}"):
            if pair_id not in gt_data:
                print(f"Warning: Pair ID {pair_id} does not exist in ground truth, skipping")
                continue
                
            try:
                # Evaluate single pair
                result = self.evaluate_single_pair(traj, pair_id)
                
                if not result:
                    print(f"Warning: Evaluation failed for pair ID {pair_id}, skipping")
                    continue
                
                # Get original ground truth
                gt_answer = gt_data[pair_id]
                pred_answer = result
                
                # If data augmentation is enabled, transform ground truth to match augmented input
                if self.use_augmentation and "_augmentation" in result:
                    aug_info = result["_augmentation"]
                    alice_rotation = aug_info["alice_rotation"]
                    bob_rotation = aug_info["bob_rotation"]
                    
                    # Transform ground truth
                    gt_answer = transform_ground_truth(gt_data[pair_id], alice_rotation, bob_rotation)
                
                # Calculate accuracy
                is_correct_alice = gt_answer["Answer"]["Alice"].lower() == pred_answer["Answer"]["Alice"].lower()
                is_correct_bob = gt_answer["Answer"]["Bob"].lower() == pred_answer["Answer"]["Bob"].lower()
                is_correct = is_correct_alice and is_correct_bob
                
                # Update metrics for current batch
                metrics["total"] += 1
                if is_correct:
                    metrics["correct"] += 1
                
                # Save results
                results[pair_id] = {
                    "prediction": result,
                    "ground_truth": gt_data[pair_id],
                    "transformed_ground_truth": gt_answer if self.use_augmentation else None,
                    "is_correct": is_correct,
                    "is_correct_alice": is_correct_alice,
                    "is_correct_bob": is_correct_bob
                }
                
                # Generate visualization if enabled and not done in evaluate_single_pair
                if self.visualize and not save_results:
                    try:
                        # Get image paths for visualization
                        alice_images, bob_images = self._get_image_paths(traj, pair_id)
                        
                        # Create visualization
                        vis_path = self.visualize_evaluation(
                            traj, pair_id, alice_images, bob_images, 
                            pred_answer, gt_answer, is_correct
                        )
                        print(f"Visualization saved to: {vis_path}")
                    except Exception as e:
                        print(f"Warning: Failed to create visualization for pair {pair_id}: {e}")
                
                # Calculate combined metrics including existing and current
                combined_metrics = {
                    "correct": metrics["correct"] + existing_metrics["correct"],
                    "total": metrics["total"] + existing_metrics["total"]
                }
                
                if combined_metrics["total"] > 0:
                    combined_metrics["accuracy"] = combined_metrics["correct"] / combined_metrics["total"]
                else:
                    combined_metrics["accuracy"] = 0
                
                # Save intermediate results after each pair to enable resuming
                os.makedirs(os.path.dirname(results_path), exist_ok=True)
                with open(results_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        "metrics": combined_metrics,
                        "results": results
                    }, f, indent=2, ensure_ascii=False)
                
            except Exception as e:
                print(f"Error evaluating pair ID {pair_id}: {str(e)}")
        
        # Final metrics combine both existing and current results
        final_metrics = {
            "correct": metrics["correct"] + existing_metrics["correct"],
            "total": metrics["total"] + existing_metrics["total"]
        }
        
        # Calculate final accuracy
        if final_metrics["total"] > 0:
            final_metrics["accuracy"] = final_metrics["correct"] / final_metrics["total"]
        else:
            final_metrics["accuracy"] = 0
        
        # Save trajectory evaluation results
        with open(results_path, 'w', encoding='utf-8') as f:
            json.dump({
                "metrics": final_metrics,
                "results": results
            }, f, indent=2, ensure_ascii=False)
        
        return {
            "metrics": final_metrics,
            "results": results
        }

    def evaluate_all_trajectories(self, trajs: List[str] = None) -> Dict:
        """Evaluate all trajectories or specified trajectories"""
        # If no trajectories specified, find all with answer.json
        if not trajs:
            trajs = []
            for item in os.listdir(self.textdata_folder):
                traj_dir = os.path.join(self.textdata_folder, item)
                if os.path.isdir(traj_dir) and os.path.exists(os.path.join(traj_dir, 'answer.json')):
                    trajs.append(item)
        
        # Check if overall results already exist and we should resume evaluation
        results_path = os.path.join(self.output_dir, "overall_results.json")
        existing_overall_metrics = {"correct": 0, "total": 0}
        existing_trajectory_results = {}
        completed_trajs = []
        
        if os.path.exists(results_path) and self.resume_eval:
            try:
                with open(results_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    existing_overall_metrics = existing_data.get("overall_metrics", {"correct": 0, "total": 0})
                    existing_trajectory_results = existing_data.get("trajectory_metrics", {})
                    print(f"Loaded existing overall metrics: {existing_overall_metrics['correct']}/{existing_overall_metrics['total']} correct")
                
                # Determine which trajectories have been fully completed
                for traj in list(trajs):
                    traj_id = f"traj{traj}" if traj.isdigit() else traj
                    if traj_id in existing_trajectory_results:
                        traj_results_path = os.path.join(self.output_dir, traj_id, "trajectory_results.json")
                        if os.path.exists(traj_results_path):
                            with open(traj_results_path, 'r', encoding='utf-8') as f:
                                traj_data = json.load(f)
                                gt_data = self._load_ground_truth(traj)
                                # If all pairs have been evaluated, mark as completed
                                if len(traj_data.get("results", {})) == len(gt_data):
                                    completed_trajs.append(traj)
                                    print(f"Trajectory {traj} is already fully evaluated.")
                
                # Remove completed trajectories from the list to evaluate
                for traj in completed_trajs:
                    if traj in trajs:
                        trajs.remove(traj)
                
                if not trajs:
                    print("All trajectories have already been fully evaluated. Loading existing results.")
                    return existing_data
                else:
                    print(f"Resuming evaluation with {len(trajs)} remaining trajectories.")
            except Exception as e:
                print(f"Error loading existing results: {e}. Starting fresh evaluation.")
                existing_overall_metrics = {"correct": 0, "total": 0}
                existing_trajectory_results = {}
                completed_trajs = []
        
        overall_metrics = {"correct": 0, "total": 0}
        trajectory_results = existing_trajectory_results.copy()
        
        # First add metrics from completed trajectories that we don't need to re-evaluate
        for traj in completed_trajs:
            traj_id = f"traj{traj}" if traj.isdigit() else traj
            if traj_id in existing_trajectory_results:
                traj_metrics = existing_trajectory_results[traj_id]
                print(f"Adding metrics from completed trajectory {traj}: {traj_metrics.get('correct', 0)}/{traj_metrics.get('total', 0)}")
                overall_metrics["correct"] += traj_metrics.get("correct", 0)
                overall_metrics["total"] += traj_metrics.get("total", 0)
        
        # Now evaluate the remaining trajectories
        for traj in trajs:
            try:
                result = self.evaluate_trajectory(traj)
                traj_id = f"traj{traj}" if traj.isdigit() else traj
                
                # Print detailed metrics for this trajectory for better debugging
                print(f"Trajectory {traj} evaluation complete: {result['metrics']['correct']}/{result['metrics']['total']} correct")
                
                trajectory_results[traj_id] = result["metrics"]
                
                # Update overall metrics
                overall_metrics["correct"] += result["metrics"]["correct"]
                overall_metrics["total"] += result["metrics"]["total"]
                
                # Calculate combined metrics including existing and current
                combined_metrics = {
                    "correct": overall_metrics["correct"] + existing_overall_metrics["correct"],
                    "total": overall_metrics["total"] + existing_overall_metrics["total"]
                }
                
                if combined_metrics["total"] > 0:
                    combined_metrics["accuracy"] = combined_metrics["correct"] / combined_metrics["total"]
                else:
                    combined_metrics["accuracy"] = 0
                
                # Save intermediate overall results after each trajectory
                with open(results_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        "overall_metrics": combined_metrics,
                        "trajectory_metrics": trajectory_results
                    }, f, indent=2, ensure_ascii=False)
                
            except Exception as e:
                print(f"Error evaluating trajectory {traj}: {str(e)}")
        
        # Calculate final overall metrics by combining new results with existing metrics
        final_overall_metrics = {
            "correct": overall_metrics["correct"] + existing_overall_metrics["correct"],
            "total": overall_metrics["total"] + existing_overall_metrics["total"]
        }
        
        if final_overall_metrics["total"] > 0:
            final_overall_metrics["accuracy"] = final_overall_metrics["correct"] / final_overall_metrics["total"]
        else:
            final_overall_metrics["accuracy"] = 0
        
        # Save overall evaluation results
        with open(results_path, 'w', encoding='utf-8') as f:
            json.dump({
                "overall_metrics": final_overall_metrics,
                "trajectory_metrics": trajectory_results
            }, f, indent=2, ensure_ascii=False)
        
        print(f"\nOverall accuracy: {final_overall_metrics['accuracy']:.4f} ({final_overall_metrics['correct']}/{final_overall_metrics['total']})")
        print(f"Detailed results saved to: {results_path}")
        
        return {
            "overall_metrics": final_overall_metrics,
            "trajectory_metrics": trajectory_results
        }


def main():
    parser = argparse.ArgumentParser(description='VLM Evaluation Tool')
    parser.add_argument('--textdata_folder', type=str, default="textdata", help='Folder containing ground truth answers')
    parser.add_argument('--googledata_folder', type=str, default="googledata", help='Folder containing images')
    parser.add_argument('--output_dir', type=str, default="eval_results", help='Folder for output results')
    parser.add_argument('--api_key', type=str, default=None, help='OpenAI API key')
    parser.add_argument('--model', type=str, default="gpt-4o-mini", help='OpenAI model to use')
    parser.add_argument('--traj', type=str, default=None, help='Trajectory to evaluate, if not specified will evaluate all')
    parser.add_argument('--pair_id', type=str, default=None, help='Pair ID to evaluate, if not specified will evaluate all pairs')
    parser.add_argument('--include_thought', action='store_true', help='Include Thought in the output (default: False)')
    parser.add_argument('--use_augmentation', action='store_true', help='Use data augmentation for evaluation (default: False)')
    parser.add_argument('--image_width', type=int, default=None, help='Width to resize images (default: original size)')
    parser.add_argument('--image_height', type=int, default=None, help='Height to resize images (default: original size)')
    parser.add_argument('--image_quality', type=int, default=85, help='JPEG quality for image compression (0-100, default: 85)')
    parser.add_argument('--request_delay', type=float, default=0.0, help='Delay in seconds between API requests (default: 0.0)')
    parser.add_argument('--no_resume', action='store_true', help='Disable resuming from previous evaluation results (default: resume enabled)')
    parser.add_argument('--visualize', action='store_true', help='Generate visualization images for evaluation results (default: False)')
    
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
        request_delay=args.request_delay,
        resume_eval=not args.no_resume,
        visualize=args.visualize
    )
    
    if args.traj and args.pair_id:
        # Evaluate single pair
        result = evaluator.evaluate_single_pair(args.traj, args.pair_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.traj:
        # Evaluate single trajectory
        result = evaluator.evaluate_trajectory(args.traj)
        print(f"Trajectory {args.traj} accuracy: {result['metrics']['accuracy']:.4f} ({result['metrics']['correct']}/{result['metrics']['total']})")
        
        # Check if visualizations were created
        traj_folder = f"traj{args.traj}" if args.traj.isdigit() else args.traj
        vis_dir = os.path.join(args.output_dir, traj_folder, "visualizations")
        if os.path.exists(vis_dir):
            vis_files = os.listdir(vis_dir)
            if vis_files:
                print(f"Created {len(vis_files)} visualization(s) in: {vis_dir}")
            else:
                print(f"No visualizations were created in: {vis_dir}")
        else:
            print(f"Visualization directory not found: {vis_dir}")
    else:
        # Evaluate all trajectories
        evaluator.evaluate_all_trajectories()


if __name__ == "__main__":
    main()
