import os
import base64
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk, messagebox
from http import HTTPStatus
import dashscope
from dashscope import MultiModalConversation, Generation
from dashscope.files import Files
import threading
import time
import numpy as np  # 修复：添加视频压缩必需的numpy导入

# ====================== 核心配置 ======================
API_KEY = "sk-6d02c1bd446f4e2588725bb590c61dfa"  # 已替换为你提供的密钥
MULTI_MODAL_MODEL = "qwen3.5-plus"
DOC_MODEL = "qwen-long"  # 文档理解专用模型

# 地域配置（北京地域）
dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

# 支持格式
SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.mov', '.avi', '.flv', '.mkv']
SUPPORTED_DOC_FORMATS = ['.pdf', '.docx', '.doc', '.txt', '.md', '.xls', '.xlsx']  # 文档格式
ALL_SUPPORTED_FORMATS = SUPPORTED_IMAGE_FORMATS + SUPPORTED_VIDEO_FORMATS + SUPPORTED_DOC_FORMATS
DEFAULT_FPS = 2  # 视频默认抽帧频率

# 文件大小限制（修复：统一配置，避免矛盾）
MAX_RAW_SIZE_MB = 30    # 原文件最大支持30MB（API实际限制）
MAX_B64_SIZE_MB = 20    # base64编码后≤20MB（对齐API官方上限）
enable_thinking = False # 思考模式默认关闭

# ====================== 全局变量 ======================
selected_file_path = ""
file_type = ""  # image/video/doc
file_id = ""    # 文档fileid
root = None
chat_text = None
input_text = None
upload_btn = None
cancel_file_btn = None
thinking_btn = None
send_btn = None
status_label = None

# ====================== 文档上传获取FileID（核心修复） ======================
def upload_file_get_fileid(file_path):
    """
    上传文件到百炼并获取fileid
    :param file_path: 文件路径
    :return: fileid字符串
    """
    try:
        show_status("🔄 正在上传文档获取FileID...", "info")
        
        # 调用文件上传接口
        response = Files.upload(
            file_path=file_path,
            api_key=API_KEY
        )
        
        # 修复Bug2：正确获取file_id（属性访问而非字典访问）
        if response.status_code == 200 and hasattr(response, 'output') and hasattr(response.output, 'file_id'):
            fileid = response.output.file_id  # 修复：response.output.file_id 而非 ['file_id']
            show_status(f"✅ 文档上传成功，FileID：{fileid}", "info")
            return fileid
        else:
            raise Exception(f"获取FileID失败：{response}")
    
    except Exception as e:
        raise Exception(f"文档上传失败：{str(e)}")

# ====================== 核心压缩函数 ======================
def compress_image(file_path, target_b64_size_mb=20):
    """智能压缩图片"""
    try:
        show_status("🔄 正在压缩图片...（大文件可能需要几秒）", "info")
        # 导入压缩依赖（延迟导入，避免启动报错）
        from PIL import Image, ImageOps
        import io
        
        img = Image.open(file_path)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        quality = 95
        max_width = 1920
        max_height = 1080
        
        img = ImageOps.exif_transpose(img)
        width, height = img.size
        if width > max_width or height > max_height:
            scale = min(max_width/width, max_height/height)
            new_size = (int(width*scale), int(height*scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        while True:
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality, optimize=True)
            raw_data = buf.getvalue()
            b64_size = len(base64.b64encode(raw_data)) / (1024*1024)
            
            if b64_size <= target_b64_size_mb or quality <= 10:
                break
            quality -= 5
        
        b64_data = base64.b64encode(raw_data).decode('utf-8')
        prefix = f"data:image/jpeg;base64,"
        
        show_status(f"✅ 图片压缩完成：质量{quality}%，base64大小{b64_size:.1f}MB", "info")
        return prefix + b64_data
    
    except Exception as e:
        raise Exception(f"图片压缩失败：{str(e)}")

def compress_video(file_path, target_fps=2, target_b64_size_mb=20):
    """智能压缩视频"""
    try:
        show_status("🔄 正在压缩视频...（大文件可能需要几十秒）", "info")
        # 导入压缩依赖（延迟导入，避免启动报错）
        import cv2
        import io
        
        temp_file = f"temp_compressed_{int(time.time())}.mp4"
        
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            raise Exception("无法打开视频文件")
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        scale = 1.0
        max_width = 1280
        if width > max_width:
            scale = max_width / width
            width = int(width * scale)
            height = int(height * scale)
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_file, fourcc, target_fps, (width, height))
        
        frame_count = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % int(fps/target_fps) == 0:
                if scale < 1.0:
                    frame = cv2.resize(frame, (width, height))
                out.write(frame)
            frame_count += 1
        
        # 释放资源
        cap.release()
        out.release()
        cv2.destroyAllWindows()
        
        # 读取压缩后的视频
        with open(temp_file, 'rb') as f:
            video_data = f.read()
        b64_data = base64.b64encode(video_data).decode('utf-8')
        
        # 删除临时文件
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        final_b64_size = len(b64_data) / (1024*1024)
        prefix = f"data:video/mp4;base64,"
        
        show_status(f"✅ 视频压缩完成：帧率{target_fps}fps，分辨率{width}x{height}，base64大小{final_b64_size:.1f}MB", "info")
        return prefix + b64_data
    
    except Exception as e:
        # 异常时清理临时文件
        if 'temp_file' in locals() and os.path.exists(temp_file):
            os.remove(temp_file)
        # 释放资源
        if 'cap' in locals():
            cap.release()
        if 'out' in locals():
            out.release()
        cv2.destroyAllWindows()
        raise Exception(f"视频压缩失败：{str(e)}")

# ====================== 基础工具函数 ======================
def init_dashscope():
    """初始化API"""
    try:
        if not API_KEY or len(API_KEY) < 10 or not API_KEY.startswith("sk-"):
            show_status("❌ API_KEY格式错误！请检查是否为以sk-开头的有效密钥", "error")
            return False
        dashscope.api_key = API_KEY
        return True
    except Exception as e:
        show_status(f"❌ 初始化失败：{str(e)[:100]}", "error")
        return False

def select_file():
    """选择文件（支持图片/视频/文档）"""
    global selected_file_path, file_type, file_id
    
    # 修复：正确构造文件类型列表
    file_types = [
        ("所有支持的文件", " ".join([f"*{ext}" for ext in ALL_SUPPORTED_FORMATS])),
        ("图片文件", " ".join([f"*{ext}" for ext in SUPPORTED_IMAGE_FORMATS])),
        ("视频文件", " ".join([f"*{ext}" for ext in SUPPORTED_VIDEO_FORMATS])),
        ("文档文件", " ".join([f"*{ext}" for ext in SUPPORTED_DOC_FORMATS])),
        ("所有文件", "*.*")
    ]
    
    file_path = filedialog.askopenfilename(
        title=f"选择图片/视频/文档文件（最大{MAX_RAW_SIZE_MB}MB）",  # 修复：使用配置变量而非硬编码30
        filetypes=file_types
    )
    
    if not file_path or not os.path.exists(file_path):
        show_status("ℹ️ 已取消文件选择", "info")
        return

    # 检查文件大小
    raw_size = os.path.getsize(file_path) / (1024 * 1024)
    if raw_size > MAX_RAW_SIZE_MB:
        show_status(f"❌ 文件过大！需≤{MAX_RAW_SIZE_MB}MB，当前{raw_size:.1f}MB", "error")
        return

    # 判断文件类型
    file_ext = os.path.splitext(file_path)[1].lower()
    if file_ext in SUPPORTED_IMAGE_FORMATS:
        file_type = "image"
        file_id = ""  # 图片/视频不需要fileid
    elif file_ext in SUPPORTED_VIDEO_FORMATS:
        file_type = "video"
        file_id = ""
    elif file_ext in SUPPORTED_DOC_FORMATS:
        file_type = "doc"
        file_id = ""  # 先清空，上传时再获取
    else:
        show_status(f"❌ 不支持的格式：{file_ext}", "error")
        return

    # 更新全局变量
    selected_file_path = file_path
    
    # 显示选择成功信息
    show_status(f"✅ 已选择【{file_type}】：{os.path.basename(file_path)}（大小{raw_size:.1f}MB）", "info")
    
    # 启用取消按钮
    cancel_file_btn.config(state=tk.NORMAL)

def cancel_file_selection():
    """取消文件选择（修复：重置所有相关变量）"""
    global selected_file_path, file_type, file_id
    
    # 清空所有相关变量
    selected_file_path = ""
    file_type = ""
    file_id = ""
    
    # 禁用取消按钮
    cancel_file_btn.config(state=tk.DISABLED)
    
    # 显示取消成功
    show_status("✅ 已取消文件选择", "info")

def toggle_thinking():
    """切换深度思考模式"""
    global enable_thinking
    enable_thinking = not enable_thinking
    if enable_thinking:
        thinking_btn.config(
            bg="#e3f2fd",
            fg="#007bff",
            text="深度思考(开启)"
        )
        show_status("✅ 已开启深度思考，将显示模型推理过程", "info")
    else:
        thinking_btn.config(
            bg="white",
            fg="#333333",
            text="深度思考(关闭)"
        )
        show_status("✅ 已关闭深度思考，仅显示最终回复", "info")

def show_status(msg, msg_type="info"):
    """线程安全的状态栏更新"""
    def update():
        if msg_type == "error":
            status_label.config(text=msg, foreground="red")
        elif msg_type == "warning":
            status_label.config(text=msg, foreground="orange")
        else:
            status_label.config(text=msg, foreground="#007bff")
        root.update_idletasks()
    root.after(0, update)

def insert_chat(sender, content=""):
    """插入聊天消息（修复：统一换行符格式）"""
    def update():
        chat_text.config(state=tk.NORMAL)
        if sender == "user":
            chat_text.insert(tk.END, f"\n👤 你：{content}\n", "user")
        elif sender == "assistant":
            chat_text.insert(tk.END, f"\n🤖 助手：{content}", "assistant")  # 修复：移除多余换行
        elif sender == "thinking":
            chat_text.insert(tk.END, f"\n💡 思考：{content}\n", "thinking")
        chat_text.config(state=tk.DISABLED)
        chat_text.see(tk.END)
        root.update_idletasks()
    root.after(0, update)

def append_chat(sender, content):
    """追加聊天内容"""
    def update():
        chat_text.config(state=tk.NORMAL)
        if sender == "assistant":
            chat_text.insert(tk.END, content, "assistant")
        elif sender == "thinking":
            chat_text.insert(tk.END, content, "thinking")
        chat_text.config(state=tk.DISABLED)
        chat_text.see(tk.END)
        root.update_idletasks()
    root.after(0, update)

def file_to_base64_with_compress(file_path):
    """文件转base64（自动压缩）"""
    try:
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # 检查压缩依赖
        compress_support = False
        try:
            import cv2
            import numpy as np  # 修复：显式检查numpy
            from PIL import Image
            compress_support = True
        except ImportError:
            compress_support = False
        
        if file_ext in SUPPORTED_IMAGE_FORMATS and compress_support:
            return compress_image(file_path, MAX_B64_SIZE_MB)
        elif file_ext in SUPPORTED_VIDEO_FORMATS and compress_support:
            return compress_video(file_path, DEFAULT_FPS, MAX_B64_SIZE_MB)
        else:
            if not compress_support:
                show_status("⚠️ 未安装压缩依赖（pillow/opencv-python/numpy），使用原始编码", "warning")
            
            with open(file_path, 'rb') as f:
                content = f.read()
            b64_data = base64.b64encode(content).decode('utf-8')
            b64_size = len(b64_data) / (1024*1024)
            
            if b64_size > MAX_B64_SIZE_MB:
                raise Exception(f"base64编码后超{MAX_B64_SIZE_MB}MB（当前{b64_size:.1f}MB），请安装压缩依赖或缩小文件")
            
            if file_ext in SUPPORTED_IMAGE_FORMATS:
                img_type = "jpeg" if file_ext in ['.jpg', '.jpeg'] else file_ext[1:]
                prefix = f"data:image/{img_type};base64,"
            elif file_ext in SUPPORTED_VIDEO_FORMATS:
                prefix = f"data:video/{file_ext[1:]};base64,"
            else:
                raise ValueError(f"不支持的格式：{file_ext}")
            
            return prefix + b64_data
    
    except Exception as e:
        raise Exception(f"文件处理失败：{str(e)}")

# ====================== 核心请求处理（修复FileID使用规范） ======================
def process_request(user_prompt):
    """处理请求（支持图片/视频/文档）"""
    global file_id
    api_error = False
    has_content = False
    is_answering = False

    try:
        # 初始化消息
        if file_type == "doc":
            # 修复Bug1：FileID使用规范（放在user的content数组中）
            messages = [
                {'role': 'system', 'content': '你是一个乐于助人的助手，擅长文档理解和分析'},
                {
                    'role': 'user',
                    'content': [
                        {'text': user_prompt},  # 用户问题
                        # FileID将在获取后添加到这里
                    ]
                }
            ]
            
            # 如果还没有fileid，先上传获取
            if not file_id and selected_file_path:
                try:
                    file_id = upload_file_get_fileid(selected_file_path)
                    # 修复：将FileID添加到user的content数组中（正确位置）
                    messages[1]['content'].append({'file': f'fileid://{file_id}'})
                except Exception as e:
                    insert_chat("assistant", f"❌ {str(e)}")
                    show_status("❌ 文档处理失败", "error")
                    api_error = True
                    # 重置状态
                    file_id = ""
                    return
        else:
            # 图片/视频/纯文本：多模态模式
            messages = [{"role": "user", "content": []}]
            
            # 处理图片/视频
            if selected_file_path and file_type in ["image", "video"]:
                try:
                    file_b64 = file_to_base64_with_compress(selected_file_path)
                    if file_type == "image":
                        messages[0]["content"].append({"image": file_b64})
                        show_status("🔄 正在分析图片...")
                    elif file_type == "video":
                        messages[0]["content"].append({"video": file_b64, "fps": DEFAULT_FPS})
                        show_status(f"🔄 正在分析视频（fps={DEFAULT_FPS}）...")
                except Exception as e:
                    insert_chat("assistant", f"❌ {str(e)}")
                    show_status("❌ 文件处理失败", "error")
                    api_error = True
                    return
            
            # 添加用户提示词
            messages[0]["content"].append({"text": user_prompt})
        
        # 调用对应的API
        if file_type == "doc":
            # 文档理解调用qwen-long模型
            show_status("🔄 正在分析文档...")
            response = Generation.call(
                # 修复Bug8：移除重复的api_key参数（全局已设置）
                model=DOC_MODEL,
                messages=messages,
                result_format='message',
                stream=False
            )
            
            # 处理文档响应
            if response.status_code == HTTPStatus.OK:
                if hasattr(response, 'output') and hasattr(response.output, 'choices'):
                    choice = response.output.choices[0]
                    if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
                        reply_content = choice.message.content
                        insert_chat("assistant", reply_content)
                        has_content = True
            else:
                code = getattr(response, 'code', '未知错误')
                msg = getattr(response, 'message', 'API异常')
                insert_chat("assistant", f"❌ API错误：{code} - {msg}")
                if "InvalidApiKey" in str(code):
                    append_chat("assistant", "\n💡 请检查你的API密钥是否正确！")
                show_status("❌ 请求失败", "error")
                api_error = True
                
        else:
            # 图片/视频/纯文本调用qwen3.5-plus模型
            if not selected_file_path:
                show_status("🔄 正在进行纯文本对话...")
            responses = MultiModalConversation.call(
                model=MULTI_MODAL_MODEL,
                messages=messages,
                stream=True,
                enable_thinking=enable_thinking,
                thinking_budget=81920,
                incremental_output=True
            )
        
            # 处理流式响应
            if enable_thinking and file_type != "doc":
                insert_chat("thinking", "="*20 + "思考过程" + "="*20)
        
            # 处理多模态响应
            for chunk in responses:
                if not hasattr(chunk, 'status_code') or chunk.status_code != HTTPStatus.OK:
                    code = getattr(chunk, 'code', '未知错误')
                    msg = getattr(chunk, 'message', 'API异常')
                    insert_chat("assistant", f"\n❌ API错误：{code} - {msg}")
                    if "InvalidApiKey" in code:
                        append_chat("assistant", "\n💡 请检查你的API密钥是否正确！")
                    show_status("❌ 请求失败", "error")
                    api_error = True
                    break

                if (not hasattr(chunk, 'output') or 
                    not hasattr(chunk.output, 'choices') or 
                    len(chunk.output.choices) == 0):
                    continue

                msg = chunk.output.choices[0].message
                reasoning_chunk = msg.get("reasoning_content", "")
                content = msg.content if hasattr(msg, 'content') else []

                if content == [] and reasoning_chunk == "":
                    continue

                # 思考过程
                if enable_thinking and reasoning_chunk and content == []:
                    append_chat("thinking", reasoning_chunk)
                    has_content = True
                # 最终回复
                elif content != []:
                    if not is_answering:
                        insert_chat("assistant", "")
                        is_answering = True

                    if isinstance(content, list) and len(content) > 0:
                        text = content[0].get('text', '')
                        if text:
                            append_chat("assistant", text)
                            has_content = True
        
        # 如果没有收到有效回复
        if not has_content and not api_error:
            show_status("⚠️ 未获取到有效响应", "warning")
            insert_chat("assistant", "⚠️ 未获取到有效回复")
        
    except Exception as e:
        insert_chat("assistant", f"\n❌ 处理异常：{str(e)}")
        show_status("❌ 程序异常", "error")
        api_error = True
    finally:
        if not api_error:
            if has_content:
                if selected_file_path:
                    show_status(f"✅ {file_type}分析完成", "info")
                else:
                    show_status("✅ 纯文本对话完成", "info")
            else:
                show_status("⚠️ 未获取到有效响应", "warning")
        # 恢复发送按钮状态
        root.after(0, lambda: send_btn.config(state=tk.NORMAL))

def send_message(event=None):
    """发送消息（修复：处理回车事件）"""
    # 过滤Shift+Enter等组合键
    if event and (event.state & 0x0001 or not event.char == '\r'):
        return
    
    if not init_dashscope():
        return
    
    prompt = input_text.get("1.0", tk.END).strip()
    if not prompt:
        show_status("❌ 请输入对话/分析内容", "error")
        return

    # 禁用发送按钮，防止重复发送
    send_btn.config(state=tk.DISABLED)
    
    # 清空输入框
    input_text.delete("1.0", tk.END)

    # 显示用户消息
    user_msg = prompt
    if selected_file_path:
        user_msg = f"{prompt}\n（已上传：{os.path.basename(selected_file_path)}）"
    insert_chat("user", user_msg)

    # 启动处理线程
    threading.Thread(target=process_request, args=(prompt,), daemon=True).start()

    return "break"  # 阻止默认回车行为

# ====================== UI构建 ======================
def create_gui():
    global root, chat_text, input_text, upload_btn, cancel_file_btn, thinking_btn, send_btn, status_label

    root = tk.Tk()
    root.title(f"多模态对话工具（支持图片/视频/文档+{MAX_RAW_SIZE_MB}MB超大文件）")  # 修复：使用配置变量
    root.geometry("900x800")
    root.resizable(True, True)

    # 字体配置
    font_default = ("微软雅黑", 10)
    font_chat = ("微软雅黑", 11)

    # 顶部标题
    ttk.Label(root, text=f"多模态对话工具（支持图片/视频/文档+{MAX_RAW_SIZE_MB}MB超大文件）", font=("微软雅黑", 12, "bold")).pack(pady=8)
    ttk.Label(root, text=f"支持格式：图片/视频/PDF/Word/TXT等 | API密钥：{API_KEY[:8]}****", font=("微软雅黑", 8), foreground="gray").pack(pady=0)

    # 聊天显示区
    chat_frame = ttk.Frame(root, padding=5)
    chat_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
    chat_text = scrolledtext.ScrolledText(
        chat_frame,
        font=font_chat,
        wrap=tk.WORD,
        state=tk.DISABLED,
        bg="#f5f5f5"
    )
    chat_text.pack(fill=tk.BOTH, expand=True)
    
    # 文字样式配置
    chat_text.tag_configure("user", justify=tk.RIGHT, foreground="#007bff", spacing1=8, spacing3=8)
    chat_text.tag_configure("assistant", justify=tk.LEFT, foreground="#000000", spacing1=8, spacing3=8)
    chat_text.tag_configure("thinking", justify=tk.LEFT, foreground="#666666", spacing1=2, spacing3=2)

    # 状态栏
    status_label = ttk.Label(root, text=f"✅ 就绪，支持图片/视频/文档（最大{MAX_RAW_SIZE_MB}MB）", font=font_default, foreground="#007bff")
    status_label.pack(fill=tk.X, padx=15, pady=2, anchor=tk.W)

    # 输入区
    input_frame = ttk.Frame(root, padding=5)
    input_frame.pack(fill=tk.X, padx=10, pady=5)

    # 左侧按钮区域（垂直排列上传和取消按钮）
    btn_frame = ttk.Frame(input_frame)
    btn_frame.pack(side=tk.LEFT, padx=5, pady=5)

    # 上传文件按钮
    upload_btn = tk.Button(
        btn_frame,
        text="📎 选择文件",
        font=font_default,
        bg="#f0f0f0",
        fg="black",
        width=10,
        height=1,
        command=select_file
    )
    upload_btn.pack(side=tk.TOP, padx=2, pady=2)

    # 取消文件选择按钮（初始禁用）
    cancel_file_btn = tk.Button(
        btn_frame,
        text="❌ 取消文件",
        font=font_default,
        bg="#ffebee",
        fg="#d32f2f",
        width=10,
        height=1,
        command=cancel_file_selection,
        state=tk.DISABLED
    )
    cancel_file_btn.pack(side=tk.TOP, padx=2, pady=2)

    # 深度思考开关
    thinking_btn = tk.Button(
        btn_frame,
        text="深度思考(关闭)",
        font=font_default,
        bg="white",
        fg="#333333",
        width=10,
        height=1,
        command=toggle_thinking
    )
    thinking_btn.pack(side=tk.TOP, padx=2, pady=2)

    # 输入框
    input_text = scrolledtext.ScrolledText(
        input_frame,
        font=font_chat,
        wrap=tk.WORD,
        height=3,
        width=60
    )
    input_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
    input_text.bind("<Return>", send_message)  # 绑定回车发送

    # 发送按钮
    send_btn = tk.Button(
        input_frame,
        text="发送 ↑",
        font=font_default,
        bg="#2196f3",
        fg="white",
        width=8,
        height=1,
        command=send_message
    )
    send_btn.pack(side=tk.RIGHT, padx=5, pady=5)

    # 窗口居中
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    # 程序退出时清理临时文件
    def on_closing():
        # 清理可能残留的临时视频文件
        for file in os.listdir("."):
            if file.startswith("temp_compressed_") and file.endswith(".mp4"):
                try:
                    os.remove(file)
                except:
                    pass
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)

    root.mainloop()

# ====================== 修复后的FileID示例代码（独立测试用） ======================
def test_fileid_example():
    """修复后的FileID调用示例（可独立运行测试）"""
    FILE_ID = "your-actual-file-id"  # 修复Bug3：定义FILE_ID变量
    API_KEY = os.getenv('DASHSCOPE_API_KEY', "sk-6d02c1bd446f4e2588725bb590c61dfa")
    
    # 修复Bug5：纠正拼写错误
    messages = [
        {'role': 'system', 'content': 'you are a helpful assistant'},
        # 修复Bug1：FileID放在user的content数组中
        {
            'role': 'user',
            'content': [
                {'text': '这篇文章讲了什么'},
                {'file': f'fileid://{FILE_ID}'}
            ]
        }
    ]
    
    try:
        dashscope.api_key = API_KEY
        response = dashscope.Generation.call(
            model="qwen-long",
            messages=messages,
            result_format='message'
        )
        
        # 修复Bug7：完善异常处理和响应解析
        if response.status_code == HTTPStatus.OK:
            print("✅ 调用成功：")
            print(response.output.choices[0].message.content)
        else:
            print(f"❌ 调用失败：{response.code} - {response.message}")
    except Exception as e:
        print(f"❌ 执行异常：{str(e)}")

if __name__ == "__main__":
    # 预检查API密钥
    if not API_KEY or not API_KEY.startswith("sk-"):
        print("❌ 请配置有效的API密钥！")
    else:
        # 如需测试FileID示例，取消注释：
        # test_fileid_example()
        
        # 运行GUI主程序
        create_gui()