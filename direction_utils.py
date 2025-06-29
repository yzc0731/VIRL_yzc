import random
from typing import Dict, Tuple, List

# Direction constants
HEADING_ORDER = ['front', 'right', 'back', 'left']
ACTION_CHOICES = ['forward', 'turn left', 'turn right', 'turn backward', 'stay']

# Bob's heading mapping (from Alice's perspective to Bob's perspective)
BOB_HEADING_MAPPING = {
    'front': 'back',
    'right': 'left',
    'back': 'front',
    'left': 'right'
}

# Action mapping - corresponding action mappings after rotation
ACTION_ROTATION_MAPPING = {
    # Rotate 90 degrees (clockwise)
    90: {
        'forward': 'turn right',
        'turn left': 'forward',
        'turn right': 'turn backward',
        'turn backward': 'turn left',
        'stay': 'stay'
    },
    # Rotate 180 degrees
    180: {
        'forward': 'turn backward',
        'turn left': 'turn right',
        'turn right': 'turn left',
        'turn backward': 'forward',
        'stay': 'stay'
    },
    # Rotate 270 degrees (counterclockwise 90 degrees)
    270: {
        'forward': 'turn left',
        'turn left': 'turn backward',
        'turn right': 'forward',
        'turn backward': 'turn right',
        'stay': 'stay'
    }
}

def get_opposite_heading(heading: str) -> str:
    """Get the opposite heading (Bob's perspective)"""
    return BOB_HEADING_MAPPING.get(heading, heading)

def rotate_heading(heading: str, rotation_degrees: int) -> str:
    """
    Rotate heading based on given angle
    
    Args:
        heading: Original heading ('front', 'right', 'back', 'left')
        rotation_degrees: Rotation angle (90, 180, 270)
        
    Returns:
        Rotated heading
    """
    if heading not in HEADING_ORDER:
        return heading
    
    current_index = HEADING_ORDER.index(heading)
    steps = rotation_degrees // 90
    new_index = (current_index + steps) % 4
    
    return HEADING_ORDER[new_index]

def rotate_action(action: str, rotation_degrees: int) -> str:
    """
    Rotate action based on given angle
    
    Args:
        action: Original action ('forward', 'turn left', 'turn right', 'turn backward', 'stay')
        rotation_degrees: Rotation angle (0, 90, 180, 270)
        
    Returns:
        Rotated action
    """
    if action.lower() not in [a.lower() for a in ACTION_CHOICES]:
        return action
    
    action = action.lower()
    # If rotation is 0 degrees, return the original action
    if rotation_degrees == 0:
        return action
    
    # Otherwise return the rotated action according to the mapping table
    return ACTION_ROTATION_MAPPING.get(rotation_degrees, {}).get(action, action)

def get_random_rotation() -> int:
    """Return a random rotation angle (0, 90, 180, 270)"""
    return random.choice([0, 90, 180, 270])

def apply_augmentation(image_paths: List[str]) -> Tuple[List[str], int, int]:
    """
    Apply data augmentation: randomly rotate image order
    
    Args:
        image_paths: List of image paths [alice_front, alice_right, alice_back, alice_left, bob_front, bob_right, bob_back, bob_left]
        
    Returns:
        Rotated image path list, Alice's rotation angle, Bob's rotation angle
    """
    # Generate random rotation angles
    alice_rotation = get_random_rotation()
    bob_rotation = get_random_rotation()
    
    # Rotate image order
    alice_images = image_paths[:4]
    bob_images = image_paths[4:8] if len(image_paths) >= 8 else []
    
    # Calculate Alice's new image order
    alice_steps = alice_rotation // 90
    alice_images = alice_images[-alice_steps:] + alice_images[:-alice_steps] if alice_steps > 0 else alice_images
    
    # Calculate Bob's new image order
    bob_steps = bob_rotation // 90
    bob_images = bob_images[-bob_steps:] + bob_images[:-bob_steps] if bob_steps > 0 else bob_images
    
    # Combine image lists
    augmented_image_paths = alice_images + bob_images
    
    return augmented_image_paths, alice_rotation, bob_rotation

def transform_ground_truth(gt_answer: Dict, alice_rotation: int, bob_rotation: int) -> Dict:
    """
    Transform ground truth actions according to rotation angles
    
    Args:
        gt_answer: Original answer dictionary
        alice_rotation: Alice's rotation angle
        bob_rotation: Bob's rotation angle
        
    Returns:
        Updated answer dictionary
    """
    transformed_answer = {}
    
    if "Answer" in gt_answer:
        transformed_answer["Answer"] = {}
        
        if "Alice" in gt_answer["Answer"]:
            alice_action = gt_answer["Answer"]["Alice"].lower()
            transformed_answer["Answer"]["Alice"] = rotate_action(alice_action, alice_rotation)
            
        if "Bob" in gt_answer["Answer"]:
            bob_action = gt_answer["Answer"]["Bob"].lower()
            transformed_answer["Answer"]["Bob"] = rotate_action(bob_action, bob_rotation)
    
    # Copy Thought section (if it exists)
    if "Thought" in gt_answer:
        transformed_answer["Thought"] = gt_answer["Thought"]
    
    return transformed_answer

def update_prompt_for_rotated_images(prompt: str, alice_rotation: int, bob_rotation: int) -> str:
    """
    Update prompt to accommodate rotated image order
    
    Args:
        prompt: Original prompt text
        alice_rotation: Alice's rotation angle
        bob_rotation: Bob's rotation angle
        
    Returns:
        Updated prompt text
    """
    # More complex prompt adjustment logic may be needed in real applications
    # This is a simple implementation that adds rotation information
    rotation_info = f"\nNote: The images are rotated {alice_rotation} degrees for Alice and {bob_rotation} degrees for Bob."
    
    # Add rotation information to the appropriate place in the prompt
    # Assume the prompt has a closing brace for JSON format
    if "}" in prompt:
        # Add rotation info before the last closing brace
        prompt_parts = prompt.rsplit("}", 1)
        return prompt_parts[0] + rotation_info + "}" + prompt_parts[1]
    else:
        # If no closing brace, add to the end
        return prompt + rotation_info
    
    return prompt
