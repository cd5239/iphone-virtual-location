# iPhone 虚拟定位

一个 Windows 桌面工具，通过 USB 或 Wi-Fi 连接 iPhone 的开发者定位服务，手动设置或清除模拟位置。支持常用地点管理、一键修改和托盘保持连接。当前源码版本为 **2.5.1**。

## 下载与首次使用

已发布的 Windows 安装包见 [Releases](https://github.com/cd5239/iphone-virtual-location/releases)，2.5.1 对应本地构建和源码验证记录见 [2.5.1 更新](docs/V2.5.1.md)。完整解压 ZIP 后再运行。需要 Windows 10/11 64 位、.NET Framework 4.x、Apple 设备驱动及服务，以及已开启开发者模式并信任此电脑的 iPhone。首次无线准备需用 USB，随后可用 Wi-Fi。连接组件已包含 Python，无需用户另装。

无线步骤见 [Wi-Fi 使用说明](docs/WIRELESS.md)。Wi-Fi 模式留空 IP 时，程序先查 Apple 设备服务；若没有 Network 设备，会主动浏览手机的无线公告并验证已有配对。手动填写 IP 后点击右侧“检测”，会自动切换到 Wi-Fi 并重新识别，无需反复切换连接方式；留空 IP 点击同样支持自动发现。自动和手动路径均须建立完整定位通道才显示可用。先退出旧版托盘，再运行新版；不要同时控制同一台手机。

1. 解锁手机，用 USB 连接电脑，并在手机上确认“信任此电脑”。
2. 打开 `iPhone虚拟定位.exe`，输入地点名称、经纬度及坐标来源，然后保存地点。
3. 点击“修改定位”；在手机地图中核对落点。之后可用 `一键修改.exe` 重新应用选中的地点。
4. 用主界面或托盘菜单发送“恢复真实定位”，再在手机地图核对实际位置。

首次运行没有预置地点。切换收藏仅改变下次要使用的地点，需点击“修改定位”才会给手机发送指令。不要只复制单个 exe；两个 exe、`engine` 和 `source` 必须保持同目录结构。

## 能力与限制

- 支持多个收藏地点，新增、修改、删除和持久化当前选择。
- 坐标来源可选 BD-09、GCJ-02、WGS84；向设备发送前换算为 WGS84。转换为近似计算，落点须在手机地图确认。
- 手机服务接受修改指令后，界面会显示结果；地图 App 可能需要刷新。
- “恢复真实定位”接口没有设备回执，程序发送停止模拟指令并等待后会提示**待手机确认**，不能据此断言 GPS 已恢复。
- USB 连接曾在 iPhone 16 / iOS 26.6.2 上验证；Wi-Fi 自动发现及手动 IP 定位通道已在本机拔线条件下验证，用户反馈 beta.3 无线功能可用。2.5.1 保留该通道逻辑，新增检测按钮并修正主按钮状态样式。具体设备和地图效果仍需实际核对。

本工具不要求打开其他手机助手界面，不调用地图地址搜索服务，也不上传地点数据。连接依赖 Apple 设备驱动和 [`pymobiledevice3`](https://github.com/doronz88/pymobiledevice3)。

## 数据与隐私

`locations.xml` 保存你输入的地点；旧 `location.xml` 仅用于首次迁移。`state/` 会在运行时生成，可能包含设备配对凭据。**不要分享 `locations.xml`、`location.xml`、备份文件或 `state/`。**本公开仓库和下载包均不包含这些文件。

详见 [换电脑使用](docs/换电脑使用.md) 和 [验证记录](docs/验证记录.md)。

## 从源码构建

界面使用 Windows .NET Framework C# 编译器构建；连接引擎使用 Python 3.13（无线隧道需要原生 TLS-PSK）、`pymobiledevice3==11.17.0` 和 `pyinstaller==6.22.3`。在 Windows PowerShell 中：

```powershell
.\source\build-ui.ps1
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\source\requirements-build.txt
.\source\build-engine.ps1 -Python .\.venv\Scripts\python.exe -BuildDirectory .\build-engine
New-Item -ItemType Directory -Force .\engine | Out-Null
Copy-Item .\build-engine\dist\LocationEngine\* .\engine -Recurse
```

完整构建依赖锁定见 `source/requirements-engine-lock.txt`，Windows 原生依赖构建说明见 [构建说明](docs/BETA3-BUILD.md)；历史依赖及第三方许可位于 `source/DEPENDENCIES.md` 和 `source/third-party-licenses/`。构建流程需要联网安装依赖；运行时首次准备开发者组件也可能需要联网。

制作公开 ZIP 时，使用 `python source/package-release.py <干净的发布目录> <输出 ZIP>`。脚本会检查引擎及 Wintun DLL 均已收录，并拒绝把 `state/` 或地点文件放进发布目录。

## 授权

本项目自有源码以 [GNU GPL v3 或更高版本](LICENSE) 开源。下载包内的 `pymobiledevice3` 同样采用 GPL-3.0-or-later；其他第三方组件分别遵循其原许可证，文本保留在 `source/third-party-licenses/`。修改或再分发时需遵守适用的许可条件。版权归属和对应源码获取方式见 [COPYRIGHT](COPYRIGHT.md) 与 [SOURCE](SOURCE.md)。
