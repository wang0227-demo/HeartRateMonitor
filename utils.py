# utils.py

import os
import sys
import tkinter as tk
from tkinter import ttk
import threading

def get_resource_path(relative_path):
    """ 获取程序运行时的绝对路径 """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)
ICON_PATH = get_resource_path("resources/logo.ico")
CURRENT_VERSION = "1.1.0"

class AsyncTaskManager:
    """通用异步任务管理器：提供带进度条的模态弹窗"""
    
    @staticmethod
    def run_with_progress(parent, title, label_text, task_func, on_complete):
        """
        task_func: 执行的任务，需返回 (success, message)
        on_complete: 任务结束后的回调，接收 (success, message)
        """
        # 创建弹窗
        popup = tk.Toplevel(parent)
        popup.iconbitmap(ICON_PATH)
        popup.title(title)
        popup.geometry("320x130")
        popup.resizable(False, False)
        popup.transient(parent)
        popup.grab_set()  # 锁定父窗口

        # 居中逻辑
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 160
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 65
        popup.geometry(f"+{max(0, x)}+{max(0, y)}")

        # UI 布局
        ttk.Label(popup, text=label_text, padding=15, wraplength=280).pack()
        progress = ttk.Progressbar(popup, mode='indeterminate', length=240)
        progress.pack(pady=5)
        progress.start(10)

        def _worker():
            try:
                # 执行耗时操作
                success, result = task_func()
                # 安全回到主线程关闭 UI 并回调
                parent.after(0, lambda: _cleanup(success, result))
            except Exception as e:
                parent.after(0, lambda: _cleanup(False, f"程序错误: {e}"))

        def _cleanup(success, result):
            if popup.winfo_exists():
                popup.grab_release()
                popup.destroy()
            on_complete(success, result)

        # 开启线程执行任务
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
