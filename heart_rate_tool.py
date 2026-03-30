# heart_rate_tool.py
import asyncio
import time
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakDeviceNotFoundError, BleakError

class BluetoothTool:
    """
    深度优化版蓝牙心率工具：
    - 引入看门狗监控数据流稳定性
    - 增加连接前定向扫描预热
    - 增强服务发现可靠性
    """
    def __init__(self, logger_func):
        self.log_message = logger_func
        self.HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
        self.last_rx_time = 0  # 数据接收时间戳

    async def _async_scan(self, timeout=5.0):
        try:
            devices = await BleakScanner.discover(timeout=timeout)
            return [d for d in devices if d.name]
        except Exception as e:
            self.log_message(f"扫描异常: {e}")
            return []

    def sync_scan_wrapper(self, timeout=5.0):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            devices = loop.run_until_complete(self._async_scan(timeout))
            loop.close()
            if not devices:
                return False, "未发现蓝牙设备。请确保设备已开启广播模式"
            return True, devices
        except Exception as e:
            return False, f"扫描失败: {str(e)}"

    async def read_battery_level(self, client: BleakClient, ui_instance):
        """读取并更新设备电量"""
        BATTERY_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
        try:
            # 读取电量字节数据
            battery_data = await client.read_gatt_char(BATTERY_CHAR_UUID)
            if battery_data:
                level = int(battery_data[0])
                # 安全地回调 UI 线程进行更新
                ui_instance.root.after(0, lambda: ui_instance.update_battery_ui(level))
        except Exception as e:
            self.log_message(f"电量读取失败 (可能设备不支持标准电量服务): {e}")

    async def _find_hr_uuid(self, client: BleakClient):
        """
        寻找心率特征 UUID。
        在现代 Bleak 版本中，进入 async with 时服务已自动加载。
        如果仍找不到，访问 client.services 会触发加载。
        """
        try:
            # 1. 直接遍历已发现的服务
            for service in client.services:
                for char in service.characteristics:
                    if char.uuid.lower() == self.HR_MEASUREMENT_UUID:
                        return char.uuid
            
            # 2. 备选方案：如果标准 UUID 没找到，尝试通过描述文字匹配（部分非标设备）
            for service in client.services:
                for char in service.characteristics:
                    if "heart rate" in (char.description or "").lower():
                        return char.uuid
                        
            return None
        except Exception as e:
            self.log_message(f"服务发现异常: {e}")
            return None

    async def get_heart_rate(self, mac: str, ui_instance):
        if not mac:
            ui_instance.log_message("错误: MAC 地址无效。")
            return

        base_delay = 3.0
        max_delay = 30.0
        retry_count = 0

        BATTERY_INTERVAL = 300  # 5分钟 = 300秒
        last_battery_check = 0   # 初始设为0，连接成功后会立即触发第一次读取

        def notification_handler(characteristic: BleakGATTCharacteristic, data: bytearray):

            self.last_rx_time = time.time()  # 更新数据活跃时间戳
            flags = data[0]
            raw_hr = data[1] if not (flags & 0x01) else int.from_bytes(data[1:3], byteorder='little')

            new_state = "high" if raw_hr > 160 else "normal"
            if getattr(ui_instance, 'last_img_state', "") != new_state:
                target_url = "E:/Git/HeartRateMonitor/resources/GUI.png" if new_state == "high" else "E:/Git/HeartRateMonitor/resources/OBS.png"
                ui_instance.update_webhook_image(target_url)
                ui_instance.last_img_state = new_state

            if raw_hr > 120:
                alert_url = "https://pixnio.com/free-images/2026/02/14/2026-02-14-08-23-37-768x1122.png"
                ui_instance.add_to_ad_queue(alert_url)



            # 物理层过滤：拦截传感器松动产生的噪音 (0, 255 等)
            if raw_hr <= 30 or raw_hr >= 220:
                return 
            # 突发跳变拦截：如果 1 秒内变化超过 50，通常是硬件误差
            last_hr = getattr(ui_instance, 'heart_rate', 0)
            if last_hr > 0 and abs(raw_hr - last_hr) > 50:
                return
            # 只有通过过滤的数据才去触发 Webhook
            if hasattr(ui_instance, 'webhook_manager'):
                ui_instance.webhook_manager.trigger_event("heart_rate_updated", raw_hr)
            # 更新 UI 及各路服务器数据
            ui_instance.heart_rate = raw_hr    
            if raw_hr > ui_instance.max_heart_rate:
                ui_instance.max_heart_rate = raw_hr
            ui_instance.heart_rate_queue.put(raw_hr)
            ui_instance.root.after(0, lambda: ui_instance.on_heart_rate_update(raw_hr))
            if hasattr(ui_instance, 'websocket_server') and ui_instance.websocket_server:
                ui_instance.websocket_server.broadcast_heart_rate(raw_hr, ui_instance.max_heart_rate)                    

        def disconnected_callback(client):
            ui_instance.connected = False
            ui_instance.log_message(f"⚠️ 设备 {mac} 物理链路断开")
            # 触发断开 Webhook
            if hasattr(ui_instance, 'webhook_manager'):
                ui_instance.webhook_manager.trigger_event("disconnected", 0, 0, mac)

        # --- 核心重连监控循环 ---
        while ui_instance.should_connect:

            try:
                # 1. 物理层预热：在连接前尝试通过扫描定位设备
                ui_instance.log_message(f"正在定位并唤醒驱动: {mac}...")
                device = await BleakScanner.find_device_by_address(mac, timeout=7.0)
                if not device:
                    raise BleakDeviceNotFoundError(mac, "扫描无法识别该设备")

                async with BleakClient(device, disconnected_callback=disconnected_callback, timeout=15.0) as client:
                    retry_count = 0 
                    ui_instance.connected = True
                    # 显式触发 UI 连接成功回调
                    ui_instance.root.after(0, ui_instance._on_connect) 

                    self.last_rx_time = time.time() # 初始化时间戳
                    ui_instance.log_message(f"✅ 连接成功: {mac}")

                    # 触发连接成功 Webhook
                    if hasattr(ui_instance, 'webhook_manager'):
                        ui_instance.webhook_manager.trigger_event("connected", 0, 0, mac)

                    hr_uuid = await self._find_hr_uuid(client)
                    if hr_uuid:
                        await client.start_notify(hr_uuid, notification_handler)
                        ui_instance.log_message("实时心率流已启动")

                        await self.read_battery_level(client, ui_instance)
                        
                        # 2. 逻辑看门狗：监控数据流是否卡死
                        while ui_instance.connected and ui_instance.should_connect:
                            await asyncio.sleep(1.0)

                            current_time = time.time()
                            if current_time - last_battery_check >= BATTERY_INTERVAL:
                                try:
                                    # 尝试读取电量 (UUID: 0x2A19)
                                    battery_data = await client.read_gatt_char("00002a19-0000-1000-8000-00805f9b34fb")
                                    if battery_data:
                                        level = int(battery_data[0]) # 某些设备返回字节数组，取第一个
                                        # 同步更新 UI
                                        ui_instance.root.after(0, lambda l=level: ui_instance.update_battery_ui(l))
                                        last_battery_check = current_time

                                        if hasattr(ui_instance, 'webhook_manager'):
                                            ui_instance.webhook_manager.trigger_event("low_battery", 0, level, "")

                                except Exception as e: 
                                    # 部分手环在传输心率时可能拒绝同时读取特征值，这里静默失败即可
                                    print(f"[BLE] 定时读取电量跳过: {e}")
                                    # 如果失败，1分钟后再试，而不是等5分钟
                                    last_battery_check = current_time - 240 

                            # 如果超过 15 秒没收到新包，认为驱动层已死，主动退出触发重连
                            if time.time() - self.last_rx_time > 15.0:
                                ui_instance.log_message("检测到数据流卡死，准备重连...")
                                break
                                
                        if ui_instance.should_connect:
                            await client.stop_notify(hr_uuid)
                    else:
                        ui_instance.log_message("❌ 错误: 该设备不符合标准心率特征")
                        ui_instance.should_connect = False

            except (BleakDeviceNotFoundError, asyncio.TimeoutError, BleakError) as e:
                if not ui_instance.should_connect: break
                
                # 3. 动态退避策略
                retry_count += 1
                wait_time = min(base_delay * (1.3 ** retry_count), max_delay)
                ui_instance.log_message(f"连接失败 ({type(e).__name__})，将在 {wait_time:.1f}s 后进行第 {retry_count} 次重试...")
                await asyncio.sleep(wait_time)
            except Exception as e:
                ui_instance.log_message(f"系统级异常: {e}")
                await asyncio.sleep(5)

        ui_instance.root.after(0, ui_instance._on_disconnect)
        ui_instance.log_message("蓝牙后台任务已安全停止")
