# websocket_server.py
import asyncio
import json
import threading
import websockets
from typing import Set, Optional

class WebSocketServer:
    def __init__(self, monitor_instance, port: int, logger_func):
        self.monitor_instance = monitor_instance
        self.port = port
        self.logger = logger_func
        self.server_thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.connected_clients: Set = set()
        # 初始化为空，在 start() 线程内创建
        self.stop_event: Optional[asyncio.Event] = None

    async def _handler(self, websocket):
        self.connected_clients.add(websocket)
        try:
            async for _ in websocket: 
                pass # 保持连接，接收客户端消息（如有）
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.connected_clients.discard(websocket)

    async def _run_server(self):
        server = None
        try:
            # 存下 server 实例以便手动管理（如果需要）
            server = await websockets.serve(self._handler, "0.0.0.0", self.port, reuse_address=True)
            self.logger(f"WebSocket 服务器已在 ws://0.0.0.0:{self.port} 启动")
            
            # 阻塞直到 stop_event 被 set()
            await self.stop_event.wait()
            
        except Exception as e:
            self.logger(f"[WebSocket] 运行异常: {e}")
        finally:
            if server:
                server.close()
                await server.wait_closed()
                self.logger("[WS] 网络端口已释放")


    def start(self):
        if self.server_thread and self.server_thread.is_alive(): 
            return
        
        def thread_target():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            # 必须在 loop 所在的线程内创建 Event
            self.stop_event = asyncio.Event() 
            self.loop.create_task(self._run_server())
            self.loop.run_forever()

        self.server_thread = threading.Thread(target=thread_target, daemon=True)
        self.server_thread.start()

    def stop(self):
        """优雅停止：确保所有协程安全退出后再关闭 Loop"""
        if self.loop and self.loop.is_running():
            def _shutdown():
                # 1. 触发事件，让 _run_server 退出 async with 块
                if self.stop_event:
                    self.stop_event.set()
                
                # 2. 获取当前所有运行中的任务（除了当前这个 shutdown 任务）
                # 这里不立即停止 loop，而是让它把最后的清理工作做完
                async def _wait_and_stop():
                    # 给一丁点时间让 websockets 库执行内部清理 (_close 等)
                    await asyncio.sleep(0.2)
                    self.loop.stop()

                asyncio.create_task(_wait_and_stop())

            # 跨线程投递关闭指令
            self.loop.call_soon_threadsafe(_shutdown)
            
            # 等待线程结束（给 2 秒宽限期）
            if self.server_thread:
                self.server_thread.join(timeout=2)
            
            # 彻底清理引用
            self.loop = None
            self.server_thread = None
            self.connected_clients.clear()
            self.logger("[WS] 服务器资源已安全回收")



    def broadcast_heart_rate(self, bpm, max_bpm, battery=0):
        """主线程调用：将心跳数据广播给所有客户端"""
        if not self.loop or not self.loop.is_running() or not self.connected_clients:
            return
        
        data = json.dumps({
            "heart_rate": bpm, 
            "max_heart_rate": max_bpm,
            "battery": battery, 
            "connected": self.monitor_instance.connected
        })

        async def _send_to_all(msg):
            # 使用 list 做快照，防止遍历时集合大小改变抛出异常
            clients = list(self.connected_clients)
            if clients:
                # 并发发送，任一客户端失败不影响其他客户端
                await asyncio.gather(*[c.send(msg) for c in clients], return_exceptions=True)
        
        # 将协程安全地投递到异步线程执行
        asyncio.run_coroutine_threadsafe(_send_to_all(data), self.loop)
