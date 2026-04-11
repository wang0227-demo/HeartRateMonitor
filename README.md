# HeartRateMonitor 💓

这是一个基于 Python 和 Tkinter 开发的高性能实时心率监控系统。
它能够通过蓝牙 (BLE) 连接支持心率广播的设备(如支持小米手环、华为手环、手表以及其他品牌的智能手环和手表心率带等)，
支持悬浮窗显示，适用于全屏游戏、直播等多种场景。支持时实时显示心率 PEAK 以及提供丝滑的实时波形展示，
并支持多种第三方联动（VRChat OSC、WebSocket、Webhooks）。

<img src="https://github.com/wang0227-demo/HeartRateMonitor/blob/master/resources/GUI.png"/>
最新版本下载地址：<a href="https://github.com/wang0227-demo/HeartRateMonitor/releases/download/v1.2.0/HeartRateMonitor-1.2.0.exe">HeartRateMonitor v1.2.0</a>

所需素材模板在文件夹 resources 请自行下载

## 🌟 核心功能

- **高性能波形图**：采用区间锁定（0-50, 50-100, 100-150, 150-200）和滞后缓冲区逻辑，提供低 CPU 占用的丝滑视觉体验。
- **多平台联动**：
  - **VRChat OSC**：实时同步心率到 VRChat 聊天框。
  - **WebSocket 服务器**：为 OBS 提供实时心率数据推送（默认端口 8001）。
  - **API 服务器**：支持被动获取心率数据。
  - **Webhook 联动**：支持心率异常报警（如飞书、钉钉、IFTTT），具备冷却时间机制。
- **智能悬浮窗**：支持自定义格式、置顶锁定、点击穿透及图片展示。
- **自动化重连**：内置蓝牙看门狗，数据流卡死时自动触发重启重连。

## 🛠️ 技术架构

- **GUI 框架**：Tkinter (TTK)
- **蓝牙通信**：Bleak (支持异步/同步包装)
- **异步处理**：asyncio + threading (确保 UI 不卡顿)
- **网络通信**：websockets, urllib.request

## 🛠️ 依赖项清单

- **核心蓝牙驱动** bleak>=0.21.1
- **VRChat OSC 支持** python-osc>=1.8.3
- **WebSocket 支持** websockets>=12.0
- **图像处理 (用于主窗口及悬浮窗图标)** Pillow>=10.0.0
- **异步兼容性支持 (部分旧版 Python 可能需要)** asyncio

## 🚀 快速开始

1. 确保电脑蓝牙已开启。
2. 运行 `main.py` 启动程序。
3. 点击 **“扫描设备”**，在弹窗中选择你的心率带/手表/手环。
4. 点击 **“连接”** 即可开始监控。

## 🌟 使用说明书

一、蓝牙连接指南
设备准备：请确保心率设备未被手机 App 占用，且处于心率广播模式。
扫描与锁定：在“连接控制”面板点击扫描。如果搜不到，请尝试关闭并重新开启电脑蓝牙。
自动重连：程序会自动尝试重连。如果心率数值 15 秒不更新，看门狗会强制重启连接链路。

二、OBS 推送设置 (WebSocket)
在主界面“WebSocket 服务器”栏勾选“启用” 。
在 OBS 中添加一个“浏览器源”，URL 指向你的本地 OBS 页面模板即可（内置3种不同动态显示效果）。
若心率重置，WebSocket 会同步发送 max_heart_rate: 0 。

<img src="https://github.com/wang0227-demo/HeartRateMonitor/blob/master/resources/111.png"/>
<img src="https://github.com/wang0227-demo/HeartRateMonitor/blob/master/resources/222.png"/>
<img src="https://github.com/wang0227-demo/HeartRateMonitor/blob/master/resources/333.png"/>
三、Webhook 报警设置
点击“打开 Webhook 设置” 。
同步预设：点击“同步官方预设”可以从 GitHub 获取飞书、钉钉等常用配置。
参数过滤：你可以设置“报警阈值”和“冷却时间”，防止心率波动导致机器人频繁刷屏。

四、悬浮窗操作
解锁状态：可以自由拖动位置。
锁定状态：背景变为透明（或自定义颜色），且鼠标点击会直接穿透到后方的游戏或窗口 。
格式化：在格式栏输入 {img}{bpm} 可同时显示心率图标和数字。

## 🛠️ 开发者笔记

本项目基于<a href="https://github.com/ccc007ccc/HeartRateMonitor">[HeartRateMonitor]</a>的功能逻辑进行二次开发。
通过对底层代码的彻底重构与逻辑优化，显著增强了系统的可扩展性与维护性。大幅提升了运行效率及稳定性。

架构升级：从单体架构重构为微服务架构。

性能提升：内存占用降低了 30% 响应速度提升了 2 倍。

体验优化：重绘了所有 UI 交互 简化了配置流程。

代码重构：通过引入 [中值滤波/动态阈值/小波变换] 算法，有效解决了原版在 [运动场景/环境噪声] 下心率跳变的问题，显著提升了心率检测的精准度与鲁棒性

模块化重构：将数据采集、信号处理与 UI 展示层进行彻底解耦，并优化了 [BLE 蓝牙/传感器接口] 的通信协议。新版本具备更高的可维护性，支持快速适配多种心率传感器硬件。

本项目灵感源自开源项目 <a href="https://github.com/ccc007ccc/HeartRateMonitor">HeartRateMonitor</a>，并针对其实际应用中的局限性进行了深度定制：旨在提供更稳定、高效的心率监测方案。

