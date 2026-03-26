# heart_rate_display_ui.py

import asyncio
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, colorchooser, filedialog
import sys
import queue
from datetime import datetime
import json
from urllib import request, error

from heart_rate_tool import BluetoothTool
from config import save_config, load_config
from floating_window import FloatingWindow
from vrc_osc import VrcOscClient
from api_server import ApiServer
from websocket_server import WebSocketServer # [新增] 导入WebSocket服务器
from webhook_manager import WebhookManager
from webhook_ui import WebhookWindow
from utils import ICON_PATH, CURRENT_VERSION

# ==========================================
# 高性能平滑波形组件 (Low CPU Usage 版)
# ==========================================
class RealTimeWaveform:
    def __init__(self, parent_frame):
        self.max_points = 100
        self.data = [75.0] * self.max_points
        
        # 视觉配置
        self.bg_color = "#1A1A1A"
        self.line_color = "#00FF88"
        self.grid_color = "#333333"
        self.text_color = "#AAAAAA"
        self.left_margin = 45 
        
        # --- 核心改进：平滑切换变量 ---
        self.target_min, self.target_max = 50, 100 # 目标区间
        self.current_min, self.current_max = 50, 100 # 实时显示的区间（用于动画）
        self.buffer = 3 # 滞后缓冲区：心率需超过边界 3bpm 才会触发切换
        
        self.canvas = tk.Canvas(
            parent_frame, bg=self.bg_color, 
            highlightthickness=0, height=120, bd=0
        )
        self.canvas.pack(fill="x", expand=True, pady=(1, 0))
        self.canvas.bind("<Configure>", lambda e: self.draw())

    def push_data(self, bpm):
        if bpm <= 0: return
        self.data.pop(0)
        self.data.append(bpm)
        
        # --- 核心逻辑 1：带滞后(Hysteresis)的区间判断 ---
        # 只有显著超过或低于当前区间边界时，才修改目标区间
        if bpm < (self.target_min - self.buffer) or bpm > (self.target_max + self.buffer):
            if bpm <= 50 + self.buffer:
                self.target_min, self.target_max = 0, 50
            elif bpm <= 100 + self.buffer:
                self.target_min, self.target_max = 50, 100
            elif bpm <= 150 + self.buffer:
                self.target_min, self.target_max = 100, 150
            else:
                self.target_min, self.target_max = 150, 200

        # --- 核心逻辑 2：坐标轴平滑过渡动画 ---
        # 每一帧向目标靠拢 20%，产生丝滑的滚动感
        self.current_min += (self.target_min - self.current_min) * 0.2
        self.current_max += (self.target_max - self.current_max) * 0.2
            
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 70: return

        v_padding = 15 
        draw_h = h - (v_padding * 2)
        
        # 绘制基于目标区间的刻度线（让文字保持整数，不随动画乱跳）
        ticks = [self.target_min, (self.target_min + self.target_max) / 2, self.target_max]
        diff = self.current_max - self.current_min
        if diff == 0: diff = 1
        
        for val in ticks:
            # 使用 current_min 进行坐标映射，实现波形随坐标轴滚动的效果
            y_pos = h - v_padding - ((val - self.current_min) / diff * draw_h)
            
            # 绘制水平线
            self.canvas.create_line(self.left_margin, y_pos, w, y_pos, fill=self.grid_color, dash=(2, 4))
            
            # 绘制刻度数字
            self.canvas.create_text(
                self.left_margin - 10, y_pos, 
                text=str(int(val)), 
                fill=self.text_color, font=("Consolas", 9, "bold"), anchor="e"
            )

        # 绘制平滑波形
        plot_width = w - self.left_margin
        x_step = plot_width / (self.max_points - 1)
        points = []
        for i, bpm in enumerate(self.data):
            x = self.left_margin + (i * x_step)
            y = h - v_padding - ((bpm - self.current_min) / diff * draw_h)
            y = max(v_padding, min(h - v_padding, y))
            points.extend([x, y])
        
        if len(points) >= 4:
            self.canvas.create_line(points, fill=self.line_color, width=2, smooth=True, splinesteps=8)


# ==========================================
# 主界面类
# ==========================================
class HeartRateMonitor:
    def __init__(self):
        self.heart_rate = 0
        self.max_heart_rate = 0
        self.waveform = None
        self.connected = False
        self.current_mac = ""
        self.should_connect = False  # 控制自动重连循环
        self.ble_task = None
        self.ble_loop = None  # 专用的异步循环
        self.ble_thread = None  # 运行异步循环的线程
        self.should_stop = False
        # [新增] 波形组件引用
        self.waveform = None
        
        self.ble_tool = BluetoothTool(self.log_message) # 传入日志函数

        self.api_server = None
        self.websocket_server = WebSocketServer(self, port=8001, logger_func=self.log_message)
        
        self.floating_window = FloatingWindow(self)
        
        self.log_queue = queue.Queue()
        self.vrc_osc_client = VrcOscClient(self.log_message)
        self.vrc_connected = False
        
        self.heart_rate_queue = queue.Queue()
        
        self.webhook_manager = WebhookManager(self.log_message)
        self.webhook_window = None
        
        self.setup_ui()        
        self.update_logs()
        self.update_heart_rate_display()       
        self.load_settings()

    def apply_global_icon(self, window):
        """为传入的窗口应用全局图标"""
        try:
            # 1. 设置标题栏图标 (ico文件)
            window.iconbitmap(ICON_PATH)
            
            # 2. 设置任务栏图标 (需要 PhotoImage)
            if hasattr(self, 'global_icon_img'):
                window.iconphoto(False, self.global_icon_img)
        except Exception as e:
            print(f"图标应用失败: {e}")

    def reset_max_heart_rate(self):
        """[无弹窗版] 立即重置最高心率统计"""
        self.max_heart_rate = 0
        
        # 1. 更新主界面数值显示
        if hasattr(self, 'max_hr_display'):
            self.max_hr_display.config(text="MAX: 0")
        
        # 2. 立即通知 WebSocket 服务器 (同步给 OBS 网页端)
        if self.websocket_server:
            self.websocket_server.broadcast_heart_rate(self.heart_rate, 0)
            
        # 3. 记录日志
        self.log_message("最高心率已重置")


    def setup_ui(self):
        self.root = tk.Tk()
        self.root.title(f"心率监控器 - {CURRENT_VERSION}")
        self.root.geometry("880x600") 
        self.root.minsize(800, 515)
        self.root.resizable(True, True)
        self.root.configure(bg="#F0F0F0")
        
        try:
            from PIL import Image, ImageTk
            img = Image.open(ICON_PATH)
            self.global_icon_img = ImageTk.PhotoImage(img)
            # 给主窗口设置图标
            self.apply_global_icon(self.root)
        except:
            pass

        # [新增] WebSocket UI变量
        self.websocket_server_enabled = tk.BooleanVar(value=False)
        self.websocket_port_var = tk.StringVar(value="8001")
        
        self.api_server_enabled = tk.BooleanVar(value=False)
        self.api_port_var = tk.StringVar(value="8000")
        self.vrc_ip_var = tk.StringVar(value="127.0.0.1")
        self.vrc_port_var = tk.StringVar(value="9000")

        self.format_var = tk.StringVar(value="{img}{bpm}")
        self.image_path_var = tk.StringVar(value="未选择图片")
        
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        main_frame.columnconfigure(0, weight=1, uniform="group1")
        main_frame.columnconfigure(1, weight=1, uniform="group1")
        main_frame.columnconfigure(2, weight=1, uniform="group1")
        main_frame.rowconfigure(1, weight=1) 

        left_column_frame = ttk.Frame(main_frame)
        middle_column_frame = ttk.Frame(main_frame)
        right_column_frame = ttk.Frame(main_frame)

        left_column_frame.grid(row=0, column=0, sticky="new", padx=(0, 5))
        middle_column_frame.grid(row=0, column=1, sticky="new", padx=5)
        right_column_frame.grid(row=0, column=2, sticky="new", padx=(5, 0))

        PAD_Y = (0, 10)

        # --- 恢复：经典清爽布局 ---
        heart_rate_frame = ttk.LabelFrame(left_column_frame, text="实时状态", padding="10")
        heart_rate_frame.pack(fill="x", pady=PAD_Y)
        
        # 顶部：心率数字显示
        self.heart_rate_label = tk.Label(
            heart_rate_frame, 
            text="--", 

            font=("Arial Black", 36), 
            fg="#FF3B30", 
            bg="#1A1A1A",
            width=5 # 固定宽度，确保位置不动
        )
        self.heart_rate_label.pack(fill="x", pady=0, ipady=10)

        # 中间：[新增] 平滑波形组件
        self.waveform = RealTimeWaveform(heart_rate_frame)

        # 底部信息栏（状态 + 最高值 + 重置按钮）
        info_footer = tk.Frame(heart_rate_frame, bg="#1A1A1A")
        info_footer.pack(fill="x", pady=(1, 5))
        
        self.status_label = tk.Label(info_footer, text="● 未连接", font=("微软雅黑", 9), fg="gray", bg="#1A1A1A")
        self.status_label.pack(side=tk.LEFT)
        
        # [新增] 重置按钮：使用小巧的扁平化风格
        self.reset_max_btn = tk.Button(
            info_footer, text="↺ 重置最高", command=self.reset_max_heart_rate,
            font=("微软雅黑", 8), fg="#FF9500", bg="#1A1A1A", 
            relief="flat", cursor="hand2", activebackground="#333"
        )
        self.reset_max_btn.pack(side=tk.RIGHT)

        self.max_hr_display = tk.Label(info_footer, text="MAX: 0", font=("Consolas", 9, "bold"), fg="#AAAAAA", bg="#1A1A1A")
        self.max_hr_display.pack(side=tk.RIGHT, padx=10)
        
        device_frame = ttk.LabelFrame(left_column_frame, text="设备信息", padding="10")
        device_frame.pack(fill="x", pady=PAD_Y)
        device_frame.columnconfigure(1, weight=1)
        ttk.Label(device_frame, text="当前设备:").grid(row=0, column=0, sticky=tk.W)
        self.device_label = ttk.Label(device_frame, text="未选择设备")
        self.device_label.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        
        button_frame = ttk.LabelFrame(left_column_frame, text="连接控制", padding="10")
        button_frame.pack(fill="x", pady=PAD_Y)
        button_frame.columnconfigure((0, 1, 2), weight=1)
        self.scan_button = ttk.Button(button_frame, text="扫描设备", command=self.scan_devices)
        self.scan_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.connect_button = ttk.Button(button_frame, text="连接", command=self.connect_device, state=tk.DISABLED)
        self.connect_button.grid(row=0, column=1, padx=5, sticky="ew")
        self.disconnect_button = ttk.Button(button_frame, text="断开", command=self.disconnect_device, state=tk.DISABLED)
        self.disconnect_button.grid(row=0, column=2, padx=(5, 0), sticky="ew")
        
        vrc_frame = ttk.LabelFrame(middle_column_frame, text="VRChat OSC 同步", padding="10")
        vrc_frame.pack(fill="x", pady=PAD_Y)
        vrc_frame.columnconfigure(1, weight=1)
        ttk.Label(vrc_frame, text="IP 地址:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(vrc_frame, textvariable=self.vrc_ip_var).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Label(vrc_frame, text="端口:").grid(row=1, column=0, sticky=tk.W, pady=(5,0))
        ttk.Entry(vrc_frame, textvariable=self.vrc_port_var).grid(row=1, column=1, sticky="ew", padx=5, pady=(5,0))
        self.vrc_connect_button = ttk.Button(vrc_frame, text="连接 OSC", command=self.toggle_vrc_connection)
        self.vrc_connect_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10,0))
        self.vrc_status_label = ttk.Label(vrc_frame, text="状态: 未连接", font=("Arial", 10), foreground="gray")
        self.vrc_status_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(5,0))
        
        # [新增] WebSocket 服务器 UI
        websocket_frame = ttk.LabelFrame(middle_column_frame, text="WebSocket服务器 (实时推送)", padding="10")
        websocket_frame.pack(fill="x", pady=PAD_Y)
        websocket_frame.columnconfigure(1, weight=1)
        self.websocket_server_enabled.trace_add("write", self.toggle_websocket_server)
        ttk.Checkbutton(websocket_frame, text="启用WebSocket服务器", variable=self.websocket_server_enabled).grid(row=0, column=0, sticky=tk.W, columnspan=2)
        ttk.Label(websocket_frame, text="端口:").grid(row=1, column=0, sticky=tk.W, pady=(5,0))
        ttk.Entry(websocket_frame, textvariable=self.websocket_port_var, width=10).grid(row=1, column=1, sticky="ew", padx=5, pady=(5,0))
        self.websocket_status_label = ttk.Label(websocket_frame, text="状态: 已禁用", font=("Arial", 10), foreground="gray")
        self.websocket_status_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5,0))

        api_frame = ttk.LabelFrame(middle_column_frame, text="心率API服务器 (被动获取)", padding="10")
        api_frame.pack(fill="x", pady=PAD_Y)
        api_frame.columnconfigure(1, weight=1)
        self.api_server_enabled.trace_add("write", self.toggle_api_server)
        ttk.Checkbutton(api_frame, text="启用API服务器", variable=self.api_server_enabled).grid(row=0, column=0, sticky=tk.W, columnspan=2)
        ttk.Label(api_frame, text="端口:").grid(row=1, column=0, sticky=tk.W, pady=(5,0))
        ttk.Entry(api_frame, textvariable=self.api_port_var, width=10).grid(row=1, column=1, sticky="ew", padx=5, pady=(5,0))
        self.api_status_label = ttk.Label(api_frame, text="状态: 已禁用", font=("Arial", 10), foreground="gray")
        self.api_status_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5,0))

        webhook_frame = ttk.LabelFrame(middle_column_frame, text="Webhook 数据推送", padding="10")
        webhook_frame.pack(fill="x", pady=PAD_Y)
        ttk.Button(webhook_frame, text="打开 Webhook 设置...", command=self.open_webhook_window).pack(fill="x")
        
        floating_frame = ttk.LabelFrame(right_column_frame, text="悬浮窗控制", padding="10")
        floating_frame.pack(fill="x", pady=PAD_Y)
        floating_frame.columnconfigure((0, 1, 2), weight=1)
        self.show_floating_button = ttk.Button(floating_frame, text="显示悬浮窗", command=self.toggle_floating_window)
        self.show_floating_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.lock_button = ttk.Button(floating_frame, text="锁定悬浮窗", command=self.toggle_floating_lock, state=tk.DISABLED)
        self.lock_button.grid(row=0, column=1, padx=5, sticky="ew")
        self.save_button = ttk.Button(floating_frame, text="保存设置", command=self.save_settings)
        self.save_button.grid(row=0, column=2, padx=(5, 0), sticky="ew")
        
        color_frame = ttk.LabelFrame(right_column_frame, text="悬浮窗颜色设置", padding="10")
        color_frame.pack(fill="x", pady=PAD_Y)
        color_frame.columnconfigure(2, weight=1)
        ttk.Label(color_frame, text="解锁时 (可拖动):").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.unlocked_color_preview = tk.Label(color_frame, text="      ", bg=self.floating_window.unlocked_color)
        self.unlocked_color_preview.grid(row=0, column=1, sticky=tk.W)
        ttk.Button(color_frame, text="选择...", command=self.choose_unlocked_color).grid(row=0, column=2, padx=5, sticky=tk.E)
        ttk.Label(color_frame, text="锁定时 (穿透点击):").grid(row=1, column=0, sticky=tk.W, pady=(5, 0), padx=(0, 10))
        self.locked_color_preview = tk.Label(color_frame, text="      ", bg=self.floating_window.locked_color)
        self.locked_color_preview.grid(row=1, column=1, pady=(5, 0), sticky=tk.W)
        ttk.Button(color_frame, text="选择...", command=self.choose_locked_color).grid(row=1, column=2, padx=5, pady=(5, 0), sticky=tk.E)

        format_frame = ttk.LabelFrame(right_column_frame, text="悬浮窗格式设置", padding="10")
        format_frame.pack(fill="x", pady=PAD_Y)
        format_frame.columnconfigure(1, weight=1)
        ttk.Label(format_frame, text="格式:").grid(row=0, column=0, sticky=tk.W, padx=(0,5))
        ttk.Entry(format_frame, textvariable=self.format_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(format_frame, text="提示:").grid(row=1, column=0, sticky=tk.W, pady=(5,0), padx=(0,5))
        ttk.Label(format_frame, text="{img}: 图片,{bpm}: 心率", foreground="gray").grid(row=1, column=1, sticky="w", pady=(5,0))
        ttk.Label(format_frame, text="图片:").grid(row=2, column=0, sticky=tk.W, pady=(5,0), padx=(0,5))
        ttk.Label(format_frame, textvariable=self.image_path_var, wraplength=160, justify=tk.LEFT, foreground="blue").grid(row=2, column=1, sticky="ew", pady=(5,0))
        btn_subframe = ttk.Frame(format_frame)
        btn_subframe.grid(row=3, column=0, columnspan=2, pady=(10,0), sticky="ew")
        btn_subframe.columnconfigure((0,1,2), weight=1)
        ttk.Button(btn_subframe, text="选择图片...", command=self.choose_image).grid(row=0, column=0, sticky='ew', padx=(0,5))
        ttk.Button(btn_subframe, text="清除图片", command=self.clear_image).grid(row=0, column=1, sticky='ew', padx=5)
        ttk.Button(btn_subframe, text="应用格式", command=self.apply_format).grid(row=0, column=2, sticky='ew', padx=(5,0))

        # 日志区
        log_frame = ttk.LabelFrame(main_frame, text="系统日志")
        log_frame.grid(row=1, column=0, columnspan=3, sticky="nsew")
        self.log_text = scrolledtext.ScrolledText(log_frame, state='disabled', height=8, font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

    def open_webhook_window(self):
        if self.webhook_window and self.webhook_window.winfo_exists():
            self.webhook_window.focus()
            return
        self.webhook_window = WebhookWindow(self, self.webhook_manager)

    def choose_image(self):
        filepath = filedialog.askopenfilename(
            title="选择一张图片",
            filetypes=[("图片文件", "*.png *.gif *.jpg *.jpeg"), ("所有文件", "*.*")]
        )
        if filepath:
            self.floating_window.set_image(filepath)
            import os
            self.image_path_var.set(os.path.basename(filepath))
            self.log_message(f"已选择图片: {filepath}")

    def clear_image(self):
        self.floating_window.set_image(None)
        self.image_path_var.set("未选择图片")
        self.log_message("已清除图片。")

    def apply_format(self):
        new_format = self.format_var.get()
        self.floating_window.update_format(new_format)
        self.log_message(f"已应用新格式: {new_format}")

    def choose_unlocked_color(self):
        color_code = colorchooser.askcolor(title="选择解锁时的字体颜色", initialcolor=self.floating_window.unlocked_color)
        if color_code and color_code[1]:
            color = color_code[1]
            self.floating_window.unlocked_color = color
            self.unlocked_color_preview.config(bg=color)
            if self.floating_window.is_open():
                self.floating_window.apply_lock_state()
            self.log_message(f"设置解锁颜色为: {color}")

    def choose_locked_color(self):
        color_code = colorchooser.askcolor(title="选择锁定时的字体颜色", initialcolor=self.floating_window.locked_color)
        if color_code and color_code[1]:
            color = color_code[1]
            self.floating_window.locked_color = color
            self.locked_color_preview.config(bg=color)
            if self.floating_window.is_open():
                self.floating_window.apply_lock_state()
            self.log_message(f"设置锁定颜色为: {color}")

    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {message}")

    def update_logs(self):
        """带自动清理功能的日志刷新"""
        try:
            has_new = False
            # 1. 批量处理队列，防止界面卡顿
            while not self.log_queue.empty():
                msg = self.log_queue.get_nowait()
                self.log_text.config(state='normal')
                
                # 2. 检查日志行数，超过 500 行自动清理旧日志（解决长时间运行卡顿）
                line_count = int(self.log_text.index('end-1c').split('.')[0])
                if line_count > 500:
                    self.log_text.delete('1.0', '101.0') # 删除前100行
                    
                self.log_text.insert(tk.END, msg + "\n")
                has_new = True
                
            if has_new:
                self.log_text.config(state='disabled')
                self.log_text.see(tk.END)
        except Exception:
            pass
        
        # 每 200ms 刷新一次，降低 CPU 负担
        self.root.after(200, self.update_logs)


    def update_heart_rate_display(self):
        """定期从队列读取心率数据并更新 UI 和 API"""
        try:
            while True:
                bpm = self.heart_rate_queue.get_nowait()
                if bpm > 0:
                    self.heart_rate = bpm
                    
                    # --- 核心新增：记录最高心率 ---
                    if bpm > self.max_heart_rate:
                        self.max_heart_rate = bpm
                    
                    # 更新主界面标签
                    self.heart_rate_label.config(text=f"心率 : {bpm}")
                    self.max_hr_display.config(text=f"MAX: {self.max_heart_rate}")

                    # [核心新增] 更新波形图数据
                    if self.waveform:
                        self.waveform.push_data(bpm)
                    
                    # 更新悬浮窗
                    if self.floating_window and self.floating_window.is_open():
                        self.floating_window.update_heart_rate(bpm)
                    
                    # 更新 VRChat OSC
                    if self.vrc_connected:
                        self.vrc_osc_client.send_heart_rate(bpm)
                        
                    # [新增] 如果启用了 WebSocket，推送数据
                    if self.websocket_server:
                        self.websocket_server.broadcast_heart_rate(bpm, self.max_heart_rate)
                        
        except queue.Empty:
            pass
            
        # 持续循环
        self.root.after(100, self.update_heart_rate_display)


    def clear_logs(self):
        self.log_text.delete(1.0, tk.END)

    # --- WebSocket 服务器控制 ---
    def is_port_in_use(self, port):  # 加上 self
        """检查本地端口是否被占用"""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                return s.connect_ex(('127.0.0.1', int(port))) == 0
        except:
            return False

    def toggle_websocket_server(self, *args):
        """启动或停止 WebSocket 服务器"""
        if self.websocket_server_enabled.get():
            # 1. 尝试停止并清理旧实例
            if self.websocket_server:
                self.websocket_server.stop()
                self.websocket_server = None
                
            # 2. 获取并检查端口状态
            try:
                port_str = self.websocket_port_var.get()
                if not port_str.isdigit():
                    raise ValueError("端口号必须是数字")
                
                port = int(port_str)
                
                # 检查端口是否还在占用中（Windows 端口回收较慢）
                if self.is_port_in_use(port):
                    self.log_message(f"[WS] 端口 {port} 尚未被系统释放，请稍后再试或更换端口")
                    # 提示：Windows 的 TIME_WAIT 状态通常需要 30-120 秒
                    self.websocket_server_enabled.set(False) 
                    return

                # 3. 端口可用，尝试启动
                from websocket_server import WebSocketServer
                self.websocket_server = WebSocketServer(self, port=port, logger_func=self.log_message)
                self.websocket_server.start()
                
                self.websocket_status_label.config(text=f"状态: 运行中 ({port})", foreground="green")
                self.log_message(f"[WS] 服务器尝试在端口 {port} 启动")
                self.root.after(1000, self._force_ws_sync)
                
            except ValueError as e:
                self.log_message(f"[WS] 错误: {e}")
                self.websocket_server_enabled.set(False)
            except Exception as e:
                self.log_message(f"[WS] 启动异常: {e}")
                self.websocket_server_enabled.set(False)
        else:
            # 关闭逻辑
            if self.websocket_server:
                self.websocket_server.stop()
                self.websocket_server = None
            self.websocket_status_label.config(text="状态: 已禁用", foreground="gray")
            self.log_message("[WS] 服务器已请求停止")

    def _force_ws_sync(self):
        """强制同步一次当前心率给所有连接的客户端(如OBS)"""
        if self.websocket_server:
            # 哪怕心率是 0，也要发一次，让 OBS 知道服务器在线
            self.websocket_server.broadcast_heart_rate(self.heart_rate, self.max_heart_rate)

    def toggle_api_server(self, *args):
        if self.api_server_enabled.get():
            try:
                port = int(self.api_port_var.get())
                self.api_server = ApiServer(self, port)
                self.api_server.start()
                if self.api_server and self.api_server.httpd:
                    self.api_status_label.config(text=f"状态: 运行于 http://127.0.0.1:{port}", foreground="green")
                else:
                    self.api_status_label.config(text="状态: 启动失败", foreground="red")
                    self.api_server_enabled.set(False)
            except ValueError:
                self.log_message("API服务器启动失败：端口号必须是有效的数字。")
                self.api_status_label.config(text="状态: 端口号无效", foreground="red")
                self.api_server_enabled.set(False)
        else:
            if self.api_server:
                self.api_server.stop()
                self.api_server = None
            self.api_status_label.config(text="状态: 已禁用", foreground="gray")

    def save_settings(self):
        self.webhook_manager.save_webhooks() 
        
        geometry = self.floating_window.last_geometry
        if self.floating_window.is_open() and self.floating_window.window is not None:
            geometry = self.floating_window.window.geometry()
            
        config = {
            "mac": self.current_mac,
            "window": {
                "visible": self.floating_window.is_open(),
                "locked": self.floating_window.is_locked(),
                "geometry": geometry,
                "unlocked_color": self.floating_window.unlocked_color,
                "locked_color": self.floating_window.locked_color,
                "format": self.format_var.get(),
                "image_path": self.floating_window.image_path,
            },
            "vrc_osc": {
                "ip": self.vrc_ip_var.get(),
                "port": self.vrc_port_var.get()
            },
            "api_server": {
                "enabled": self.api_server_enabled.get(),
                "port": self.api_port_var.get()
            },
            # [新增] 保存 WebSocket 设置
            "websocket_server": {
                "enabled": self.websocket_server_enabled.get(),
                "port": self.websocket_port_var.get()
            }
        }
        save_config(config)
        self.log_message("设置已保存到 config.json")

    def load_settings(self):
        config = load_config()
        if not config:
            self.log_message("未找到配置文件，使用默认设置。")
            return

        mac = config.get("mac")
        if mac:
            self.current_mac = mac
            self.device_label.config(text=f"MAC: {mac}")
            self.connect_button.config(state=tk.NORMAL)
            self.log_message(f"从配置文件加载设备: {mac}")

        window_settings = config.get("window")
        if window_settings:
            self.log_message("正在加载悬浮窗设置...")
            unlocked_color = window_settings.get("unlocked_color", "#00FF00")
            locked_color = window_settings.get("locked_color", "#FF6600")
            self.floating_window.unlocked_color = unlocked_color
            self.floating_window.locked_color = locked_color
            self.unlocked_color_preview.config(bg=unlocked_color)
            self.locked_color_preview.config(bg=locked_color)
            format_str = window_settings.get("format", "{img}{bpm}")
            image_path = window_settings.get("image_path")
            self.format_var.set(format_str)
            self.floating_window.update_format(format_str)
            if image_path:
                import os
                if os.path.exists(image_path):
                    self.floating_window.set_image(image_path)
                    self.image_path_var.set(os.path.basename(image_path))
                    self.log_message(f"已加载图片: {image_path}")
                else:
                    self.log_message(f"配置文件中的图片路径不存在: {image_path}")
                    self.image_path_var.set("图片丢失")
  
            if window_settings.get("visible", False):
                self.floating_window.last_geometry = window_settings.get("geometry", "200x80+100+100")
                self.toggle_floating_window() 
                if window_settings.get("locked", False):
                    self.root.after(100, self.toggle_floating_lock)
        
        vrc_settings = config.get("vrc_osc")
        if vrc_settings:
            self.vrc_ip_var.set(vrc_settings.get("ip", "127.0.0.1"))
            self.vrc_port_var.set(vrc_settings.get("port", "9000"))
            self.log_message("已加载 VRChat OSC 设置")

        # [新增] 加载 WebSocket 设置
        websocket_settings = config.get("websocket_server")
        if websocket_settings:
            self.websocket_port_var.set(websocket_settings.get("port", "8001"))
            if websocket_settings.get("enabled", False):
                # 延迟执行，确保UI完全加载
                self.root.after(200, lambda: self.websocket_server_enabled.set(True))
            self.log_message("已加载 WebSocket 服务器设置")

        api_settings = config.get("api_server")
        if api_settings:
            self.api_port_var.set(api_settings.get("port", "8000"))
            if api_settings.get("enabled", False):
                self.root.after(100, lambda: self.api_server_enabled.set(True))
            self.log_message("已加载 API 服务器设置")
        
    def toggle_vrc_connection(self):
        if self.vrc_connected:
            self.vrc_osc_client.disconnect()
            self.vrc_connected = False
            self.vrc_connect_button.config(text="连接 OSC")
            self.vrc_status_label.config(text="状态: 未连接", foreground="gray")
            self.log_message("VRChat OSC 已断开")
        else:
            ip = self.vrc_ip_var.get()
            port_str = self.vrc_port_var.get()
            if not ip or not port_str:
                messagebox.showerror("OSC 错误", "IP地址和端口不能为空")
                return
            try:
                port = int(port_str)
                success, message = self.vrc_osc_client.connect(ip, port)
                if success:
                    self.vrc_connected = True
                    self.vrc_connect_button.config(text="断开 OSC")
                    self.vrc_status_label.config(text=f"状态: 已连接到 {ip}:{port}", foreground="green")
                    self.log_message(message)
                else:
                    messagebox.showerror("OSC 连接失败", message)
                    self.log_message(f"OSC 连接失败: {message}")
            except ValueError:
                messagebox.showerror("OSC 错误", "端口号必须是有效的数字")
                self.log_message("OSC 连接失败: 端口号无效")
            except Exception as e:
                messagebox.showerror("OSC 连接失败", str(e))
                self.log_message(f"OSC 连接失败: {e}")

    def toggle_floating_window(self):
        if self.floating_window.is_open():
            self.floating_window.close_window()
        else:
            self.floating_window.create_window()
            self.show_floating_button.config(text="关闭悬浮窗")
            self.lock_button.config(state=tk.NORMAL)
            self.log_message("悬浮窗已显示")
            
    def toggle_floating_lock(self):
        if self.floating_window.is_open():
            self.floating_window.toggle_lock()
            if self.floating_window.is_locked():
                self.lock_button.config(text="解锁悬浮窗")
            else:
                self.lock_button.config(text="锁定悬浮窗")
                
    def floating_window_closed(self):
        self.show_floating_button.config(text="显示悬浮窗")
        self.lock_button.config(text="锁定悬浮窗", state=tk.DISABLED)
        self.log_message("悬浮窗已关闭")

    def on_closing(self):
        """[优化] 退出程序时的清理逻辑"""
        self.should_connect = False
        self.save_settings()
        
        # 优雅停止异步循环
        if self.ble_loop:
            self.ble_loop.call_soon_threadsafe(self.ble_loop.stop)
        if self.api_server: 
            self.api_server.stop()
            
        if self.websocket_server: 
            self.websocket_server.stop()
        self.log_message("正在释放网络资源...")                
        # 给 200ms 时间让线程退出
        self.root.after(200, self._final_destroy)

    def _final_destroy(self):
        """最终销毁步骤"""
        try:
            self.root.destroy()
        except:
            pass
        # os._exit(0) 比 sys.exit(0) 更暴力，能确保所有守护线程彻底消失
        import os
        os._exit(0)
        
    def scan_devices(self):
        """[重构后] 点击扫描按钮触发"""
        from utils import AsyncTaskManager
        
        # 使用通用加载框执行扫描
        AsyncTaskManager.run_with_progress(
            parent=self.root,
            title="蓝牙扫描",
            label_text="正在搜寻附近的蓝牙心率设备，请稍候...",
            # 调用我们在 heart_rate_tool.py 中补全的同步包装器
            task_func=lambda: self.ble_tool.sync_scan_wrapper(timeout=7.0),
            on_complete=self._on_scan_completed
        )

    def _on_scan_completed(self, success, result):
        """扫描任务结束后的回调 (在主线程运行)"""
        if not success:
            messagebox.showwarning("扫描提示", result)
            return
            
        # result 此时就是设备列表，直接传给现有的弹窗函数
        self._show_device_selection(result)

    def _show_device_selection(self, devices):
        """在主线程中弹出选择窗口"""
        if not devices:
            messagebox.showinfo("扫描结果", "附近未发现可连接的蓝牙设备")
            return
        
        selection_window = tk.Toplevel(self.root)
        self.apply_global_icon(selection_window)
        selection_window.title("选择心率设备")
        selection_window.geometry("450x400")
        selection_window.transient(self.root)
        selection_window.grab_set()

        # 布局美化
        main_frame = ttk.Frame(selection_window, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main_frame, text="发现以下设备:", font=("微软雅黑", 10)).pack(anchor=tk.W)

        # 列表框
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Consolas", 10))
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)
        
        # 填充数据
        for device in devices:
            name = device.name if device.name else "Unknown"
            listbox.insert(tk.END, f"{name.ljust(15)} [{device.address}]")
        
        def on_confirm():
            selection = listbox.curselection()
            if selection:
                selected_device = devices[selection[0]]
                # 保存 MAC 地址供连接使用
                self.current_mac = selected_device.address
                # 更新 UI 状态
                self.device_label.config(text=f"已选: {selected_device.name or '未知'}", foreground="#0078d7")
                self.connect_button.config(state=tk.NORMAL)
                self.log_message(f"设备锁定: {selected_device.address}")
                selection_window.destroy()
            else:
                messagebox.showwarning("提示", "请选择一个设备")

        # 底部按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_box := ttk.Frame(btn_frame), text="确定连接", command=on_confirm).pack(side=tk.RIGHT)
        ttk.Button(btn_box, text="取消", command=selection_window.destroy).pack(side=tk.RIGHT, padx=10)
        btn_box.pack(side=tk.RIGHT)

    def _ensure_ble_loop_running(self):
        """确保后台有一个活着的 asyncio 循环线程"""
        if self.ble_thread is None or not self.ble_thread.is_alive():
            self.ble_loop = asyncio.new_event_loop()
            self.ble_thread = threading.Thread(
                target=self._run_async_loop, 
                args=(self.ble_loop,), 
                daemon=True
            )
            self.ble_thread.start()
            self.log_message("系统：后台异步引擎已启动")

    def _run_async_loop(self, loop):
        """异步线程的主循环"""
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def connect_device(self):
        
        if not self.current_mac:
            messagebox.showwarning("连接失败", "请先选择设备")
            return
        if self.connected:
            messagebox.showinfo("连接状态", "设备已连接")
            return

        self.should_connect = True  # 允许开始重连循环
        self._ensure_ble_loop_running()
        # 禁用按钮防止重复点击
        self.connect_button.config(state="disabled")
        self.scan_button.config(state="disabled")
        self.disconnect_button.config(state="normal")
        # 将连接任务安全地推送到异步线程
        # 注意：这里不再使用 AsyncTaskManager 包装连接过程，
        # 因为连接现在是一个“长期运行且会自动重连”的任务。
        asyncio.run_coroutine_threadsafe(
            self.ble_tool.get_heart_rate(self.current_mac, self), 
            self.ble_loop
        )

    def on_heart_rate_update(self, raw_hr):
        """[优化] 处理来自蓝牙线程的 UI 更新请求"""
        # 只有在连接状态下才更新数值，防止断开瞬间的脏数据
        if self.should_connect:
            self.heart_rate_label.config(text=f"心率 : {raw_hr}", fg="#00FF88")
            self.status_label.config(text="● 已连接", fg="#00FF88")
            self.max_hr_display.config(text=f"MAX: {self.max_heart_rate}")
            
            # 视觉报警逻辑
            if hasattr(self, 'webhook_manager'):
                threshold = self.webhook_manager.default_threshold
                if raw_hr >= threshold:
                    self.heart_rate_label.config(bg="#440000") # 高心率变暗红背景
                else:
                    self.heart_rate_label.config(bg="#1A1A1A")

    def _do_connect_task(self):
        """[核心] 供 AsyncTaskManager 调用的同步包装器"""
        import asyncio
        try:
            self.should_stop = False
            # 在子线程开启新的事件循环
            self.ble_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.ble_loop)
            
            # 1. 启动心率监听协程 (它内部会修改 self.connected)
            # 我们将任务放入 loop 但不立即 run_forever，因为我们需要检测是否连接成功
            task = self.ble_loop.create_task(self._run_heart_rate_monitor())
            
            # 2. 等待连接成功的信号 (由 heart_rate_tool 或 _run_heart_rate_monitor 修改)
            import time
            timeout = 10
            start_time = time.time()
            while not self.connected and (time.time() - start_time) < timeout:
                # 运行一下 loop 处理握手包
                self.ble_loop.stop() 
                self.ble_loop.run_forever() 
                time.sleep(0.1)

            if self.connected:
                # 连接成功，让 loop 在子线程继续跑，处理后续心率包
                # 注意：这里需要一个常驻的执行方式
                threading.Thread(target=self.ble_loop.run_forever, daemon=True).start()
                return True, "设备连接成功"
            else:
                return False, "连接超时，未能在规定时间内订阅心率服务"
                
        except Exception as e:
            return False, f"连接异常: {str(e)}"

    def _on_connect_finished(self, success, message):
        """连接结束后的回调 (主线程)"""
        if success:
            self.log_message(f"✅ {message}")
            self.connect_button.config(state=tk.DISABLED)
            self.scan_button.config(state=tk.DISABLED)
            self.disconnect_button.config(state=tk.NORMAL)
            # 触发 Webhook
            if hasattr(self, 'webhook_manager'):
                self.webhook_manager.trigger_event("connected")
        else:
            self.log_message(f"❌ {message}")
            messagebox.showerror("连接失败", message)
            self._on_disconnect() # 恢复按钮初始状态


    async def _run_heart_rate_monitor(self):
        def heart_rate_callback(characteristic, data):
            if self.should_stop: return
            try:
                value = 0
                if len(data) >= 2:
                    if data[0] & 0x01: value = int.from_bytes(data[1:3], byteorder='little')
                    else: value = data[1]
                else:
                    hex_data = data.hex()
                    if '06' in hex_data: value = int(hex_data.split('06')[1], 16)
                if value > 0:
                    self.heart_rate_queue.put(value)
            except Exception as e:
                self.log_message(f"解析心率数据失败: {str(e)}")
        
        self.root.after(0, self._on_connect)
        try:
            await self._run_custom_heart_rate_monitor(self.current_mac, heart_rate_callback)
        finally:
            if not self.should_stop:
                self.root.after(0, self._on_disconnect)

    async def _run_custom_heart_rate_monitor(self, mac, callback):
        from bleak import BleakClient
        # 导入专门的异常类用于精确捕获
        from bleak.exc import BleakDeviceNotFoundError, BleakError
        import asyncio

        disconnected_event = asyncio.Event()

        def disconnected_callback(client):
            self.log_message("设备连接断开")
            disconnected_event.set()
            # 确保 UI 状态同步
            self.root.after(0, self._on_disconnect)

        try:
            # 增加 timeout 保护，防止无限等待
            async with BleakClient(mac, disconnected_callback=disconnected_callback, timeout=15.0) as client:
                self.log_message(f"✅ 成功连接设备: {mac}")
                # 通知 UI 修改按钮状态为“已连接”
                self.root.after(0, self._on_connect)
                
                hr_uuid = await self._find_heart_rate_characteristics(client)
                if hr_uuid:
                    self.log_message(f"找到心率特征: {hr_uuid}")
                    await client.start_notify(hr_uuid, callback)
                    self.log_message("开始接收实时心率数据...")
                    
                    # 保持连接直到主动停止或意外断开
                    while not self.should_stop and not disconnected_event.is_set():
                        await asyncio.sleep(0.5)
                    
                    try: 
                        await client.stop_notify(hr_uuid)
                    except: 
                        pass
                else:
                    self.log_message("❌ 错误：该设备不包含标准心率特征服务。")
                    self.root.after(0, self._on_disconnect)

        except BleakDeviceNotFoundError:
            self.log_message(f"❌ 找不到设备: {mac}。请确认设备已开机并在范围内。")
            self.root.after(0, self._on_disconnect)
        except asyncio.TimeoutError:
            self.log_message(f"❌ 连接超时: {mac}。请尝试靠近设备或重新扫描。")
            self.root.after(0, self._on_disconnect)
        except Exception as e:
            self.log_message(f"❌ 连接发生未知错误: {str(e)}")
            self.root.after(0, self._on_disconnect)


    async def _find_heart_rate_characteristics(self, client):
        uuid_map = { "service": "0000180d-0000-1000-8000-00805f9b34fb", "measurement": "00002a37-0000-1000-8000-00805f9b34fb" }
        for service in client.services:
            if service.uuid.lower() == uuid_map["service"]:
                for char in service.characteristics:
                    if char.uuid.lower() == uuid_map["measurement"]: return char.uuid
        for service in client.services:
            for char in service.characteristics:
                if any(k in char.description.lower() for k in ['heart rate', 'hr']): return char.uuid
        return None

    def _on_connect(self):
        self.connected = True
        self.status_label.config(text="状态: 已连接", fg="green")
        self.log_message("设备连接成功，开始监控心率")
        self.webhook_manager.trigger_event("connected", self.heart_rate)
        # [新增] 连接时广播状态
        if self.websocket_server:
            self.websocket_server.broadcast_heart_rate(self.heart_rate, self.max_heart_rate)
    def disconnect_device(self):
        """[重构] 主动断开连接"""
        self.log_message("正在请求断开连接...")
        self.should_connect = False  # 告诉重连循环：不要再试了
        
        # 即使物理链路还没断，UI 先给反馈
        self.connected = False
        self._on_disconnect()
        # 触发 Webhook
        if hasattr(self, 'webhook_manager'):
            self.webhook_manager.trigger_event("disconnected")       

    def _on_disconnect(self):
        """统一恢复 UI 状态"""
        self.heart_rate = 0
        self.heart_rate_label.config(text="--", fg="#FF3B30", bg="#1A1A1A")
        self.status_label.config(text=" ● 未 连 接 ", fg="gray")
        self.device_label.config(text=f"MAC: {self.current_mac}" if self.current_mac else "未选择设备")
        
        self.connect_button.config(state="normal" if self.current_mac else "disabled")
        self.scan_button.config(state="normal")
        self.disconnect_button.config(state="disabled")

        # 广播给 WebSocket (告诉 OBS 网页心率归零)
        if hasattr(self, 'websocket_server') and self.websocket_server:
            self.websocket_server.broadcast_heart_rate(0, self.max_heart_rate)

    def run(self):
        self.log_message("心率监控器启动")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

def main():
    import multiprocessing
    # [最高优先级] 阻止子进程触发递归启动 exe
    multiprocessing.freeze_support() 
    app = HeartRateMonitor()
    app.run()

if __name__ == "__main__":
    main()
