<div align="center">

<img src="https://img.shields.io/badge/version-v0.3.2-ff69b4?style=for-the-badge" />
<img src="https://img.shields.io/badge/platform-Windows-0078d7?style=for-the-badge&logo=windows" />
<img src="https://img.shields.io/badge/Electron-31.7.7-47848f?style=for-the-badge&logo=electron" />
<img src="https://img.shields.io/badge/PyTorch-2.6.0-ee4c2c?style=for-the-badge&logo=pytorch" />
<img src="https://img.shields.io/badge/DeepSeek-API-6c47ff?style=for-the-badge" />

# 🎵 Miku Cure

**初音未来情绪伴侣 · 桌面宠物式情绪感知系统**

> 让 Miku 陪着你学习，实时感知你的情绪，在你疲惫或低落时轻轻说一句「加油哦 ✨」

[English](#english) · [中文](#中文)

</div>

---

## 中文

### ✨ 功能简介

Miku Cure 是一个运行在 Windows 桌面右下角的透明悬浮小宠物。它通过摄像头实时识别你的表情情绪，结合番茄钟工作法，在你专注学习时默默陪伴，在你持续低落时主动用 AI 生成的暖心话语来鼓励你。

### 🎉 v0.3.0 更新亮点
- **全局多语言支持 (i18n)**：现已全面支持中文、日文、英文三种语言。不仅包括界面文本，连生成的专注报告日志文件名、内容表头，以及 Miku 暖心话语都会随语言切换！
- **设置界面重构**：采用了全新的水平 Tab 标签页设计（模型、通用、API设置、关于），优化垂直空间；将所有单选框升级为点击下拉列表 (`<select>`)。
- **内置 API 管理器**：不再仅仅依赖 `.env` 文件，现在你可以直接在“设置” -> “API 设置”中添加、编辑、删除你的 LLM API Key，支持所有 OpenAI 格式兼容的接口（并自动热加载到后端）。
- **完善的生命周期管理**：修复了在 Windows 平台上的“僵尸进程”问题。关闭 Miku 前端窗口时，Python 进程树及所有的 WebSocket 服务将会被完全、干净地终结。

### 🖼️ 界面预览

| 桌面宠物主窗口                                                | 全新设置窗口 (v0.3.0)               |
|:------------------------------------------------------:|:------------------:|
| 200×200 透明悬浮，Miku GIF 循环播放 | 标签页导航，内置多语言、API 管理、关于页面 |

### 🧠 系统架构

```
┌────────────────────────────────────────────────────────┐
│                 Electron 前端 (frontend/)              │
│  透明悬浮窗 200×200 │ 番茄钟 │ 音乐播放器 │ 设置面板 (i18n) │
└──────────────────────┬─────────────────────────────────┘
                       │ WebSocket (ws://localhost:8765)
┌──────────────────────▼─────────────────────────────────┐
│                 Python 后端 (backend/)                 │
│  camera.py → detector.py → websocket_server.py         │
│  logger.py (多语言日志) │  llm.py (热切API)  │  main.py │
└────────────────────────────────────────────────────────┘
                       │
           ┌───────────▼───────────┐
           │  FER2013 训练模型      │
           │  · 自建 PyTorch CNN   │
           │  · HOG + SVM         │
           │  · MobileNetV2 微调   │
           └───────────────────────┘
```

### 🚀 快速开始

#### 环境要求

- Windows 10/11
- Python 3.10+
- Node.js 18+
- 摄像头（笔记本内置或外接均可）
- LLM API Key（支持 DeepSeek 或任意兼容 OpenAI 格式的接口）

#### 1. 克隆项目

```bash
git clone https://github.com/momo325/miku-cure.git
cd miku-cure
```

#### 2. 一键启动 

在项目根目录下：
- **首次使用**：双击运行 `install.bat`，它会自动帮你创建虚拟环境、安装前后端所有依赖。
- **日常启动**：双击运行 `start.bat`，它会自动启动后端服务并打开前端 Miku 窗口。（**关闭 Miku 窗口时，后端服务也会自动安全退出**）

#### 3. 配置 API

应用启动后，右击 Miku 头像进入「⚙️ 设置」，在「API 设置」标签页中添加你的 LLM 接口并选中，即可激活 AI 陪伴功能。如果没有配置，将使用本地的随机预设暖心话语。

#### 4. 训练模型（可选，耗时约 10-30 分钟）

```bash
# 需要先将 FER2013 数据集放置于 datasets/fer2013.csv
cd train
python train_models.py
```

训练完成后权重会保存至 `train/models/`，你可以将它们手动拷贝到 `backend/models/` 以供推理使用。

#### 5. 准备 Miku 媒体资源

你可以把自己喜欢的视频和歌曲放入 `miku/` 文件夹中。如果没有该文件夹，请在项目根目录创建它，并按如下结构放置你的自定资源：

```
miku/
├── gif/      # 日常待机 MP4 动画（循环播放）
├── dance/    # 跳舞视频 MP4（带音频）
└── sing/     # 歌曲 OGG 音频文件
```

### 📁 项目结构

```
miku-cure/
├── backend/
│   ├── camera.py           # 摄像头低功耗采集（1 FPS）
│   ├── detector.py         # 表情识别核心（CNN / SVM / DeepFace 三路热切换）
│   ├── logger.py           # 跨越式情绪日志（支持多语言自动生成）
│   ├── llm.py              # 兼容 OpenAI 的对话接口 + 本地多语种兜底语录
│   ├── websocket_server.py # WebSocket 实时推送服务
│   └── main.py             # 后端总调度（负面情绪干预 + 番茄钟结算）
├── train/
│   ├── train_models.py     # 模型训练脚本
│   └── models/             # 训练产出目录
├── frontend/
│   ├── main.js             # Electron 主进程（透明悬浮窗、IPC、进程树清理）
│   ├── index.html          # 主界面（200×200 视口）
│   ├── renderer.js         # 渲染进程（状态机、番茄钟、音乐播放器）
│   ├── i18n.js             # (v0.3.0) 国际化翻译库 (zh/ja/en)
│   ├── style.css           # 初音主题样式（毛玻璃 / 微动画）
│   ├── settings.html       # 全新 Tab 式设置窗口
│   ├── settings_renderer.js # 设置窗口逻辑 (含 API 管理器)
│   ├── assets/             # 特殊状态媒体库
│   └── package.json
├── install.bat             # 一键环境安装脚本
├── start.bat               # 一键联合启动脚本
└── README.md
```

### 🎨 功能详解

#### 🔵 实时情绪识别
- **采样频率**：1 FPS 低功耗后台采集
- **情绪分类**：7 类（开心 😊 / 悲伤 😢 / 愤怒 😠 / 惊讶 😲 / 恐惧 😨 / 厌恶 🤢 / 中性 😐）
- **防抖平滑**：滑动窗口多数投票，避免情绪闪烁

#### 🍅 专注番茄钟与日志
- 自定义专注时长
- 倒计时结束后自动生成当次多语言情绪统计 Markdown 报告，自动保存在 `logs/YYYYMMDD/` 目录下。

#### 💬 AI 主动干预与多语言陪伴
- 连续 60 秒检测到负面情绪时触发，Miku 会根据当前设置的语言（中/日/英）和情绪特征向 LLM 请求安慰话语。
- 断网或无 API 时，会自动降级使用内置的三语关怀语录库。

#### ⚙️ 丰富的高级设置
- **推理后端切换**：自建 PyTorch CNN / DeepFace / Mock
- **界面与尺寸**：支持调整 67%、100%、150% 窗口缩放，中日英语言无缝切换
- **API 管理**：本地化的 LLM Key 托管方案，支持多模型保存

### 🤝 贡献
欢迎提 Issue 和 PR！

### 📄 许可证
MIT License © 2026

---

## English

### ✨ Overview

Miku Cure is a transparent floating desktop pet that lives in the bottom-right corner of your Windows screen. It uses your webcam to recognize facial emotions in real-time, combines with a Pomodoro timer, and silently accompanies you while studying — gently encouraging you with AI-generated warm messages when you're feeling down.

### 🎉 What's New in v0.3.0
- **Full i18n Support**: Seamlessly switch between English, Japanese, and Chinese. Translations apply to the UI, LLM prompts, fallback messages, and even generated Markdown log files.
- **Redesigned Settings**: A new tabbed interface optimizing vertical space, featuring dropdowns instead of bulky radio buttons.
- **Built-in API Manager**: Add, edit, and switch between OpenAI-compatible APIs right from the settings UI without needing to edit `.env` files.
- **Robust Process Management**: Fixed zombie processes on Windows. Closing the app now thoroughly terminates the entire Python process tree and WebSockets.

### 🚀 Quick Start

```bash
git clone https://github.com/momo325/miku-cure.git
cd miku-cure

# Just double click `install.bat` to setup environments.
# Then double click `start.bat` to run the app!
```

After starting, right click Miku, open settings, and configure your LLM API in the "API Settings" tab.

**Customizing Media:** You can add your favorite videos and songs by placing them into the `miku/` folder. Create `gif/` (idle MP4s), `dance/` (dance MP4s), and `sing/` (OGG audio) subdirectories to load your own content.

### 🛠️ Tech Stack

- **Frontend**: Electron 31 · HTML5 · CSS3 (glassmorphism) · Vanilla JS
- **Backend**: Python 3.10 · PyTorch 2.6 · OpenCV · MediaPipe · WebSockets
- **AI**: DeepSeek/OpenAI Compatible API · Custom CNN · MobileNetV2
- **Data**: FER2013 dataset

### 📄 License

MIT License © 2026
