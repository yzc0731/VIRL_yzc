import json
import re

def parse_line(line):
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

def txt_to_json(input_file, output_file):
    """Convert the entire txt file to json"""
    final_result = {}
    
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                line_data = parse_line(line)
                final_result.update(line_data)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_result, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Google Street View Data Download Tool")
    parser.add_argument("--seed", type=int, help="Random seed for data directory naming")
    args = parser.parse_args()
    input_file = f"googledata/seed{args.seed}/answer_user.txt"
    output_file = f"googledata/seed{args.seed}/answer.json"
    txt_to_json(input_file, output_file)
    print(f"Saved to {output_file}")