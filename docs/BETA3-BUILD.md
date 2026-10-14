# beta.3 本地构建

Python 引擎使用官方 CPython 3.13.16 x64、pymobiledevice3 11.17.0、PyInstaller 6.22.3，保持原生 TLS-PSK。完整实际构建依赖锁定在 `source/requirements-engine-lock.txt`；原 `DEPENDENCIES.md` 保留此前环境历史。

本轮使用工作目录内便携 Python，不注册系统安装。pylzss 0.3.4 与 lzfse 0.4.2 没有适用的 CPython 3.13 Windows wheel，因此使用便携 Zig 0.13.0 从未修改的上游源码编译这两项已有依赖，以保留开发者组件初始化能力。对应源码包在 `source/third-party-sources`，原第三方许可文本保留。

构建步骤：

1. 准备 CPython 3.13.16 x64（含 Python SDK 头文件和导入库）及对应依赖，安装 PyInstaller。
2. 如没有现成的 pylzss/lzfse 3.13 原生扩展，用 `source/build-compression.py --zig <zig.exe> --python-sdk <Python SDK 根目录> --output <Python site-packages>` 构建；其余锁定依赖可通过 pip 安装。
3. `source/build-ui.ps1` 构建 WPF 两个入口。
4. `source/build-engine.ps1 -Python <python.exe> -BuildDirectory <独立构建目录>` 构建引擎。脚本收集 pmd_pytcp 子模块、DTX、Wintun DLL，以及需要的版本元数据。
5. 把构建后的引擎放入干净交付目录的 `engine`；加入对应源码、文档和两个入口，用 `source/package-release.py <干净目录> <目录外的ZIP>` 打包并校验。

不要将构建环境、Git、配对数据、常用地点或手机 IP 放进交付包。本仓库保留本机可用的稳定 Git 历史；beta.2 基线来自交付 ZIP 的源码快照，详见 `LOCAL-BASELINE.md`。

官方运行时来源：[CPython 3.13.16](https://www.python.org/ftp/python/3.13.16/)；便携编译器来源：[Zig 0.13.0](https://ziglang.org/download/)。源码库保持 pymobiledevice3 固定版本，没有修改第三方协议实现。
