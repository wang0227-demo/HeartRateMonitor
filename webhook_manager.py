# webhook_manager.py

import threading
import queue
import json
import os
import time
from urllib import request, error
from typing import Callable, Optional, List, Dict

# 定义 Webhook 的独立配置文件
WEBHOOK_CONFIG_FILE = "config_webhook.json"
# 定义 GitHub 仓库中的预设文件 URL
GITHUB_CONFIG_URL = "https://ghproxy.net/https://raw.githubusercontent.com/wang0227-demo/demo/refs/heads/main/config_webhook.json"

class WebhookManager:
    """
    管理所有 Webhook 的加载、保存和智能过滤发送。
    支持高心率阈值报警和冷却时间机制。
    """
    def __init__(self, logger_func: Callable[[str], None], response_logger: Optional[Callable[[str], None]] = None):
        self.logger = logger_func
        self.response_logger = response_logger
        self.webhooks: List[Dict] = []
        
        # --- 智能过滤状态控制 ---
        self.last_trigger_times: Dict[str, float] = {}  # 记录每个 Webhook 上次触发的时间
        self.default_threshold = 120                   # 默认报警阈值
        self.default_cooldown = 60                     # 默认冷却时间 (秒)
        # --- [新增] 异步队列化核心组件 ---
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        
        self.load_webhooks() # 初始化时即加载

    def load_webhooks(self):
        """从 config_webhook.json 加载 Webhook 列表"""
        if not os.path.exists(WEBHOOK_CONFIG_FILE):
            self.webhooks = []
            self.logger("未找到 Webhook 配置文件，已初始化为空列表。")
            return
        try:
            with open(WEBHOOK_CONFIG_FILE, "r", encoding="utf-8") as f:
                self.webhooks = json.load(f)
            self.logger(f"从 {WEBHOOK_CONFIG_FILE} 加载了 {len(self.webhooks)} 个 Webhook 配置。")
        except (json.JSONDecodeError, IOError) as e:
            self.webhooks = []
            self.logger(f"加载 {WEBHOOK_CONFIG_FILE} 失败: {e}")

    def get_webhooks(self) -> List[Dict]:
        """[修复报错] 获取所有 Webhook 配置"""
        return self.webhooks

    def save_webhook(self, index: Optional[int], config: Dict):
        """[修复报错] 保存或新增一个 Webhook 配置"""
        if index is None:
            self.webhooks.append(config)
            self.logger(f"新增 Webhook: {config.get('name')}")
        else:
            # 注意：UI 传过来的 index 可能是元组 (0,)，需要转成整数
            idx = index[0] if isinstance(index, (tuple, list)) else index
            if 0 <= idx < len(self.webhooks):
                self.webhooks[idx] = config
                self.logger(f"更新 Webhook: {config.get('name')}")
        self.save_webhooks() # 调用持久化保存到文件

    def delete_webhook(self, index: int):
        """[修复报错] 删除一个 Webhook 配置"""
        # 处理 Tkinter 传过来的元组索引
        idx = index[0] if isinstance(index, (tuple, list)) else index
        if 0 <= idx < len(self.webhooks):
            removed = self.webhooks.pop(idx)
            self.logger(f"已删除 Webhook: {removed.get('name')}")
            self.save_webhooks() # 保存更改

    def _worker_loop(self):
        """常驻后台线程：负责从队列取任务并执行请求"""
        while True:
            try:
                # 获取任务 (config, heart_rate, is_test, body)
                task = self.task_queue.get()
                self._execute_http_request(*task)
                self.task_queue.task_done()
            except Exception as e:
                self.logger(f"[WebhookWorker] 严重错误: {e}")

    def trigger_event(self, event_type: str, heart_rate: int = 0):
        """
        根据事件类型触发匹配的 Webhook。
        增加了心率阈值过滤和冷却时间检查。
        """
        """重写触发逻辑：改为向队列投递任务"""
        current_time = time.time()
        
        event_map = {
            "connected": "设备已连接",
            "disconnected": "设备已断开",
            "heart_rate_updated": f"⚠️ 高心率报警: {heart_rate}bpm"
        }

        for index, config in enumerate(self.webhooks):
            if not config.get("enabled", False):
                continue

            triggers = config.get("triggers", ["heart_rate_updated"])
            if event_type not in triggers:
                continue

            # --- 智能过滤逻辑 ---
            if event_type == "heart_rate_updated":
                # 1. 检查阈值：如果当前心率低于配置的阈值，则跳过
                threshold = config.get("threshold", self.default_threshold)
                if heart_rate < threshold:
                    continue
                
                # 2. 检查冷却时间：防止频繁发送
                webhook_id = config.get("name", f"webhook_{index}")
                last_time = self.last_trigger_times.get(webhook_id, 0)
                cooldown = config.get("cooldown", self.default_cooldown)
                
                if current_time - last_time < cooldown:
                    continue
                
                # 符合条件，更新触发时间
                self.last_trigger_times[webhook_id] = current_time
                self.logger(f"[{config.get('name')}] 满足触发条件: 心率 {heart_rate} >= {threshold}")

            # --- 准备并发送请求 ---
            body_str = config.get("body", "{}").replace("{event}", event_map.get(event_type, event_type))
            task_data = (config, heart_rate, False, body_str, 0)
            self.task_queue.put(task_data)
            self.logger(f"[{config.get('name')}] 已加入发送队列")

    def _execute_http_request(self, config: Dict, heart_rate: int, is_test: bool = False, 
                      custom_body: Optional[str] = None, retry_count: int = 0):
        """
        执行 HTTP POST 请求，并在失败时自动重试。
        retry_count: 当前重试次数
        """
        """被 worker_loop 调用，执行具体的网络 IO"""
        webhook_name = config.get("name", "Unknown")
        max_retries = config.get("max_retries", 2)  # 默认失败后重试 2 次
        retry_delay = 5  # 失败后等待 5 秒重试

        def log_msg(msg):
            if is_test and self.response_logger: self.response_logger(msg)
            else: self.logger(msg)

        try:
            bpm_str = str(heart_rate) if heart_rate > 0 else "N/A"
            url = config.get("url", "").replace("{bpm}", bpm_str)
            
            if not url.startswith(('http://', 'https://')):
                log_msg(f"[{webhook_name}] 发送失败: URL无效")
                return

            headers_str = config.get("headers", "{}").replace("{bpm}", bpm_str)
            body_str = (custom_body if custom_body else config.get("body", "{}")).replace("{bpm}", bpm_str)

            headers = json.loads(headers_str)
            if 'Content-Type' not in headers: headers['Content-Type'] = 'application/json'
            
            data = body_str.encode('utf-8')
            req = request.Request(url, data=data, headers=headers, method='POST')

            with request.urlopen(req, timeout=8) as response:
                status = response.status
                log_msg(f"✅ Webhook [{webhook_name}] 发送成功 ({status})")

                resp_data = response.read().decode('utf-8', errors='ignore')
                log_msg(f"✅ Webhook [{webhook_name}] 发送成功 ({response.status})")
        
        except Exception as e:
            # 判断是否需要重试
            if retry_count < max_retries:
                next_retry = retry_count + 1
                log_msg(f"❌ Webhook [{webhook_name}] 失败: {str(e)}。将在 {retry_delay}秒后进行第 {next_retry} 次重试({next_retry}/{max_retries})")
                
                # 使用 Timer 在指定延迟后重新开启线程执行发送，不阻塞当前线程
                # 巧妙处理：使用 Timer 在 5 秒后将任务重新放入队列末尾
                threading.Timer(retry_delay, lambda: self.task_queue.put(
                    (config, heart_rate, is_test, custom_body, next_retry)
                )).start()
            else:
                log_msg(f"🚨 Webhook [{webhook_name}] 最终发送失败，已达最大重试次数 ({max_retries})。错误: {str(e)}")

    def sync_from_github(self) -> tuple[bool, str]:
        """从 GitHub 下载最新的预设配置文件"""
        try:
            req = request.Request(GITHUB_CONFIG_URL, headers={'User-Agent': 'HeartRateMonitor-App'})
            with request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    content = response.read().decode('utf-8')
                    json.loads(content) # 验证JSON格式
                    with open(WEBHOOK_CONFIG_FILE, "w", encoding="utf-8") as f:
                        f.write(content)
                    self.load_webhooks()
                    return True, "同步成功"
        except Exception as e:
            return False, f"同步失败: {e}"

    def test_webhook(self, config: Dict):
        """立即测试单个 Webhook（不进冷却和阈值逻辑）"""
        # 参数顺序对应：(config, heart_rate, is_test, custom_body, retry_count)
        test_body = config.get("body", "{}").replace("{event}", "测试事件").replace("{bpm}", "88")
        task_data = (config, 88, True, test_body, 0)
        self.task_queue.put(task_data)
        self.logger(f"[{config.get('name')}] 测试请求已加入队列")

    def save_webhooks(self):
        """[核心补全] 将当前 Webhook 列表保存到本地 config_webhook.json"""
        try:
            with open(WEBHOOK_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.webhooks, f, indent=4, ensure_ascii=False)
            self.logger(f"配置已同步至本地文件。")
        except IOError as e:
            self.logger(f"保存配置文件失败: {e}")

