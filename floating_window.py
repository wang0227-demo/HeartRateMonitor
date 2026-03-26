# floating_window.py

import tkinter as tk
import re
from typing import Optional
from PIL import Image, ImageTk, ImageSequence
from utils import get_resource_path
class FloatingWindow:
    """
    悬浮窗类
    - 支持使用 {bpm} 和 {img} 占位符自定义显示格式。
    - 支持加载并显示图片（包括动图 GIF/WebP）。
    """
    def __init__(self, heart_rate_monitor):
        self.heart_rate_monitor = heart_rate_monitor
        self.window: Optional[tk.Toplevel] = None
        self.locked = False
        
        self.last_geometry = "200x80+100+100"
        self.display_format = "{img}{bpm}"
        self.lift_counter = 0

        # 图片相关属性
        self.image_path: Optional[str] = None
        self.frames_original: list[Image.Image] = []  # 原始图片帧列表
        self.image_tk_list: list[ImageTk.PhotoImage] = [] # 缩放后的 Tk 图片对象列表
        self.current_frame_idx = 0
        self.frame_duration = 100 # 默认帧间隔
        self.ani_timer_id = None  # 定时器 ID

        self.unlocked_color = "#00FF00"
        self.locked_color = "#FF6600"

        self.content_frame: Optional[tk.Frame] = None
        self.display_widgets: list[dict] = []
        self.bpm_label: Optional[tk.Label] = None

    def _keep_on_top(self):
        """置顶守护：每秒检查一次，防止被非全屏独占的游戏覆盖"""
        if self.window and self.window.winfo_exists():
            if self.locked:
                self.window.lift()
                self.window.attributes("-topmost", True)
            # 持续运行守护逻辑，保存定时器 ID 以便关闭时清理
            self.ani_timer_id_top = self.window.after(1000, self._keep_on_top)

    def create_window(self):
        if self.window:
            return
            
        self.window = tk.Toplevel(self.heart_rate_monitor.root)
        self.heart_rate_monitor.apply_global_icon(self.window)
        self.window.title("心率")
        self.window.geometry(self.last_geometry)
        #禁止窗口根据内容自动缩放 (防止变回小点)
        self.window.pack_propagate(False)
        # --- 核心修改：移除窗口本身的边框和外边距 ---
        self.window.config(bg="#000001", bd=0, highlightthickness=0)
        # 内容容器也同步设为 0 边距
        self.content_frame = tk.Frame(self.window, bg="#000001", bd=0, highlightthickness=0)
        self.content_frame.pack_propagate(False) # 重点：固定内部容器大小
        self.content_frame.pack(expand=True, fill="both")
        
        self.rebuild_display()
        self.bind_events()
        self.window.protocol("WM_DELETE_WINDOW", self.close_window)
        self.apply_lock_state()
        self._keep_on_top() # 启动守护逻辑

    def rebuild_display(self):
        """重新构建悬浮窗内容"""
        if not self.content_frame:
            return

        # 清理旧定时器
        if self.ani_timer_id:
            self.window.after_cancel(self.ani_timer_id)
            self.ani_timer_id = None

        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        self.display_widgets = []
        self.bpm_label = None

        # 核心：使用一个内部容器来辅助居中，避免直接在 content_frame 堆挤
        inner_container = tk.Frame(self.content_frame, bg="#000001")
        inner_container.place(relx=0.5, rely=0.5, anchor=tk.CENTER) # 绝对居中
        
        parts = re.split(r'({img}|{bpm})', self.display_format)

        for part in parts:
            if not part: continue
            spacing = 10 # 设置统一的左右间距
            if part == "{bpm}":
                label = tk.Label(inner_container, text="--", bg="#000001")
                label.pack(side=tk.LEFT, padx=spacing) # 增加 padx
                self.bpm_label = label
                self.display_widgets.append({'type': 'bpm', 'widget': label})
            elif part == "{img}":
                label = tk.Label(inner_container, bg="#000001")
                label.pack(side=tk.LEFT, padx=spacing) # 增加 padx
                self.display_widgets.append({'type': 'img', 'widget': label})
            else:
                label = tk.Label(inner_container, text=part, bg="#000001")
                label.pack(side=tk.LEFT, padx=2) # 普通文字间距略小
                self.display_widgets.append({'type': 'text', 'widget': label})
        
        self._update_font_size()
        self.apply_lock_state()
        self.update_heart_rate(self.heart_rate_monitor.heart_rate)

    def _update_font_size(self, event=None):
        """处理字体缩放和图片帧缩放 (优化稳定性版)"""
        if not self.window: return
            
        height = self.window.winfo_height()
        new_size = max(10, int(height / 2.5))
        
        bpm_font = ("Arial", new_size, "bold")
        text_font = ("TkDefaultFont", new_size)

        # [优化]：如果正在播放动画，先暂停定时器，防止缩放过程中索引越界
        if self.ani_timer_id:
            self.window.after_cancel(self.ani_timer_id)
            self.ani_timer_id = None

        # [修复]：清空旧图片引用，释放内存
        self.image_tk_list.clear()
        
        if self.frames_original and "{img}" in self.display_format:
            try:
                img_h = int(height * 0.5)
                if img_h > 0:
                    # 重新生成缩放后的图片帧
                    for frame in self.frames_original:
                        ratio = img_h / frame.height
                        img_w = int(frame.width * ratio)
                        if img_w > 0:
                            resized = frame.resize((img_w, img_h), Image.Resampling.LANCZOS)
                            self.image_tk_list.append(ImageTk.PhotoImage(resized))
            except Exception as e:
                self.heart_rate_monitor.log_message(f"图片缩放失败: {e}")

        # 应用字体和首帧图片
        for item in self.display_widgets:
            widget = item['widget']
            if item['type'] == 'img':
                if self.image_tk_list:
                    widget.config(image=self.image_tk_list[0])
            elif item['type'] == 'bpm':
                widget.config(font=bpm_font)
            elif item['type'] == 'text':
                widget.config(font=text_font)

        # 重新启动动画循环
        if len(self.image_tk_list) > 1:
            self.current_frame_idx = 0 # 重置索引防止越界
            self._play_animation()

    def _play_animation(self):
        """动图播放循环"""
        if not self.window or len(self.image_tk_list) <= 1:
            return

        # 更新所有图片槽位
        for item in self.display_widgets:
            if item['type'] == 'img':
                item['widget'].config(image=self.image_tk_list[self.current_frame_idx])

        self.current_frame_idx = (self.current_frame_idx + 1) % len(self.image_tk_list)
        
        # 清除之前的定时器，防止叠加跑得过快
        if self.ani_timer_id:
            self.window.after_cancel(self.ani_timer_id)
        
        self.ani_timer_id = self.window.after(self.frame_duration, self._play_animation)

    def set_image(self, path: Optional[str]):
        """设置图片并提取所有帧"""
        # 1. 清理旧数据和定时器
        self.frames_original.clear() 
        self.image_tk_list.clear()
        if self.ani_timer_id:
            try:
                self.window.after_cancel(self.ani_timer_id)
            except:
                pass
            self.ani_timer_id = None

        self.image_path = path
        self.current_frame_idx = 0
        
        # 2. 加载新图片
        if path:
            try:
                with Image.open(path) as img:
                    # 提取所有帧并转为 RGBA
                    self.frames_original = [f.copy().convert("RGBA") for f in ImageSequence.Iterator(img)]
                    # 获取帧间隔
                    self.frame_duration = img.info.get('duration', 100)
                    if self.frame_duration < 20: 
                        self.frame_duration = 100
            except Exception as e:
                self.frames_original = []
                self.heart_rate_monitor.log_message(f"加载图片失败: {e}")
        
        # 3. 如果窗口已打开，重新构建显示
        if self.is_open():
            self.rebuild_display()

    def update_format(self, new_format: str):
        """更新显示格式"""
        self.display_format = new_format
        if self.is_open():
            self.rebuild_display()

    def bind_events(self):
        if not self.window: return
        self.window.bind("<Configure>", self._update_font_size)

    def update_heart_rate(self, heart_rate):
        if self.is_open() and self.bpm_label:
            text = str(heart_rate) if heart_rate > 0 else "--"
            self.bpm_label.config(text=text)

    def close_window(self):
        """关闭悬浮窗并清理所有后台定时器"""
        if self.window:
            # 1. 取消所有 after 定时器 (置顶守护和动图播放)
            if hasattr(self, 'ani_timer_id_top') and self.ani_timer_id_top:
                self.window.after_cancel(self.ani_timer_id_top)
            if hasattr(self, 'ani_timer_id') and self.ani_timer_id:
                self.window.after_cancel(self.ani_timer_id)
            
            # 2. 保存当前窗口位置以便下次恢复
            try:
                self.last_geometry = self.window.geometry()
            except:
                pass
                
            # 3. 销毁窗口并重置状态
            self.window.destroy()
            self.window = None
            
            # 4. 通知主程序更新 UI 状态
            self.heart_rate_monitor.floating_window_closed()
            
    def is_open(self):
        return self.window is not None

    def apply_lock_state(self):
        """应用锁定/解锁状态的视觉与系统表现"""
        if not self.window or not self.content_frame:
            return

        if self.locked:
            # 锁定状态：无边框、强制置顶、点击穿透（透明色）
            color = self.locked_color
            self.window.overrideredirect(True) # 去掉标题栏
            self.window.attributes("-topmost", True)
            # 强制刷新透明色和边框状态
            self.window.config(bd=0, highlightthickness=0)
            self.window.attributes("-transparentcolor", "#000001") # 黑色背景变为透明
        else:
            # 解锁状态：恢复边框、取消置顶、取消透明
            color = self.unlocked_color
            self.window.overrideredirect(False)
            self.window.attributes("-topmost", False)
            self.window.attributes("-transparentcolor", "")
            # 解锁时可以恢复一点边框感方便拖动（可选）
            self.window.config(bd=1, highlightthickness=1, highlightbackground="gray")
        
        # 刷新所有组件的文字颜色
        for item in self.display_widgets:
            widget = item['widget']
            if item['type'] == 'bpm':
                widget.config(fg=color)
            elif item['type'] == 'text':
                widget.config(fg=self.unlocked_color)

    def is_locked(self):
        """检查悬浮窗是否被锁定"""
        return self.locked

    def toggle_lock(self):
        """切换锁定状态并立即生效"""
        self.locked = not self.locked
        self.apply_lock_state()
