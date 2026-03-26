# main.py

import multiprocessing
import sys
import argparse
import asyncio
from heart_rate_display_ui import HeartRateMonitor

def main():
    parser = argparse.ArgumentParser(description='心率监控器')
    parser.add_argument('--scan', action='store_true', help='仅扫描设备')
    args = parser.parse_args()
    
    if args.scan:
        from heart_rate_tool import scan_and_select_device
        asyncio.run(scan_and_select_device())
    else:
        app = HeartRateMonitor()
        app.run()

if __name__ == "__main__":
    # [最高优先级] 必须在第一行，阻止打包后的子进程无限循环启动
    multiprocessing.freeze_support() 
    main()
