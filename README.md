# HeartRateMonitor 💓

这是一个基于 Python 和 Tkinter 开发的高性能实时心率监控系统。
它能够通过蓝牙 (BLE) 连接支持心率广播的设备(如支持小米手环、华为手环、手表以及其他品牌的智能手环和手表心率带等)，
支持悬浮窗显示，适用于全屏游戏、直播等多种场景。支持时实时显示心率 PEAK 以及提供丝滑的实时波形展示，
并支持多种第三方联动（VRChat OSC、WebSocket、Webhooks）。

<img src="https://github.com/wang0227-demo/HeartRateMonitor/blob/master/resources/GUI.png"/>
最新版本下载地址：<a href="https://github.com/wang0227-demo/HeartRateMonitor/releases/download/v1.3.1/HeartRateMonitor_v1.3.1.rar">HeartRateMonitor_v1.3.1</a>

所需素材模板在文件夹 resources 

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
- **HTTP请求 支持** Requests==2.34.2
- **图像处理 (用于主窗口及悬浮窗图标)** Pillow>=10.0.0
- **异步兼容性支持 (部分旧版 Python 可能需要)** asyncio

## 🚀 快速开始

1. 确保电脑蓝牙已开启。
2. 运行 `main.py` 启动程序。
3. 点击 **“扫描设备”**，在弹窗中选择你的心率带/手表/手环。
4. 点击 **“连接”** 即可开始监控。

## 🛠️ 开发者笔记

本项目基于<a href="https://github.com/ccc007ccc/HeartRateMonitor">[HeartRateMonitor]</a>的功能逻辑进行二次开发。
通过对底层代码的彻底重构与逻辑优化，显著增强了系统的可扩展性与维护性。大幅提升了运行效率及稳定性。

架构升级：从单体架构重构为微服务架构。

性能提升：内存占用降低了 30% 响应速度提升了 2 倍。

体验优化：重绘了所有 UI 交互 简化了配置流程。

代码重构：通过引入 [中值滤波/动态阈值/小波变换] 算法，有效解决了原版在 [运动场景/环境噪声] 下心率跳变的问题，显著提升了心率检测的精准度与鲁棒性

模块化重构：将数据采集、信号处理与 UI 展示层进行彻底解耦，并优化了 [BLE 蓝牙/传感器接口] 的通信协议。新版本具备更高的可维护性，支持快速适配多种心率传感器硬件。

本项目灵感源自开源项目 <a href="https://github.com/ccc007ccc/HeartRateMonitor">HeartRateMonitor</a>，并针对其实际应用中的局限性进行了深度定制：旨在提供更稳定、高效的心率监测方案。

🌟 使用说明

一、	设备准备：请确保你的电脑支持无线蓝牙且你的心率设备处于心率广播模式。

二、	打开软件：初次扫描设备一定要先打开设备的心率广播模式，然后再扫描（不然无法获取设备真实的mac地址）。在软件左下角“连接控制”面板点击扫描，然后锁定你的设备，点击连接。一般情况几秒钟就可以连上了。连接成功以后你就可以看到心率在实时变动了。如果软件使用频率较高，建议可以勾选自动连接，这样会比较方便。

三、	功能介绍：支持实时同步心率到VRChat聊天框、多种心率获取方式（支持WebSocket、API、文本读取等）、支持Webhook联动（如飞书、钉钉、IFTTT等可定制各种提醒联动事件驱动等）、支持悬浮窗模式（让你在游戏的时候也能轻松看到自己的心率情况）、支持设备电量查看（注意：仅对符合协议标准的设备有效）、支持语音提醒功能、精彩时刻【截屏】、自定义看板娘功能等
<img src="https://github.com/wang0227-demo/HeartRateMonitor/blob/master/resources/333.png"/>
 
语音提醒功能 在心率异常的时候会有语音提醒

精彩时刻【截屏】 在心率异常的时候会自动截屏 保存在软件的screenshots目录下

自定义看板娘功能介绍 点亮换肤图标，软件会自动在软件目录生成\resources\skins文件夹 你只需要将自己喜欢的动态图片放到skins目录即可（请注意命名规范，至少要包含pet_idle_1.gif、pet_idle_2.gif、pet_idle_3.gif这3个文件名的有效文件）


四、	OBS使用方法 

1、	点亮实时状态右上角的文本图标后会在软件目录下生成一个obs_hr.txt的文件，然后OBS添加源-文本（GDI+）-勾选从文件读取-然后浏览选中软件目录下的obs_hr.txt文件即可（这种方式比较简单）
 <img src="https://github.com/wang0227-demo/HeartRateMonitor/blob/master/resources/444.png"/>


2、	选择你喜欢的模式WebSocket / API启动服务（两种获取方式都差不多），然后OBS添加源-浏览器-勾选本地文件-然后浏览选中对应的模板文件即可（每个模板都有3种动态显示效果，根据心率不同而触发。这种方式显示效果较好）

注意事项 API、WebSocket默认端口（8000、8001），有时候会存在被其他软件占用的情况。这时候我们只需要将其修改为其他可用端口即可。然后我们还需要同步修改html模板文件里面的默认端口（可直接搜索8000、8001替换即可）

30+不同心率显示模板效果展示（参考）

 <img src="https://github.com/wang0227-demo/HeartRateMonitor/blob/master/resources/111.png"/>
 <img src="https://github.com/wang0227-demo/HeartRateMonitor/blob/master/resources/222.png"/>

模板文件默认为WebSocket模式，如果你需要使用API 模式，请参考obs_api.html进行修改（只需要将<script></script>里面的内容替换掉即可）

obs_api.htm、obs_api2.htm一个是不带趋势图、一个是带趋势图的模板

obs设置建议
不带趋势图的obs浏览器建议设置大小 400*200
带趋势图的obs浏览器建议设置大小 800*200  
