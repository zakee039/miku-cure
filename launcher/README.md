# Miku Cure 桌面启动器

参考 **RAG-PRO / RAG智能体** 的启动器与便携包设计，用于统一管理：

- 后端 Python（情绪识别 + WebSocket）
- Electron 桌宠窗口
- 环境自检与实时日志
- 关闭时可选停止全部服务，避免孤儿进程

## 运行（开发）

```bat
cd launcher
run.bat
```

或：

```bat
pip install -r requirements.txt
python main.py
```

## 打包启动器 exe

```bat
cd launcher
build.bat
```

产物：项目根目录 `MikuCure-Launcher.exe`  
请放在**项目根**（或便携包根目录）运行，以便自动定位 `backend/`、`frontend/`。

## 便携整包（解压即用 · CPU）

在项目根：

```bat
package_portable.bat
```

或：

```powershell
powershell -File .\package_portable.ps1
```

产物：`packages/MikuCure-portable-<时间戳>.zip` + `.sha256`

包内结构：

```
MikuCure/
├── runtime/python/          # 嵌入式 Python + site-packages（CPU torch）
├── backend/                 # 源码 + models（无 .venv）
├── frontend/                # Electron 应用 + electron/dist
├── miku/                    # 媒体资源
├── user/                    # 用户数据（空模板）
├── MikuCure-Launcher.exe
├── PORTABLE_MANIFEST.json
├── start.bat
└── 便携使用说明.md
```

## 双模式

| | 开发态 | 便携态 |
|---|---|---|
| 识别 | 有 `backend/.venv` | `PORTABLE_MANIFEST.json` / `runtime/python` |
| Python | `.venv` | `runtime/python` |
| 启动 Electron | `node_modules/electron/dist` | 同左（已打入包内） |
| 后端托管 | 启动器或 Electron 均可 | 建议只用启动器（`MIKU_EXTERNAL_BACKEND=1`） |

## 与 RAG-PRO 对齐的要点

- 嵌入式 Python + 拷贝 site-packages（禁止把 venv 原样拷贝）
- 清理 `_distutils_hack` / 坏 `.pth`
- 启动器识别便携模式，禁止对用户机 `npm install`
- 关闭对话框：停止服务 / 仅退启动器
- 打包脚本校验 import 后再打 zip
