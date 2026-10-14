# v2.5.0-beta.3 本机验证

日期：2026-10-14。分支：`feature/mdns-auto-v2.5.0-beta.3`。这是本地测试包，未推送或发布。

## 变更

- Apple/usbmux 无 Network 设备时，约 4 秒浏览 `_remotepairing._tcp.local`，校验已有 RemotePairing 认证后按手机去重。
- 发现地址只作为临时连接端点，不写进手动 IP 字段或公开包；保留手动 IP 单播发现。
- 无线 lockdown 使用 `autopair=False` 并核对设备身份；多台设备、目标仍插 USB、未认证公告、无效地址和端口均拒绝。
- 自动/手动/Apple Network 三条 Wi-Fi 路径只有完整定位通道建立后才报告可用；缓存会话复检时检查通道和新的 lockdown 通信。
- 构建依赖继续使用 Python 3.13.16 原生 TLS-PSK；补齐已有开发者组件初始化所需压缩库及版本元数据。

## 已完成验证

| 验证 | 结果 |
|---|---|
| Python 回归测试 | 45 项全部通过，包含真实合成 authTag 校验、重复公告、未配对/伪造拒绝、多目标拒绝、地址重试、USB 未拔拒绝、通道失败及断线撤销就绪 |
| WPF 状态模型 | 通过 |
| 合成地点存储测试 | 通过；未使用用户地点 |
| WPF 离屏渲染 | 96/144/192 DPI 生成成功；144 DPI 已目视检查，无内容截断 |
| 原生压缩依赖 | pylzss/lzfse 压缩解压往返通过，开发者组件初始化模块导入通过 |
| beta.3 新源码拔线检测 | 自动 mDNS 通道、缓存复检、手动 IP 通道均成功 |
| beta.3 最终打包引擎拔线检测 | 同样全部成功，退出码 0，无 stderr |

最终引擎的脱敏关键输出：

```text
request 1: Wi-Fi IP blank -> discovery=mdns, Network, connected, usable=true, active=false
request 2: Wi-Fi IP blank -> discovery=mdns, Network, connected, usable=true, active=false
request 3: manual IP      -> discovery=manual, Network, connected, usable=true, active=false
```

当时 Apple Mobile Device Service 为 Running/Automatic，Bonjour Service 仍为 Stopped/Disabled。因此新自动路径已经在原来无法生成 Network 列表的公司电脑环境中建立了无线隧道、DVT 和 LocationSimulation 定位服务通道，修复没有依赖启用 Bonjour 或修改网络配置。

检测只使用已有本机配对，仅发送 probe/shutdown，未发送定位修改或恢复命令，也没有在手机地图中验证实际位置。开发者组件模块验证了导入和运行库完整性，本轮没有在全新 iPhone 上实际下载安装组件。多手机、断线、失败等异常路径为合成测试；实机验证针对当前单台手机。

## 交付与版本边界

公开包仅含程序、引擎、对应源码、构建脚本、第三方许可和文档，不含 state、地点文件、手机 IP、连接方式或 Git。打包脚本验证 ZIP CRC 和四种架构 Wintun DLL；最后从生成的 ZIP 再解压检查并重测引擎。

本机原始 beta.2 的关键源码和引擎保持原哈希；本地 `main` 保持 `7072fbf`。beta.2 的原开发提交不在本机，独立仓库用原交付 ZIP 的源码快照建立本地 `v2.5.0-beta.2` 基线标签，详见 `LOCAL-BASELINE.md`。没有通过 GitHub 拉取、推送或发布，没有改稳定版、服务、防火墙、手机开关或地址转坐标功能。

测试时完整解压到新目录；需要复用已有配对时，仅在自己的本机复制 beta.2 的 state 到 beta.3。保留原目录，不将私人状态放回 ZIP。具体操作见 `WIRELESS-TEST.md`。
