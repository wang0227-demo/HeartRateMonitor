# api_server.py

import http.server
import socketserver
import threading
import json
from typing import TYPE_CHECKING, Optional

# 使用类型检查来避免循环导入，同时获得代码提示
if TYPE_CHECKING:
    from heart_rate_display_ui import HeartRateMonitor

class HeartRateApiHandler(http.server.BaseHTTPRequestHandler):
    """处理HTTP请求的处理器"""
    
    # [修正1] 使用 Optional 允许类型为 None
    heart_rate_monitor_instance: Optional['HeartRateMonitor'] = None
    # [新增] 处理 OPTIONS 请求，彻底解决跨域问题
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-Requested-With, Content-Type')
        self.end_headers()
        
    def do_GET(self):
        # 使用 try...finally 确保资源释放
        try:
            if self.path == '/heartrate':
                # 1. 准备数据 (增加容错)
                mon = self.heart_rate_monitor_instance
                current_hr = mon.heart_rate if mon else 0
                max_hr = getattr(mon, 'max_heart_rate', 0) if mon else 0
                is_connected = mon.connected if mon else False

                # 2. 构建响应 JSON
                response_data = {
                    'heart_rate': int(current_hr),
                    'max_heart_rate': int(max_hr),
                    'connected': bool(is_connected)
                }

                # 3. 发送响应头 (包含完善的 CORS)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*') 
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', '*')
                # 明确告诉客户端连接已完成，不要保持长连接
                self.send_header('Connection', 'close') 
                self.end_headers()
                
                # 4. 写入数据
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Not Found')
                
        except (ConnectionResetError, BrokenPipeError):
            # 捕获客户端（如浏览器）中途关闭导致的连接重置，不打印报错以保持日志整洁
            pass
        except Exception as e:
            # 记录其他异常到控制台或日志
            if self.heart_rate_monitor_instance:
                self.heart_rate_monitor_instance.log_message(f"[API] 请求处理异常: {e}")
        finally:
            # http.server 会自动处理 socket 关闭，但在某些 Python 版本下
            # 显式 flush 能够确保数据完全送达后再由底层释放资源
            try:
                self.wfile.flush()
            except:
                pass

    def log_message(self, format, *args):
        pass # 保持禁用日志，防止控制台刷屏

class ApiServer:
    """运行在独立线程中的API服务器"""
    def __init__(self, monitor_instance: 'HeartRateMonitor', port=8080):
        self.port = port
        self.monitor_instance = monitor_instance
        self.httpd: Optional[socketserver.ThreadingTCPServer] = None
        self.server_thread: Optional[threading.Thread] = None

    def start(self):
        """启动服务器"""
        if self.server_thread and self.server_thread.is_alive():
            self.monitor_instance.log_message("API服务器已在运行中。")
            return

        # 将主程序实例传递给请求处理器
        handler = HeartRateApiHandler
        handler.heart_rate_monitor_instance = self.monitor_instance
        
        try:
            # 使用 ThreadingTCPServer 以便能正确关闭
            self.httpd = socketserver.ThreadingTCPServer(("", self.port), handler)
            self.server_thread = threading.Thread(target=self.httpd.serve_forever)
            self.server_thread.daemon = True
            self.server_thread.start()
            self.monitor_instance.log_message(f"API服务器已在 http://127.0.0.1:{self.port} 启动")
        except Exception as e:
            self.monitor_instance.log_message(f"启动API服务器失败: {e}")
            self.httpd = None
            self.server_thread = None

    def stop(self):
        """停止服务器"""
        if self.httpd:
            self.monitor_instance.log_message("正在停止API服务器...")
            self.httpd.shutdown()
            self.httpd.server_close()
            
            # [修正2] 在调用 join 之前检查线程对象是否存在
            if self.server_thread:
                self.server_thread.join(timeout=2)

            self.httpd = None
            self.server_thread = None
            self.monitor_instance.log_message("API服务器已停止。")