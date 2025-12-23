import os
import subprocess
import json
import shutil
import threading
import zipfile
import sys
import uuid
import datetime
import re
import requests
from openai import OpenAI
from functools import wraps
from urllib.parse import unquote, unquote_plus
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, session, jsonify
# 新增：用于多线程并发处理
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# ================= 配置区 =================
ADMIN_USERNAME = os.environ.get('ADMIN_USER', 'admin') 
ADMIN_PASSWORD = os.environ.get('ADMIN_PASS', 'password123') 
SECRET_KEY = os.environ.get('SECRET_KEY', 'seaside_secret_key')
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '') 
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

BASE_DIR = "/data"
CONFIG_FILE = os.path.join(BASE_DIR, '.tracker_config.json')

app.secret_key = SECRET_KEY
task_store = {} # 存储所有任务（做种 + 翻译）的状态和日志

# ================= 辅助函数 =================

def log_task(task_id, message):
    """记录任务日志"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(log_entry, flush=True) # 控制台打印
    
    if task_id in task_store:
        # 存入内存供前端轮询
        if 'logs' not in task_store[task_id]:
            task_store[task_id]['logs'] = []
        task_store[task_id]['logs'].append(log_entry)
        task_store[task_id]['msg'] = message # 更新简短状态

def get_safe_path(rel_path):
    if not rel_path: rel_path = ""
    clean_rel = rel_path.strip('/')
    abs_base = os.path.abspath(BASE_DIR)
    abs_target = os.path.abspath(os.path.join(abs_base, clean_rel))
    if not abs_target.startswith(abs_base): raise ValueError("非法路径访问")
    return abs_target

def load_default_tracker():
    default_url = "http://udp.opentrackr.org:1337/announce"
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                return data.get('tracker_url', default_url)
    except Exception: pass
    return default_url

def save_default_tracker(url):
    try:
        with open(CONFIG_FILE, 'w') as f: json.dump({'tracker_url': url}, f)
    except Exception: pass

def find_largest_file(start_path):
    if os.path.isfile(start_path): return start_path
    largest_file = None; max_size = 0
    for root, dirs, files in os.walk(start_path):
        for f in files:
            file_path = os.path.join(root, f)
            if 'torrent' in root.split(os.sep): continue
            try:
                size = os.path.getsize(file_path)
                if size > max_size and size > 50 * 1024 * 1024:
                    max_size = size; largest_file = file_path
            except OSError: continue
    return largest_file

def get_video_duration(video_path):
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        val = result.stdout.strip()
        return float(val) if val else 0
    except: return 0

# === 翻译逻辑 (多线程优化版) ===
def background_translate(task_id, file_path):
    log_task(task_id, f"开始处理文件: {os.path.basename(file_path)}")
    
    if not DEEPSEEK_API_KEY:
        log_task(task_id, "❌ 错误: 未配置 DeepSeek API Key")
        task_store[task_id]['status'] = 'error'
        return

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    filename = os.path.basename(file_path)
    is_srt = filename.lower().endswith('.srt')
    
    try:
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            full_content = f.read()

        if not full_content.strip():
            log_task(task_id, "文件内容为空，结束。")
            task_store[task_id]['status'] = 'done'
            return

        blocks = []
        if is_srt:
            log_task(task_id, "检测到 SRT 字幕，正在按时间轴分块...")
            # 统一换行符
            full_content = full_content.replace('\r\n', '\n').replace('\r', '\n')
            # 按双换行符分割 SRT 块
            blocks = re.split(r'\n\s*\n', full_content)
            blocks = [b.strip() for b in blocks if b.strip()]
            log_task(task_id, f"解析完成，共 {len(blocks)} 个字幕段落。")
        else:
            log_task(task_id, "普通文本模式，按行处理...")
            blocks = [line.strip() for line in full_content.split('\n') if line.strip()]

        # 批处理配置
        BATCH_SIZE = 30  # 每个请求包含的字幕块数量
        total_batches = (len(blocks) + BATCH_SIZE - 1) // BATCH_SIZE
        
        # 定义处理单个批次的内部函数
        def _process_batch(batch_index, batch_blocks):
            """
            处理单个批次的子函数，返回 (index, translated_text)
            """
            batch_input_text = "\n\n".join(batch_blocks)
            
            system_prompt = (
                "你是一位精通多国语言的电影字幕翻译专家。我将发给你一段包含时间轴的 SRT 原文。"
                "请结合上下文语境（Context），将对话内容翻译成流畅、地道的简体中文。"
                "**严格遵守以下格式规则**："
                "1. **绝对保留**原有的序号和时间轴，严禁修改数字。"
                "2. 仅将时间轴下方的外语对话替换为中文翻译。"
                "3. 保持原有的 SRT 格式结构（序号-时间-文本），段落之间用空行分隔。"
                "4. 不要输出任何解释性文字，只输出翻译后的 SRT 内容。"
            )
            
            retry_count = 0
            while retry_count < 3:
                try:
                    response = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"请翻译以下字幕片段:\n\n{batch_input_text}"},
                        ],
                        stream=False,
                        temperature=1.3
                    )
                    res_raw = response.choices[0].message.content.strip()
                    res_raw = res_raw.replace('```srt', '').replace('```', '').strip()
                    
                    if res_raw:
                        return batch_index, res_raw
                    else:
                        raise ValueError("AI 返回内容为空")
                except Exception as e:
                    retry_count += 1
            
            # 失败兜底：返回原文，避免缺失
            return batch_index, batch_input_text

        # 准备所有批次数据
        all_batches = []
        for i in range(0, len(blocks), BATCH_SIZE):
            batch_data = blocks[i:i + BATCH_SIZE]
            batch_index = i // BATCH_SIZE
            all_batches.append((batch_index, batch_data))

        translated_results = [None] * len(all_batches) # 预分配槽位
        completed_count = 0
        
        # 并发执行配置
        MAX_WORKERS = 8 # 线程数，建议 5-10
        
        log_task(task_id, f"🚀 启动并发翻译，线程数: {MAX_WORKERS}，共 {total_batches} 个批次...")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 提交所有任务
            future_to_batch = {
                executor.submit(_process_batch, b_idx, b_data): b_idx 
                for b_idx, b_data in all_batches
            }
            
            for future in as_completed(future_to_batch):
                b_idx = future_to_batch[future]
                try:
                    idx, content = future.result()
                    translated_results[idx] = content
                    completed_count += 1
                    
                    # 进度日志
                    if completed_count % 5 == 0 or completed_count == total_batches:
                         progress = (completed_count / total_batches) * 100
                         log_task(task_id, f"进度: {progress:.1f}% ({completed_count}/{total_batches})")
                         
                except Exception as exc:
                    log_task(task_id, f"❌ 批次 {b_idx} 异常: {exc}")
                    translated_results[b_idx] = "\n\n".join(all_batches[b_idx][1])

        # 检查并修复空值
        if any(r is None for r in translated_results):
             log_task(task_id, "⚠️ 警告：部分批次数据丢失，正在修复...")
             for i, res in enumerate(translated_results):
                 if res is None:
                     translated_results[i] = "\n\n".join(all_batches[i][1])

        # 保存文件
        dir_name, base_name = os.path.split(file_path)
        name_part, ext_part = os.path.splitext(base_name)
        new_filename = f"{name_part}.chi{ext_part}"
        new_path = os.path.join(dir_name, new_filename)

        log_task(task_id, "翻译完成，正在拼接写入文件...")

        final_content = "\n\n".join(translated_results)
        with open(new_path, 'w', encoding='utf-8') as f:
            f.write(final_content)

        log_task(task_id, f"✅ 全部处理完毕！文件已保存为: {new_filename}")
        task_store[task_id]['status'] = 'done'

    except Exception as e:
        log_task(task_id, f"💀 致命错误: {str(e)}")
        task_store[task_id]['status'] = 'error'

def upload_to_pixhost(file_path):
    upload_url = "https://api.pixhost.to/images"
    try:
        with open(file_path, 'rb') as f:
            files = {'img': f}
            data = {"content_type": "0", "max_th_size": "400"}
            headers = {"Accept": "application/json"}
            
            response = requests.post(upload_url, files=files, data=data, headers=headers, timeout=60)
            
            if response.status_code == 200:
                res_json = response.json()
                th_url = res_json.get('th_url')
                if th_url:
                    th_url = th_url.replace('\\/', '/')
                    full_url = th_url.replace('/thumbs/', '/images/')
                    full_url = full_url.replace('https://t', 'https://img')
                    return f"[img]{full_url}[/img]"
            else:
                print(f"Pixhost Error: {response.text}")
    except Exception as e:
        print(f"Upload exception for {file_path}: {e}")
    return None

def generate_screenshots(video_path, output_base_path, mode, quality):
    temp_dir = "/tmp/temp_thumbs_processing"
    settings_grid = {'small': (320, 15), 'medium': (640, 5), 'large': (1280, 2)}
    settings_full = {'medium': (1920, 1, ["-qmin", "1", "-qmax", "1"]), 'large': (0, 1, ["-qmin", "1", "-qmax", "1"])}
    generated_images = []

    try:
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)
        duration = get_video_duration(video_path)
        if duration < 60: return "success", "视频太短，跳过截图"
        
        result_file = None; preview_data = None
        
        if mode == 'grid':
            width, q_val = settings_grid.get(quality, (640, 5))
            output_jpg = output_base_path + "_Thumb.jpg"
            blank_img = os.path.join(temp_dir, "blank.jpg")
            subprocess.run(["ffmpeg", "-f", "lavfi", "-i", f"color=c=black:s={width}x{int(width*9/16)}", "-frames:v", "1", "-y", blank_img], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            interval = duration / 16
            for i in range(16):
                timestamp = (i * interval) + (interval / 2)
                img_path = os.path.join(temp_dir, f"img_{i:02d}.jpg")
                cmd = ["ffmpeg", "-ss", str(timestamp), "-y", "-i", video_path, "-frames:v", "1", "-qscale:v", str(q_val), "-vf", f"scale={width}:-1", img_path]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if not os.path.exists(img_path) or os.path.getsize(img_path) == 0: shutil.copy(blank_img, img_path)
            cmd_tile = ["ffmpeg", "-y", "-i", os.path.join(temp_dir, "img_%02d.jpg"), "-vf", "tile=4x4:padding=5:color=white", "-qscale:v", str(q_val), output_jpg]
            subprocess.run(cmd_tile, capture_output=True)
            if os.path.exists(output_jpg): 
                result_file = output_jpg; preview_data = output_jpg
                generated_images.append(output_jpg) 
            else: return "error", "拼图生成失败"
        else:
            target_width, q_val, extra_flags = settings_full.get(quality, (1920, 1, []))
            image_list = []
            steps = 7
            for i in range(1, steps):
                timestamp = duration * (i / steps)
                img_path = f"{output_base_path}_shot_{i}.jpg"
                cmd = ["ffmpeg", "-ss", str(timestamp), "-y", "-i", video_path, "-frames:v", "1", "-qscale:v", str(q_val)]
                cmd.extend(extra_flags)
                if target_width > 0: cmd.extend(["-vf", f"scale={target_width}:-1"])
                cmd.append(img_path)
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(img_path) and os.path.getsize(img_path) > 0: 
                    image_list.append(img_path)
                    generated_images.append(img_path) 
            
            zip_path = output_base_path + "_Screenshots.zip"
            if image_list:
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for img in image_list: zipf.write(img, os.path.basename(img))
                result_file = zip_path; preview_data = image_list[0] if len(image_list) > 0 else None
            else: return "error", "截图失败"
        
        return "success", {"file": result_file, "preview": preview_data, "images": generated_images}
    except Exception as e: return "error", str(e)
    finally:
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)

def background_process(tracker_url, is_private, comment, piece_size, full_source_path, output_folder, task_id, shot_mode, shot_quality):
    log_task(task_id, f"启动做种任务...")
    task_store[task_id] = {'status': 'running', 'msg': '初始化...', 'files': {}, 'bbcode': ''}
    try:
        if not os.path.exists(output_folder): os.makedirs(output_folder, exist_ok=True)
        base_name = os.path.basename(full_source_path.rstrip('/')) if os.path.isdir(full_source_path) else os.path.basename(full_source_path)
        f_torrent = os.path.join(output_folder, f"{base_name}.torrent")
        f_info = os.path.join(output_folder, f"{base_name}_MediaInfo.txt")
        f_shot_base = os.path.join(output_folder, base_name)
        
        for f in [f_torrent, f_info, f_shot_base + "_Screenshots.zip"]:
            if os.path.exists(f): 
                try: os.remove(f)
                except: pass
        if os.path.exists(output_folder):
            for fname in os.listdir(output_folder):
                if fname.startswith(base_name) and fname.lower().endswith(('.jpg', '.jpeg')):
                    try: os.remove(os.path.join(output_folder, fname))
                    except: pass

        task_store[task_id]['msg'] = '正在生成种子...'
        cmd = ["mktorrent", "-v", "-l", piece_size, "-a", tracker_url]
        if is_private: cmd.append("-p")
        if comment: cmd.extend(["-c", comment])
        cmd.extend(["-o", f_torrent])
        cmd.append(full_source_path)
        subprocess.run(cmd, capture_output=True)
        if os.path.exists(f_torrent): task_store[task_id]['files']['torrent'] = f_torrent

        task_store[task_id]['msg'] = '扫描视频文件...'
        target_media_file = find_largest_file(full_source_path)
        if target_media_file:
            task_store[task_id]['msg'] = '生成 MediaInfo...'
            subprocess.run(["mediainfo", target_media_file, f"--LogFile={f_info}"], stdout=subprocess.DEVNULL)
            if os.path.exists(f_info): task_store[task_id]['files']['info'] = f_info
            
            task_store[task_id]['msg'] = f'正在截图 ({shot_mode}/{shot_quality})...'
            status, res = generate_screenshots(target_media_file, f_shot_base, shot_mode, shot_quality)
            if status == "success":
                 if res.get('file'): task_store[task_id]['files']['shot_download'] = res['file']
                 if res.get('preview'): task_store[task_id]['files']['shot_preview'] = res['preview']
                 
                 image_files = res.get('images', [])
                 if image_files:
                     task_store[task_id]['msg'] = f'正在上传 {len(image_files)} 张图片到 Pixhost...'
                     bbcode_lines = []
                     for idx, img_p in enumerate(image_files):
                         code = upload_to_pixhost(img_p)
                         if code:
                             bbcode_lines.append(code)
                     task_store[task_id]['bbcode'] = "\n".join(bbcode_lines)

                 task_store[task_id]['msg'] = '✅ 全部成功'
            else: task_store[task_id]['msg'] = f"⚠️ 截图失败: {res}"
        else: task_store[task_id]['msg'] = '✅ 完成 (无视频)'
        task_store[task_id]['status'] = 'done'
    except Exception as e:
        task_store[task_id]['status'] = 'error'
        task_store[task_id]['msg'] = f"系统错误: {str(e)}"

# === 字幕提取逻辑 ===
def extract_subtitle_streams(video_path):
    try:
        cmd_probe = ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream=index:stream_tags=language,title:stream=codec_name", "-of", "json", video_path]
        result = subprocess.run(cmd_probe, capture_output=True, text=True)
        try: data = json.loads(result.stdout)
        except: return False, "无法读取媒体信息"
        streams = data.get('streams', [])
        if not streams: return False, "未检测到字幕流"
        count = 0
        base_name = os.path.splitext(video_path)[0]
        for stream in streams:
            idx = stream.get('index'); codec = stream.get('codec_name', 'srt'); tags = stream.get('tags', {}); lang = tags.get('language', 'und')
            ext = 'srt'
            if 'ass' in codec: ext = 'ass'
            elif 'pgs' in codec: ext = 'sup'
            out_name = f"{base_name}.{lang}.{idx}.{ext}"
            subprocess.run(["ffmpeg", "-y", "-i", video_path, "-map", f"0:{idx}", "-c", "copy", out_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(out_name): count += 1
        return True, f"提取 {count} 条字幕"
    except Exception as e: return False, str(e)

# ================= 路由 =================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USERNAME and request.form['password'] == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        flash('错误', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/api/status')
@login_required
def check_status():
    task_id = request.args.get('task_id')
    if task_id and task_id in task_store: return jsonify(task_store[task_id])
    return jsonify({'status': 'unknown'})

@app.route('/api/list_files', methods=['POST'])
@login_required
def list_files():
    try:
        rel_path = request.json.get('path', '').strip()
        full_path = get_safe_path(rel_path)
        if not os.path.exists(full_path): return jsonify({'success': False, 'msg': '路径不存在'})
        file_list = []
        current_rel = os.path.relpath(full_path, BASE_DIR)
        if current_rel == '.': current_rel = ""
        if os.path.isfile(full_path):
            file_list.append({'name': os.path.basename(full_path), 'type': 'file', 'size': os.path.getsize(full_path), 'is_txt': full_path.endswith('.txt')})
        else:
            for item in sorted(os.listdir(full_path)):
                if item.startswith('.'): continue
                item_path = os.path.join(full_path, item)
                is_dir = os.path.isdir(item_path)
                file_list.append({
                    'name': item,
                    'type': 'dir' if is_dir else 'file',
                    'size': os.path.getsize(item_path) if not is_dir else 0,
                    'is_txt': item.lower().endswith(('.txt', '.nfo', '.md'))
                })
        file_list.sort(key=lambda x: (x['type'] != 'dir', x['name']))
        return jsonify({'success': True, 'files': file_list, 'current_path': current_rel})
    except Exception as e: return jsonify({'success': False, 'msg': str(e)})

@app.route('/api/file_op', methods=['POST'])
@login_required
def file_op():
    try:
        data = request.json
        op_type = data.get('type')
        current_path = data.get('current_path', '')
        
        user_key = data.get('api_key') 
        if user_key: 
            global DEEPSEEK_API_KEY
            DEEPSEEK_API_KEY = user_key

        if op_type == 'delete':
            target = data.get('filename')
            full = get_safe_path(os.path.join(current_path, target))
            if os.path.isdir(full): shutil.rmtree(full)
            else: os.remove(full)
            return jsonify({'success': True})
        
        elif op_type == 'rename':
            old_name = data.get('old_name'); new_name = data.get('new_name')
            if not new_name: return jsonify({'success': False, 'msg': '新文件名不能为空'})
            old_full = get_safe_path(os.path.join(current_path, old_name))
            new_full = get_safe_path(os.path.join(current_path, new_name))
            os.rename(old_full, new_full)
            return jsonify({'success': True})
        
        elif op_type == 'create_txt':
            filename = data.get('filename')
            if not filename: return jsonify({'success': False, 'msg': '文件名不能为空'})
            if '.' not in filename: filename += '.txt'
            full_target = get_safe_path(os.path.join(current_path, filename))
            if os.path.exists(full_target): return jsonify({'success': False, 'msg': '文件已存在'})
            with open(full_target, 'w', encoding='utf-8') as f: f.write("")
            return jsonify({'success': True})
        
        elif op_type == 'read_txt':
            filename = data.get('filename')
            full_target = get_safe_path(os.path.join(current_path, filename))
            with open(full_target, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
            return jsonify({'success': True, 'content': content})
        
        elif op_type == 'save_txt':
            filename = data.get('filename'); content = data.get('content')
            full_target = get_safe_path(os.path.join(current_path, filename))
            with open(full_target, 'w', encoding='utf-8') as f: f.write(content)
            return jsonify({'success': True})

        elif op_type == 'extract_subs':
            filename = data.get('filename')
            full_target = get_safe_path(os.path.join(current_path, filename))
            success, msg = extract_subtitle_streams(full_target)
            return jsonify({'success': success, 'msg': msg})

        # === 核心修改：翻译任务 ===
        elif op_type == 'translate_sub':
            filename = data.get('filename')
            full_target = get_safe_path(os.path.join(current_path, filename))
            
            if not os.path.exists(full_target):
                return jsonify({'success': False, 'msg': '文件不存在'})
            
            # 生成任务 ID
            task_id = str(uuid.uuid4())[:8]
            
            # 初始化任务状态
            task_store[task_id] = {
                'status': 'running', 
                'msg': '准备开始翻译...', 
                'logs': [], # 专门用于前端展示日志
                'type': 'translation'
            }

            # 启动后台线程
            t = threading.Thread(target=background_translate, args=(task_id, full_target))
            t.start()
            
            return jsonify({
                'success': True, 
                'task_id': task_id, 
                'msg': '任务已启动，请查看日志窗口。'
            })
        
        elif op_type == 'batch_delete':
            filenames = data.get('filenames', [])
            if not filenames: return jsonify({'success': False, 'msg': '未选择文件'})
            for name in filenames:
                try:
                    full_target = get_safe_path(os.path.join(current_path, name))
                    if os.path.exists(full_target):
                        if os.path.isdir(full_target): shutil.rmtree(full_target)
                        else: os.remove(full_target)
                except Exception as e: print(f"删除失败 {name}: {e}")
            return jsonify({'success': True})
        
        elif op_type == 'batch_move':
            filenames = data.get('filenames', [])
            dest_rel_path = data.get('destination', '').strip()
            if not filenames: return jsonify({'success': False, 'msg': '未选择文件'})
            if not dest_rel_path: return jsonify({'success': False, 'msg': '目标路径不能为空'})
            dest_full = get_safe_path(dest_rel_path)
            if not os.path.exists(dest_full) or not os.path.isdir(dest_full):
                 try: os.makedirs(dest_full, exist_ok=True)
                 except: return jsonify({'success': False, 'msg': '目标文件夹不存在且无法创建'})
            success_count = 0
            for name in filenames:
                try:
                    src_full = get_safe_path(os.path.join(current_path, name))
                    if src_full == dest_full: continue 
                    shutil.move(src_full, dest_full)
                    success_count += 1
                except Exception as e: print(f"移动失败 {name}: {e}")
            return jsonify({'success': True, 'msg': f"成功移动 {success_count} 个项目"})
        
        return jsonify({'success': False, 'msg': '未知操作'})
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)})

@app.route('/api/submit_task', methods=['POST'])
@login_required
def submit_task():
    try:
        rel_path = request.form.get('path', '').strip()
        tracker_url = request.form.get('tracker', '').strip()
        save_default = request.form.get('save_default')
        is_private = request.form.get('private')
        comment = request.form.get('comment', '').strip()
        piece_size = request.form.get('piece_size', '24')
        shot_mode = request.form.get('shot_mode', 'grid')
        shot_quality = request.form.get('shot_quality', 'medium')

        if save_default and tracker_url: save_default_tracker(tracker_url)
        full_source_path = get_safe_path(rel_path)
        
        if not os.path.exists(full_source_path):
            return jsonify({'success': False, 'msg': f"路径不存在: {full_source_path}"})

        output_folder = os.path.join(full_source_path, "torrent") if os.path.isdir(full_source_path) else os.path.join(os.path.dirname(full_source_path), "torrent")
        task_id = str(uuid.uuid4())[:8]
        
        t = threading.Thread(target=background_process, args=(
            tracker_url, is_private, comment, piece_size, 
            full_source_path, output_folder, task_id,
            shot_mode, shot_quality
        ))
        t.start()
        return jsonify({'success': True, 'task_id': task_id})
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)})

@app.route('/', methods=['GET'])
@login_required
def index():
    current_tracker = load_default_tracker()
    task_id = request.args.get('task_id')
    
    download_link = None; mediainfo_link = None; shot_download_link = None; shot_preview_link = None  
    mediainfo_content = ""; bbcode_content = ""; error_msg = None
    
    if task_id and task_id in task_store:
        task_data = task_store[task_id]
        if task_data['status'] == 'done':
            if "失败" in task_data['msg']: error_msg = task_data['msg']
            files = task_data.get('files', {})
            if 'torrent' in files: download_link = files['torrent']
            if 'info' in files and os.path.exists(files['info']):
                mediainfo_link = files['info']
                try: 
                    with open(files['info'], 'r') as f: mediainfo_content = f.read()
                except: pass
            if 'shot_download' in files: shot_download_link = files['shot_download']
            
            img_path = None
            if 'shot_preview' in files:
                p = files['shot_preview']
                if isinstance(p, str) and os.path.exists(p): img_path = p
                elif isinstance(p, list) and len(p) > 0 and os.path.exists(p[0]): img_path = p[0]
            if img_path: shot_preview_link = url_for('view_image', path=img_path)
            
            bbcode_content = task_data.get('bbcode', '')

    return render_template('index.html', 
                           default_tracker=current_tracker,
                           download_path=download_link,
                           mediainfo_link=mediainfo_link,
                           shot_download_link=shot_download_link,
                           shot_preview_link=shot_preview_link,
                           mediainfo_content=mediainfo_content,
                           bbcode_content=bbcode_content, 
                           error_msg=error_msg)

@app.route('/download')
@login_required
def download_file():
    file_path = request.args.get('file')
    if file_path:
        decoded = unquote(file_path)
        if os.path.exists(decoded): return send_file(decoded, as_attachment=True)
    return "文件未找到"

@app.route('/view_image')
@login_required
def view_image():
    file_path = request.args.get('path')
    if not file_path: return "No path provided", 400
    decoded_path = unquote_plus(file_path)
    if os.path.exists(decoded_path): return send_file(decoded_path, mimetype='image/jpeg')
    return "Image not found", 404

if __name__ == '__main__':
    app.config['JSON_AS_ASCII'] = False
    app.run(host='0.0.0.0', port=5000, threaded=True)