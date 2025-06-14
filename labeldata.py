from flask import Flask, render_template, request, redirect, url_for, send_from_directory
import os
from glob import glob
import re
from collections import defaultdict

app = Flask(__name__)

# 配置
BASE_FOLDER = 'googledata'
HEADING_ORDER = ['front', 'front_right', 'back_right', 'back_left', 'front_left']
ACTION_CHOICES = ['forward', 'turn left', 'turn right', 'turn backward', 'stop']

def get_grouped_images(random_seed):
    """获取分组后的图片数据，按time分组"""
    seed_folder = f"seed{random_seed}"
    image_dir = os.path.join(BASE_FOLDER, seed_folder)
    image_files = glob(os.path.join(image_dir, 'streetview_*.jpg'))
    
    # 按time分组
    time_groups = defaultdict(list)
    for img_path in image_files:
        info = parse_image_info(img_path)
        if info:
            time_groups[info['time']].append(info)
    
    # 对每个time组进行排序和验证
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
    
    return processed_groups

def sort_by_heading(images):
    heading_order = {h: i for i, h in enumerate(HEADING_ORDER)}
    return sorted(images, key=lambda x: heading_order.get(x['heading'], 999))

def parse_image_info(full_path):
    rel_path = os.path.relpath(full_path, BASE_FOLDER)
    basename = os.path.basename(full_path)
    match = re.match(r'streetview_(Alice|Bob)_(\d+)_([\w_]+)\.jpg', basename)
    if match:
        return {
            'agent': match.group(1),
            'time': int(match.group(2)),
            'heading': match.group(3),
            'filename': rel_path.replace('\\', '/'),
            'full_path': full_path
        }
    return None

@app.route('/googledata/<path:filename>')
def custom_static(filename):
    return send_from_directory(BASE_FOLDER, filename)

@app.route('/<int:random_seed>', methods=['GET', 'POST'])
def index(random_seed):
    image_groups = get_grouped_images(random_seed)
    if not image_groups:
        return f"在seed{random_seed}文件夹中没有找到有效的图片组！"

    # 获取当前处理的组索引（从URL参数或默认为0）
    current_group_index = int(request.args.get('group', 0))
    
    if request.method == 'POST':
        # 保存用户输入
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
        # 处理完当前组后，检查是否还有更多组
        if current_group_index + 1 < len(image_groups):
            return redirect(url_for('index', 
                                random_seed=random_seed,
                                group=current_group_index + 1))
        else:
            return "所有图片组已完成标注！"
    
    # 确保索引在有效范围内
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