from vlm_eval import VLMEvaluator
import json
import os

# 定义文件路径
results_file = "/Users/huangrunhan/Desktop/hrh/Learning/Multimodal/Multiagent Rendezvous/VIRL_yzc/eval/gpt-4o-mini-07-03-16-04-37/batch_files/results_file-UrdHGs3ru2yDBRMwZCsDwy.jsonl"
output_dir = os.path.dirname(os.path.dirname(results_file))

# 创建ID映射
id_mapping = {}
with open(results_file, 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        custom_id = data['custom_id']
        parts = custom_id.split('_')
        if len(parts) >= 3:
            id_mapping[custom_id] = {"traj": parts[0], "pair_id": parts[1]}

# 保存临时ID映射文件
id_mapping_file = os.path.join(output_dir, "temp_id_mapping.json")
with open(id_mapping_file, 'w', encoding='utf-8') as f:
    json.dump(id_mapping, f, indent=2)

# 创建评估器并处理批处理文件
evaluator = VLMEvaluator(output_dir=output_dir, api_key="your_openai_api_key_here")
results = evaluator.process_existing_batch_file(results_file, id_mapping_file)
evaluator.evaluate_and_save_results(results)

# 删除临时文件（可选）
# os.remove(id_mapping_file)

print(f"批处理结果已处理，评估结果保存在 {output_dir}")