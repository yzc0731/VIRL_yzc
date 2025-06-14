import json
import re

def parse_line(line):
    """解析单行数据并返回字典"""
    # 初始化结果字典
    result = {}
    
    # 使用正则表达式匹配各个部分
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
    
    # 构建字典结构
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
    """将整个txt文件转换为json"""
    final_result = {}
    
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:  # 忽略空行
                line_data = parse_line(line)
                final_result.update(line_data)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_result, f, indent=4, ensure_ascii=False)

# 使用示例
if __name__ == "__main__":
    input_file = "googledata/seed18/answer_user.txt"  # 你的输入txt文件
    output_file = "googledata/seed18/answer.json"  # 输出的json文件
    txt_to_json(input_file, output_file)
    print(f"转换完成，结果已保存到 {output_file}")