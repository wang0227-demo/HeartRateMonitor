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
        self.default_low_battery = 20                   # 默认电量低提醒
        # --- 智能过滤状态控制 ---
        self.last_trigger_times: Dict[str, float] = {}  # 记录每个 Webhook 上次触发的时间
        self.default_threshold_low = 60                   # 默认报警阈值
        self.default_threshold_high = 120                 # 默认报警阈值
        self.default_cooldown = 60                     # 默认冷却时间 (秒)
        # --- [新增] 异步队列化核心组件 ---
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        
        self.load_webhooks() # 初始化时即加载
        
    def log_to_response_window(self, message):
        """确保日志输出始终在 Tkinter 主线程执行"""
        def _do_log():
            self.response_log.config(state="normal")
            self.response_log.insert(tk.END, f"> {message}\n")
            self.response_log.see(tk.END)
            self.response_log.config(state="disabled")
        
        self.root.after(0, _do_log) # 跨线程安全调度
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

    def trigger_event(self, event_type: str, heart_rate: int = 0, battery: int = 0, mac: str = ""):
        """ 统一触发事件入口：支持 connected, disconnected, low_battery， heart_rate_updated """
        current_time = time.time() 
        event_map = {
            "connected": "设备已连接",
            "disconnected": "设备已断开",
            "low_battery": "设备电量低",
            "heart_rate_updated": "心率异常"
        }

        for index, config in enumerate(self.webhooks):
            if not config.get("enabled", False):
                continue

            triggers = config.get("triggers", ["heart_rate_updated"])
            if event_type not in triggers:
                continue

            # --- 智能过滤逻辑 ---
            if event_type == "heart_rate_updated":
                # 正常范围内不触发
                threshold_low = config.get("threshold_low", self.default_threshold_low)
                threshold_high = config.get("threshold_high", self.default_threshold_high)
                # 如果心率在正常范围内，不触发
                if threshold_low < heart_rate < threshold_high:
                    continue
                
                # 冷却时间检查
                webhook_id = config.get("name", f"webhook_{index}")
                last_time = self.last_trigger_times.get(webhook_id, 0)
                cooldown = config.get("cooldown", self.default_cooldown)     
                if current_time - last_time < cooldown:
                    continue
                
                # 更新触发时间
                self.last_trigger_times[webhook_id] = current_time

            # --- 智能过滤逻辑 ---
            if event_type == "low_battery":
                if battery > self.default_low_battery:
                    continue

                # 冷却时间检查
                webhook_id = config.get("name", f"webhook_{index}")
                last_time = self.last_trigger_times.get(webhook_id, 0)
                cooldown = config.get("cooldown", self.default_cooldown)     
                if current_time - last_time < cooldown:
                    continue
                
                # 更新触发时间
                self.last_trigger_times[webhook_id] = current_time

            # --- 统一准备并发送任务 (无论什么事件) ---
            event_desc = event_map.get(event_type, event_type)
            # 替换 Body 中的 {event} 变量
            battery_str = str(battery) if battery > 0 else "N/A"
            body_str = config.get("body", "{}").replace("{event}", event_desc).replace("{mac}", mac).replace("{battery}", battery_str)    
            # 投递到异步任务队列 (config, heart_rate, is_test, custom_body, retry_count)
            task_data = (config, heart_rate, False, body_str, 0)
            self.task_queue.put(task_data)
            self.logger(f"[{config.get('name')}] {event_desc} 事件已加入发送队列")

    def _execute_http_request(self, config: Dict, heart_rate: int, is_test: bool = False, 
                          custom_body: Optional[str] = None, retry_count: int = 0):
        webhook_name = config.get("name", "Unknown")
        max_retries = config.get("max_retries", 2)
        retry_delay = 5

        def log_msg(msg):
            if is_test and self.response_logger: self.response_logger(msg)
            else: self.logger(msg)

        try:
            bpm_str = str(heart_rate) if heart_rate > 0 else "N/A"
            url = config.get("url", "").replace("{bpm}", bpm_str)

            # 校验 URL
            if not url.startswith(('http://', 'https://')):
                log_msg(f"[{webhook_name}] 发送失败: URL无效")
                return

            # 准备数据
            headers_str = config.get("headers", "{}").replace("{bpm}", bpm_str)
            body_str = (custom_body if custom_body else config.get("body", "{}")).replace("{bpm}", bpm_str)
            headers = json.loads(headers_str)
            if 'Content-Type' not in headers: 
                headers['Content-Type'] = 'application/json'
            
            data = body_str.encode('utf-8')


            req = request.Request(url, data=data, headers=headers, method='POST')

            # 执行请求
            with request.urlopen(req, timeout=8) as response:
                status = response.status
                log_msg(f"✅ Webhook [{webhook_name}] 发送成功 ({status})")
                # 如果是测试模式，打印出 返回内容方便调试
                if is_test:
                    resp_data = response.read().decode('utf-8', errors='ignore')
                    log_msg(f"服务器返回: {resp_data}")

        except Exception as e:
            if retry_count < max_retries:
                next_retry = retry_count + 1
                log_msg(f"❌ [{webhook_name}] 失败: {e}。{retry_delay}秒后进行第 {next_retry} 次重试")
                threading.Timer(retry_delay, lambda: self.task_queue.put(
                    (config, heart_rate, is_test, custom_body, next_retry)
                )).start()
            else:
                log_msg(f"🚨 [{webhook_name}] 最终失败: {e}")


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
        # 参数顺序对应：(config, heart_rate, battery, is_test, custom_body, retry_count)
        test_body = config.get("body", "{}").replace("{event}", "测试事件").replace("{bpm}", "88").replace("{battery}", "20")
        task_data = (config, 88, 20, True, test_body, 0)
        self.task_queue.put(task_data)
        self.logger(f"[{config.get('name')}] 测试请求已加入队列")

    def save_webhooks(self):
        """ 将当前 Webhook 列表保存到本地 config_webhook.json"""
        try:
            with open(WEBHOOK_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.webhooks, f, indent=4, ensure_ascii=False)
            self.logger(f"配置已同步至本地文件。")
        except IOError as e:
            self.logger(f"保存配置文件失败: {e}")

import requests
import hashlib
import subprocess
import hmac
import base64
import time
import json
import re
from datetime import datetime
from utils import CURRENT_VERSION

class UserTracker:
    # 填入你从飞书机器人后台获取的 Secret
    WEBHOOK_SECRET = "ibXsLlfiNu2rTSat3CjANg"  

    @staticmethod
    def gen_sign(secret, timestamp):
        """生成飞书签名校验字符串"""
        string_to_sign = f'{timestamp}\n{secret}'
        hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        return base64.b64encode(hmac_code).decode('utf-8')

    @staticmethod
    def get_info():
        """获取机器码和地理位置"""
        # 1. 机器码
        try:
            cmd = "wmic csproduct get uuid"
            mid_raw = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip().split('\n')[-1].strip()
            mid = hashlib.md5(mid_raw.encode()).hexdigest().upper()[:12]
        except:
            mid = "UNKNOWN"

        # 2. 地理位置
        loc = "未知"
        try:
            # 修正了 pconline 的返回解析，它默认返回文本，通常需要指定 json 或 text
            r = requests.get("https://whois.pconline.com.cn/ipJson.jsp?json=true", timeout=2)
            loc = f"{r.json().get('city')}"
        except:
            r = requests.get("https://api.ip.sb/geoip", timeout=2)
            loc = f"{r.json().get('city')}"
            pass
        return mid, loc


    @staticmethod
    def send_to_feishu(webhook_url):
        """发送统计卡片"""
        mid, loc = UserTracker.get_info()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 生成时间戳和签名
        ts = str(int(time.time()))
        signature = UserTracker.gen_sign(UserTracker.WEBHOOK_SECRET, ts)
        
        payload = {
            "timestamp": ts,      # 对应顶层字段
            "sign": signature,     # 对应顶层字段
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": "🔔 HeartRateMonitor - 用户上线"},
                    "template": "green"
                },
                "elements": [
                    {
                        "tag": "div",
                        "fields": [
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**用户ID:**\n{mid}"}},
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**地理位置:**\n{loc}"}},
                            {"is_short": False, "text": {"tag": "lark_md", "content": f"**上线时间:**\n{now}"}}
                        ]
                    },
                    {"tag": "hr"},
                    {"tag": "note", "elements": [{"tag": "plain_text", "content": f"HeartRateMonitor版本: {CURRENT_VERSION}"}]}
                ]
            }
        }
        
        try:
            r = requests.post(webhook_url, json=payload, timeout=5)
            #print(r.json()) # 调试时可以打开，查看是否报错
        except Exception as e:
            pass
            #print(f"发送失败: {e}") # 调试时可以打开，查看是否报错
