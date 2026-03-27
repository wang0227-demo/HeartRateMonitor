# webhook_ui.py

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import json
import threading
from typing import Optional

class WebhookWindow(tk.Toplevel):
    """
    Webhook 管理的独立窗口
    """
    def __init__(self, monitor_instance, webhook_manager):
        super().__init__(monitor_instance.root)
        self.webhook_manager = webhook_manager
        self.selected_index: Optional[int] = None
        
        # 继承主窗口图标
        if hasattr(monitor_instance, 'apply_global_icon'):
            monitor_instance.apply_global_icon(self)

        self.title("Webhook 联动设置")
        self.geometry("850x700") 
        self.minsize(700, 600)
        self.transient(monitor_instance.root)
        self.grab_set()

        # --- 数据变量 ---
        self.enabled_var = tk.BooleanVar(value=True)
        self.name_var = tk.StringVar()
        self.url_var = tk.StringVar()
        self.trigger_connect_var = tk.BooleanVar(value=False)
        self.trigger_disconnect_var = tk.BooleanVar(value=False)
        self.trigger_hr_update_var = tk.BooleanVar(value=True)
        self.threshold_low_var = tk.StringVar(value="60")
        self.threshold_high_var = tk.StringVar(value="120")
        self.cooldown_var = tk.StringVar(value="60")

        self._setup_ui()
        self.load_webhooks_into_listbox()
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _setup_ui(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # --- 左侧：列表区域 ---
        list_frame = ttk.LabelFrame(main_frame, text="Webhook 预设列表", padding="10")
        list_frame.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        
        self.listbox = tk.Listbox(list_frame, width=25, exportselection=False, font=("Microsoft YaHei", 9))
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_listbox_select)
        
        btn_grid = ttk.Frame(list_frame)
        btn_grid.pack(fill=tk.X, pady=(10,0))
        ttk.Button(btn_grid, text="新增", command=self.new_webhook).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0,2))
        self.delete_button = ttk.Button(btn_grid, text="删除", command=self.delete_webhook, state=tk.DISABLED)
        self.delete_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2,0))
        
        ttk.Button(list_frame, text="🔄 同步官方预设", command=self.sync_webhooks).pack(fill=tk.X, pady=(5,0))

        # --- 右侧：编辑区域 ---
        edit_scroll = ttk.Frame(main_frame)
        edit_scroll.grid(row=0, column=1, sticky="nsew")
        
        details_frame = ttk.LabelFrame(edit_scroll, text="配置详情", padding="15")
        details_frame.pack(fill=tk.BOTH, expand=True)
        details_frame.columnconfigure(1, weight=1)

        # 基础信息
        ttk.Checkbutton(details_frame, text="启用此 Webhook", variable=self.enabled_var).grid(row=0, column=0, columnspan=2, sticky="w")
        
        ttk.Label(details_frame, text="名称:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(details_frame, textvariable=self.name_var).grid(row=1, column=1, sticky="ew", padx=5)
        
        ttk.Label(details_frame, text="URL:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(details_frame, textvariable=self.url_var).grid(row=2, column=1, sticky="ew", padx=5)

        # 触发器设置
        trig_frame = ttk.LabelFrame(details_frame, text="触发场景", padding=10)
        trig_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Checkbutton(trig_frame, text="设备连接时", variable=self.trigger_connect_var).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(trig_frame, text="设备断开时", variable=self.trigger_disconnect_var).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(trig_frame, text="心率刷新时", variable=self.trigger_hr_update_var).pack(side=tk.LEFT, padx=10)

        # 智能过滤设置
        filter_frame = ttk.LabelFrame(details_frame, text="心率报警过滤 (仅限心率刷新触发)", padding=10)
        filter_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Label(filter_frame, text="报警阈值Low ≤").pack(side=tk.LEFT)
        ttk.Entry(filter_frame, textvariable=self.threshold_low_var, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Label(filter_frame, text="报警阈值High ≥").pack(side=tk.LEFT)
        ttk.Entry(filter_frame, textvariable=self.threshold_high_var, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Label(filter_frame, text="冷却时间 (秒)").pack(side=tk.LEFT, padx=(15, 0))
        ttk.Entry(filter_frame, textvariable=self.cooldown_var, width=8).pack(side=tk.LEFT, padx=5)

        # JSON 编辑区
        ttk.Label(details_frame, text="Body (JSON):").grid(row=5, column=0, sticky="nw", pady=(10,0))
        self.body_text = tk.Text(details_frame, height=8, font=("Consolas", 9))
        self.body_text.grid(row=5, column=1, sticky="nsew", padx=5, pady=(10,0))
        
        ttk.Label(details_frame, text="Headers (JSON):").grid(row=6, column=0, sticky="nw", pady=10)
        self.headers_text = tk.Text(details_frame, height=4, font=("Consolas", 9))
        self.headers_text.grid(row=6, column=1, sticky="nsew", padx=5, pady=10)
        
        ttk.Label(details_frame, text="变量: {bpm} 心率数字, {event} 事件描述", foreground="gray").grid(row=7, column=1, sticky="w")

        # 日志区
        log_frame = ttk.LabelFrame(main_frame, text="测试响应日志", padding=5)
        log_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10,0))
        self.response_log = scrolledtext.ScrolledText(log_frame, height=6, font=("Consolas", 9), state="disabled", bg="#f0f0f0")
        self.response_log.pack(fill=tk.BOTH, expand=True)

        # 底部按钮
        btn_box = ttk.Frame(main_frame)
        btn_box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10,0))
        ttk.Button(btn_box, text="测试发送", command=self.test_webhook).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_box, text="💾 保存并应用", command=self.save_webhook).pack(side=tk.RIGHT)

        # 绑定日志输出
        self.webhook_manager.response_logger = self.log_to_response_window

    def load_webhooks_into_listbox(self):
        self.listbox.delete(0, tk.END)
        for hook in self.webhook_manager.get_webhooks():
            status = "●" if hook.get("enabled") else "○"
            self.listbox.insert(tk.END, f"{status} {hook.get('name', '未命名')}")

    def on_listbox_select(self, event=None):
        indices = self.listbox.curselection()
        if not indices: return
        self.selected_index = indices[0]
        self.delete_button.config(state=tk.NORMAL)
        
        config = self.webhook_manager.get_webhooks()[self.selected_index]
        self.enabled_var.set(config.get("enabled", True))
        self.name_var.set(config.get("name", ""))
        self.url_var.set(config.get("url", ""))
        
        # 触发器回填
        trigs = config.get("triggers", ["heart_rate_updated"])
        self.trigger_connect_var.set("connected" in trigs)
        self.trigger_disconnect_var.set("disconnected" in trigs)
        self.trigger_hr_update_var.set("heart_rate_updated" in trigs)
        
        # 过滤参数回填
        self.threshold_low_var.set(str(config.get("threshold_low", 60)))
        self.threshold_high_var.set(str(config.get("threshold_high", 120)))
        self.cooldown_var.set(str(config.get("cooldown", 60)))
        
        # 文本回填
        self.body_text.delete("1.0", tk.END)
        body_content = config.get("body", "{}").strip()
        self.body_text.insert("1.0", body_content)
        self.headers_text.delete("1.0", tk.END)
        self.headers_text.insert("1.0", config.get("headers", '{"Content-Type": "application/json"}'))

    def save_webhook(self):
        # 构造触发器列表
        trigs = []
        if self.trigger_connect_var.get(): trigs.append("connected")
        if self.trigger_disconnect_var.get(): trigs.append("disconnected")
        if self.trigger_hr_update_var.get(): trigs.append("heart_rate_updated")

        body_raw = self.body_text.get("1.0", tk.END).strip()
        headers_raw = self.headers_text.get("1.0", tk.END).strip()

        # 校验 JSON
        try:
            # 校验 Body：先尝试直接解析，如果报错，尝试替换变量后再解析（模拟运行环境）
            if body_raw:
                test_body = body_raw.replace("{bpm}", "0").replace("{event}", "test")
                json.loads(test_body)
            
            # 校验 Headers
            if headers_raw:
                test_headers = headers_raw.replace("{bpm}", "0")
                json.loads(test_headers)
        except json.JSONDecodeError as e:
            messagebox.showerror("格式错误", f"JSON 格式无效，请检查 Body 或 Headers。\n\n错误信息: {e}")
            return

        config = {
            "enabled": self.enabled_var.get(),
            "name": self.name_var.get().strip() or "未命名",
            "url": self.url_var.get().strip(),
            "triggers": trigs,
            "threshold_low": int(self.threshold_low_var.get() or 60),
            "threshold_high": int(self.threshold_high_var.get() or 120),
            "cooldown": int(self.cooldown_var.get() or 60),
            "body": body_raw or "{}",
            "headers": headers_raw or "{}"
        }

        self.webhook_manager.save_webhook(self.selected_index, config)
        self.load_webhooks_into_listbox()
        if self.selected_index is not None:
            self.listbox.selection_set(self.selected_index)
        else:
            self.listbox.selection_set(tk.END)
        messagebox.showinfo("成功", f"Webhook '{config['name']}' 已保存并生效")    
        self.log_to_response_window(f">>> 已保存 Webhook: {config['name']}")

    def new_webhook(self):
        self.selected_index = None

        self.listbox.selection_clear(0, tk.END)
        # 重置 UI 变量为默认值
        self.enabled_var.set(True)
        self.name_var.set("新 Webhook")
        self.url_var.set("http://")
        self.trigger_connect_var.set(False)
        self.trigger_disconnect_var.set(False)
        self.trigger_hr_update_var.set(True)
        self.threshold_low_var.set("60")
        self.threshold_high_var.set("120")
        self.cooldown_var.set("60")
        self.body_text.delete("1.0", tk.END)
        self.body_text.insert("1.0", '{"event": "{event}", "bpm": "{bpm}"}')
        self.headers_text.delete("1.0", tk.END)
        self.headers_text.insert("1.0", '{"Content-Type": "application/json"}')
        
        self.delete_button.config(state=tk.DISABLED)

    def delete_webhook(self):
        """删除当前选中的配置"""
        if self.selected_index is None:
            return
            
        if messagebox.askyesno("确认删除", "确定要删除此 Webhook 配置吗？"):
            self.webhook_manager.delete_webhook(self.selected_index)
            self.selected_index = None
            self.load_webhooks_into_listbox()
            self.new_webhook() # 清空右侧编辑区

    def sync_webhooks(self):
        """从 GitHub 同步预设"""
        from utils import AsyncTaskManager # 确保导入了工具类
        
        if messagebox.askokcancel("同步提示", "同步将覆盖本地已有的同名配置，是否继续？"):
            # 使用异步任务管理器启动带进度条的弹窗
            AsyncTaskManager.run_with_progress(
                parent=self,
                title="同步预设",
                label_text="正在连接服务器并下载最新的 Webhook 配置...",
                # 传入执行任务的函数（要求返回 success, msg）
                task_func=self.webhook_manager.sync_from_github,
                # 任务完成后的回调逻辑
                on_complete=self._on_sync_done
            )

    def _on_sync_done(self, success, msg):
        """同步完成后的界面刷新"""
        if success:
            self.load_webhooks_into_listbox()
            messagebox.showinfo("同步成功", "预设已成功更新并加载到列表。")
        else:
            messagebox.showerror("同步失败", f"无法同步配置：\n{msg}")

    def test_webhook(self):
        """测试当前编辑中的配置（不要求先保存）"""
        url = self.url_var.get().strip()
        if not url or url == "http://":
            messagebox.showwarning("警告", "请输入有效的 URL 再进行测试")
            return
            
        # 构造临时配置用于测试
        trigs = []
        if self.trigger_connect_var.get(): trigs.append("connected")
        # ... (此处逻辑同 save_webhook 中的构造)
        
        config = {
            "name": self.name_var.get() or "测试预览",
            "url": url,
            "body": self.body_text.get("1.0", tk.END).strip(),
            "headers": self.headers_text.get("1.0", tk.END).strip()
        }
        
        self.log_to_response_window(f"正在发送测试请求至: {url}...")
        self.webhook_manager.test_webhook(config)

    def log_to_response_window(self, message):
        """将 Webhook 的返回结果显示在 UI 下方的日志区"""
        self.response_log.config(state="normal")
        self.response_log.insert(tk.END, f"> {message}\n")
        self.response_log.see(tk.END)
        self.response_log.config(state="disabled")

    def on_closing(self):
        """关闭窗口时的清理"""
        self.webhook_manager.response_logger = None # 解绑日志，防止报错
        self.grab_release()
        self.destroy()
        