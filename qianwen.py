import os
import base64
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk
from http import HTTPStatus
import dashscope
from dashscope import MultiModalConversation
import threading

# ====================== 核心配置 ======================
API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-6d02c1bd446f4e2588725bb590c61dfa")
MULTI_MODAL_MODEL = "qwen3.5-plus"

# 地域配置（北京地域，按需切换）
dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"
# dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"  # 新加坡 
# dashscope.base_http_api_url = "https://dashscope-us.aliyuncs.com/api/v1"    # 弗吉尼亚

# 支持格式
SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.mov', '.avi', '.flv', '.mkv']
DEFAULT_FPS = 2  # 视频默认抽帧频率
enable_thinking = False  # 思考模式默认关闭（关：黑字白底；开：蓝字淡蓝底）

# ====================== 全局变量 ======================
selected_file_path = ""
file_type = ""  # "image"/"video"/""
root = None
chat_text = None    # 对话框（大显示区）
input_text = None   # 用户输入框
upload_btn = None   # 文件上传按钮
thinking_btn = None # 深度思考开关
send_btn = None     # 发送按钮
status_label = None # 状态栏

# ====================== 工具函数 ======================
def init_dashscope():
    """初始化API，校验密钥有效性"""
    try:
        if not API_KEY or len(API_KEY) < 10 or not API_KEY.startswith("sk-"):
            show_status("❌ API_KEY格式错误，请配置有效密钥", "error")
            return False
        dashscope.api_key = API_KEY
        return True
    except Exception as e:
        show_status(f"❌ 初始化失败：{str(e)[:100]}", "error")
        return False

def select_file():
    """单按钮上传文件（同时支持图片/视频）"""
    global selected_file_path, file_type
    file_path = filedialog.askopenfilename(
        title="选择图片/视频文件",
        filetypes=[
            ("图片/视频文件", "*.jpg *.jpeg *.png *.gif *.bmp *.mp4 *.mov *.avi *.flv *.mkv"),
            ("所有文件", "*.*")
        ]
    )
    if not file_path or not os.path.exists(file_path):
        selected_file_path = ""
        file_type = ""
        show_status("ℹ️ 已取消文件选择", "info")
        return

    # 文件大小校验（≤8MB）
    raw_size = os.path.getsize(file_path) / (1024 * 1024)
    if raw_size > 8:
        show_status(f"❌ 文件过大！需≤8MB，当前{raw_size:.1f}MB", "error")
        selected_file_path = ""
        file_type = ""
        return

    # 判断文件类型
    file_ext = os.path.splitext(file_path)[1].lower()
    if file_ext in SUPPORTED_IMAGE_FORMATS:
        file_type = "image"
    elif file_ext in SUPPORTED_VIDEO_FORMATS:
        file_type = "video"
    else:
        show_status(f"❌ 不支持的格式：{file_ext}", "error")
        selected_file_path = ""
        file_type = ""
        return

    selected_file_path = file_path
    show_status(f"✅ 已选择【{file_type}】：{os.path.basename(file_path)}", "info")

def toggle_thinking():
    """切换深度思考模式（关：黑字白底；开：蓝字淡蓝底）"""
    global enable_thinking
    enable_thinking = not enable_thinking
    if enable_thinking:
        thinking_btn.config(
            bg="#e3f2fd",  # 淡蓝底
            fg="#007bff",  # 蓝字
            text="深度思考(开启)"
        )
        show_status("✅ 已开启深度思考，将显示模型推理过程", "info")
    else:
        thinking_btn.config(
            bg="white",  # 白底
            fg="#333333", # 黑字
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
    """线程安全的对话框消息插入（纯文字无框）
    - user: 右对齐蓝色文字
    - assistant: 左对齐黑色文字
    - thinking: 左对齐灰色文字
    """
    def update():
        chat_text.config(state=tk.NORMAL)
        if sender == "user":
            # 用户消息：右对齐蓝色纯文字
            chat_text.insert(tk.END, f"\n{content}\n", "user")
        elif sender == "assistant":
            # AI消息：左对齐黑色纯文字
            chat_text.insert(tk.END, "\n", "assistant")
        elif sender == "thinking":
            # 思考过程：左对齐灰色纯文字
            chat_text.insert(tk.END, "\n", "thinking")
        chat_text.config(state=tk.DISABLED)
        chat_text.see(tk.END)
        root.update_idletasks()
    root.after(0, update)

def append_chat(sender, content):
    """线程安全地向最后一个消息追加内容（实现连续流式输出，无框）"""
    def update():
        chat_text.config(state=tk.NORMAL)
        chat_text.insert(tk.END, content, sender)
        chat_text.config(state=tk.DISABLED)
        chat_text.see(tk.END)
        root.update_idletasks()
    root.after(0, update)

def file_to_base64(file_path):
    """文件转base64（带大小校验）"""
    try:
        with open(file_path, 'rb') as f:
            content = f.read()
        b64_data = base64.b64encode(content)
        b64_size_mb = len(b64_data) / (1024 * 1024)
        if b64_size_mb > 10:
            raise Exception(f"base64编码后超10MB（当前{b64_size_mb:.1f}MB）")

        ext = os.path.splitext(file_path)[1].lower()
        if ext in SUPPORTED_IMAGE_FORMATS:
            img_type = "jpeg" if ext in ['.jpg', '.jpeg'] else ext[1:]
            prefix = f"data:image/{img_type};base64,"
        elif ext in SUPPORTED_VIDEO_FORMATS:
            prefix = f"data:video/{ext[1:]};base64,"
        else:
            raise ValueError(f"不支持的格式：{ext}")
        return prefix + b64_data.decode('utf-8')
    except Exception as e:
        raise Exception(f"文件编码失败：{str(e)}")

# ====================== 核心请求处理 ======================
def process_request(user_prompt):
    """流式处理请求（纯文本/图片/视频，支持思考模式，连续无框输出）"""
    api_error = False
    has_content = False
    is_answering = False
    reasoning = ""
    answer = ""

    try:
        # 构建请求消息
        messages = [{"role": "user", "content": []}]
        
        # 处理文件（图片/视频）
        if selected_file_path:
            show_status(f"🔄 正在编码{file_type}文件...")
            try:
                file_b64 = file_to_base64(selected_file_path)
            except Exception as e:
                insert_chat("assistant")
                append_chat("assistant", f"❌ 文件编码失败：{str(e)}")
                show_status("❌ 文件编码失败", "error")
                api_error = True
                return

            if file_type == "image":
                messages[0]["content"].append({"image": file_b64})
                show_status("🔄 正在分析图片...")
            elif file_type == "video":
                messages[0]["content"].append({"video": file_b64, "fps": DEFAULT_FPS})
                show_status(f"🔄 正在分析视频（fps={DEFAULT_FPS}）...")
        else:
            show_status("🔄 正在进行纯文本对话...")

        # 添加用户提示词
        messages[0]["content"].append({"text": user_prompt})

        # 调用流式API（带思考模式参数）
        responses = MultiModalConversation.call(
            model=MULTI_MODAL_MODEL,
            messages=messages,
            stream=True,
            enable_thinking=enable_thinking,
            thinking_budget=81920,
            incremental_output=True
        )

        # 处理流式响应（连续无框输出）
        if enable_thinking:
            insert_chat("thinking")
            append_chat("thinking", "="*20 + "思考过程" + "="*20 + "\n")

        for chunk in responses:
            # 基础状态校验
            if not hasattr(chunk, 'status_code') or chunk.status_code != HTTPStatus.OK:
                code = getattr(chunk, 'code', '未知错误')
                msg = getattr(chunk, 'message', 'API异常')
                if not is_answering:
                    insert_chat("assistant")
                append_chat("assistant", f"\n❌ API错误：{code} - {msg}")
                show_status("❌ 请求失败", "error")
                api_error = True
                break

            # 逐层空值保护
            if (not hasattr(chunk, 'output') or 
                not hasattr(chunk.output, 'choices') or 
                len(chunk.output.choices) == 0):
                continue

            msg = chunk.output.choices[0].message
            reasoning_chunk = msg.get("reasoning_content", "")
            content = msg.content if hasattr(msg, 'content') else []

            # 空内容跳过
            if content == [] and reasoning_chunk == "":
                continue

            # 处理思考过程（连续无框）
            if enable_thinking and reasoning_chunk and content == []:
                reasoning += reasoning_chunk
                append_chat("thinking", reasoning_chunk)
                has_content = True
            # 处理最终回复（连续无框）
            elif content != []:
                if not is_answering:
                    insert_chat("assistant")
                    if enable_thinking:
                        append_chat("assistant", "\n" + "="*20 + "完整回复" + "="*20 + "\n")
                    is_answering = True

                if isinstance(content, list) and len(content) > 0:
                    text = content[0].get('text', '')
                    if text:
                        answer += text
                        append_chat("assistant", text)
                        has_content = True

    except Exception as e:
        if not is_answering:
            insert_chat("assistant")
        append_chat("assistant", f"\n❌ 处理异常：{str(e)}")
        show_status("❌ 程序异常", "error")
        api_error = True
    finally:
        # 最终状态更新
        if not api_error:
            if has_content:
                if selected_file_path:
                    show_status(f"✅ {file_type}分析完成" + (f"（fps={DEFAULT_FPS}）" if file_type == "video" else ""))
                else:
                    show_status("✅ 纯文本对话完成")
            else:
                show_status("⚠️ 未获取到有效响应", "warning")
        # 恢复发送按钮
        root.after(0, lambda: send_btn.config(state=tk.NORMAL))

def send_message(event=None):
    """发送消息（支持点击按钮/回车发送，shift+回车换行）"""
    # 处理shift+回车换行（不拦截）
    if event and event.state & 0x0001:
        return
    if not init_dashscope():
        return
    # 获取用户输入
    prompt = input_text.get("1.0", tk.END).strip()
    if not prompt:
        show_status("❌ 请输入对话/分析内容", "error")
        return

    # 禁用发送按钮防重复提交
    send_btn.config(state=tk.DISABLED)
    # 清空输入框
    input_text.delete("1.0", tk.END)

    # 显示用户消息（纯文字右对齐蓝色）
    user_msg = prompt
    if selected_file_path:
        user_msg = f"[上传{file_type}：{os.path.basename(selected_file_path)}]\n{prompt}"
    insert_chat("user", user_msg)

    # 启动子线程处理请求
    threading.Thread(target=process_request, args=(prompt,), daemon=True).start()

    # 阻止回车默认换行（仅回车发送时生效）
    if event:
        return "break"

# ====================== UI构建（无框纯文字聊天UI） ======================
def create_gui():
    global root, chat_text, input_text, upload_btn, thinking_btn, send_btn, status_label

    root = tk.Tk()
    root.title("使用qwen3.5-plus处理多模态")
    root.geometry("900x800")
    root.resizable(True, True)

    # 字体配置
    font_default = ("微软雅黑", 10)
    font_chat = ("微软雅黑", 11)

    # 顶部标题
    ttk.Label(root, text="使用qwen3.5-plus处理多模态", font=("微软雅黑", 12, "bold")).pack(pady=8)
    ttk.Label(root, text="内容由千问AI生成", font=("微软雅黑", 8), foreground="gray").pack(pady=0)

    # 中间对话框（大显示区，纯文字无框）
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
    # 配置纯文字样式（无框无背景，仅区分对齐和颜色）
    chat_text.tag_configure(
        "user",
        justify=tk.RIGHT,
        foreground="#007bff",  # 用户消息蓝色
        spacing1=8,
        spacing3=8
    )
    chat_text.tag_configure(
        "assistant",
        justify=tk.LEFT,
        foreground="#000000",  # AI消息黑色
        spacing1=8,
        spacing3=8
    )
    chat_text.tag_configure(
        "thinking",
        justify=tk.LEFT,
        foreground="#666666",  # 思考过程灰色
        spacing1=2,
        spacing3=2
    )

    # 状态栏（对话框下方）
    status_label = ttk.Label(root, text="✅ 就绪，可输入内容发送", font=font_default, foreground="#007bff")
    status_label.pack(fill=tk.X, padx=15, pady=2, anchor=tk.W)

    # 底部输入区（完全还原你的UI布局）
    input_frame = ttk.Frame(root, padding=5)
    input_frame.pack(fill=tk.X, padx=10, pady=5)

    # 左侧按钮区（文件上传+深度思考）
    btn_frame = ttk.Frame(input_frame)
    btn_frame.pack(side=tk.LEFT, padx=5, pady=5)

    # 文件上传单按钮（📎图标）
    upload_btn = tk.Button(
        btn_frame,
        text="📎",
        font=font_default,
        bg="#f0f0f0",
        fg="black",
        width=3,
        height=1,
        command=select_file
    )
    upload_btn.pack(side=tk.LEFT, padx=2)

    # 深度思考开关（关：黑字白底；开：蓝字淡蓝底）
    thinking_btn = tk.Button(
        btn_frame,
        text="深度思考(关闭)",
        font=font_default,
        bg="white",  # 初始白底
        fg="#333333", # 初始黑字
        command=toggle_thinking
    )
    thinking_btn.pack(side=tk.LEFT, padx=5)

    # 中间用户输入框
    input_text = scrolledtext.ScrolledText(
        input_frame,
        font=font_chat,
        wrap=tk.WORD,
        height=3,
        width=60
    )
    input_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
    # 绑定回车发送（shift+回车换行）
    input_text.bind("<Return>", send_message)

    # 右侧发送按钮（右下角）
    send_btn = tk.Button(
        input_frame,
        text="↑",
        font=font_default,
        bg="#cccccc",
        fg="white",
        width=3,
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

    root.mainloop()

if __name__ == "__main__":
    create_gui()