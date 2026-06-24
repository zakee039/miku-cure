<div align="center">

<img src="https://img.shields.io/badge/version-v0.1.0-ff69b4?style=for-the-badge" />
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

### 🖼️ 界面预览

| 桌面宠物主窗口 | 设置窗口 |
|:---:|:---:|
| 200×200 透明悬浮，Miku GIF 循环播放 | 独立亮色设置窗口，支持热切换推理后端 |

### 🧠 系统架构

```
┌─────────────────────────────────────────────────┐
│               Electron 前端 (frontend/)           │
│  透明悬浮窗 200×200 │ 番茄钟 │ 音乐播放器 │ 设置  │
└────────────────────┬────────────────────────────┘
                     │ WebSocket (ws://localhost:8765)
┌────────────────────▼────────────────────────────┐
│              Python 后端 (backend/)               │
│  camera.py → detector.py → websocket_server.py  │
│  logger.py  │  llm.py (DeepSeek)  │  main.py    │
└─────────────────────────────────────────────────┘
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
- DeepSeek API Key（[免费申请](https://platform.deepseek.com/)）

#### 1. 克隆项目

```bash
git clone https://github.com/momo325/miku-cure.git
cd miku-cure
```

#### 2. 配置环境变量

在项目根目录新建 `.env` 文件：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

#### 3. 安装 Python 依赖

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

> **Note** 如果你有 NVIDIA GPU 且架构为 Ampere 或更早（RTX 30xx 及以前），可安装对应 CUDA 版本的 PyTorch 以获得 GPU 加速。  
> RTX 40xx / RTX 50xx (Blackwell) 用户建议使用 CPU 模式，稳定性更高。

#### 4. 训练模型（可选，耗时约 10-30 分钟）

```bash
# 需要先将 FER2013 数据集放置于 datasets/fer2013.csv
python train_models.py
```

训练完成后权重会保存至 `backend/models/`。

#### 5. 准备 Miku 媒体资源

在项目根目录创建 `miku/` 文件夹，并按如下结构放置资源：

```
miku/
├── gif/      # 日常待机 MP4 动画（循环播放）
├── dance/    # 跳舞视频 MP4（带音频）
└── sing/     # 歌曲 OGG 音频文件
```

#### 6. 启动后端

```bash
cd backend
.venv\Scripts\activate
python main.py
```

#### 7. 启动前端

```bash
cd frontend
npm install
npm start
```

Miku 会出现在你的屏幕右下角 🎵

### 📁 项目结构

```
miku-cure/
├── backend/
│   ├── camera.py           # 摄像头低功耗采集（1 FPS）
│   ├── detector.py         # 表情识别核心（CNN / SVM / DeepFace 三路热切换）
│   ├── logger.py           # 跨越式情绪日志（RLE 压缩 Markdown 报告）
│   ├── llm.py              # DeepSeek 对话接口 + 本地语录兜底
│   ├── websocket_server.py # WebSocket 实时推送服务
│   ├── main.py             # 后端总调度（60s 负面情绪干预 + 番茄钟结算）
│   ├── train_models.py     # 三模型对比训练脚本
│   └── requirements.txt
├── frontend/
│   ├── main.js             # Electron 主进程（透明悬浮窗、IPC 通信）
│   ├── index.html          # 主界面（200×200 视口）
│   ├── renderer.js         # 渲染进程（状态机、番茄钟、音乐播放器）
│   ├── style.css           # 初音主题样式（毛玻璃 / 微动画）
│   ├── settings.html       # 设置窗口
│   ├── settings_renderer.js # 设置窗口逻辑
│   └── package.json
└── README.md
```

### 🎨 功能详解

#### 🔵 实时情绪识别
- **采样频率**：1 FPS 低功耗后台采集
- **人脸检测**：OpenCV Haar Cascades + MediaPipe（双重保障）
- **情绪分类**：7 类（开心 😊 / 悲伤 😢 / 愤怒 😠 / 惊讶 😲 / 恐惧 😨 / 厌恶 🤢 / 中性 😐）
- **防抖平滑**：滑动窗口多数投票，避免情绪闪烁

#### 🍅 番茄钟
- 自定义专注时长（默认 25 分钟）
- 倒计时结束后自动生成当次情绪统计报告
- 报告追加写入 `emotion_log.md`

#### 💬 AI 主动干预
- 连续 60 秒检测到负面情绪（悲伤 / 愤怒 / 恐惧 / 厌恶）时触发
- 优先调用 DeepSeek API 生成个性化暖心话语
- 网络断开时自动切换本地 Miku 二次元语录库兜底

#### 🎵 媒体播放器
- 日常 GIF/MP4 循环待机，双击随机切换
- 跳舞模式：播放带音频 MP4
- 唱歌模式：底部弹出极简单行播放器（上一首 / 播放暂停 / 下一首 / 关闭）

#### ⚙️ 热切换推理后端
点击齿轮图标 ⚙️ 打开设置窗口，可实时切换：
- **自建 PyTorch CNN**（默认，离线可用）
- **DeepFace**（精度更高，需联网或本地模型）
- **Fallback 模拟器**（无摄像头时调试用）

### 🐛 已知问题 & 解决方案

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| GPU 报错 `no kernel image` | RTX 50xx Blackwell 架构暂不被 PyTorch cu124 支持 | 设置 `CUDA_VISIBLE_DEVICES=-1` 强制 CPU 模式 |
| OpenCV 加载 XML 崩溃 | 项目路径含中文，OpenCV C++ 底层不支持 | 将 XML 复制到系统临时英文路径再加载 |
| `int32 is not JSON serializable` | Haar Cascades 返回 numpy int32 | 显式转换为标准 Python `int` |
| WebSocket `no running event loop` | 新版 websockets 接口变更 | 改用 `async with websockets.serve(...)` |

### 📊 模型性能对比

| 模型 | 验证集准确率 | 推理速度（CPU） | 模型大小 |
|------|:-----------:|:--------------:|:-------:|
| 自建 CNN | ~62% | < 2ms / 帧 | 23.2 MB |
| HOG + SVM | ~55% | < 1ms / 帧 | 0.2 MB |
| MobileNetV2 微调 | ~65% | ~5ms / 帧 | 8.9 MB |

> 数据集：FER2013（35887 张，48×48 灰度图，7 类）

### 🤝 贡献

欢迎提 Issue 和 PR！特别是：
- 更多 Miku 媒体资源
- 更高精度的情绪识别模型
- macOS / Linux 支持

### 📄 许可证

MIT License © 2026

---

## English

### ✨ Overview

Miku Cure is a transparent floating desktop pet that lives in the bottom-right corner of your Windows screen. It uses your webcam to recognize facial emotions in real-time, combines with a Pomodoro timer, and silently accompanies you while studying — gently encouraging you with AI-generated warm messages when you're feeling down.

### 🚀 Quick Start

```bash
git clone https://github.com/momo325/miku-cure.git
cd miku-cure

# Backend
cd backend && python -m venv .venv && .venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python main.py

# Frontend (new terminal)
cd frontend && npm install && npm start
```

Create a `.env` file in root with your `DEEPSEEK_API_KEY`.

### 🛠️ Tech Stack

- **Frontend**: Electron 31 · HTML5 · CSS3 (glassmorphism) · Vanilla JS
- **Backend**: Python 3.10 · PyTorch 2.6 · OpenCV · MediaPipe · WebSockets
- **AI**: DeepSeek Chat API · Custom CNN · HOG+SVM · MobileNetV2
- **Data**: FER2013 dataset

### 📄 License

MIT License © 2026
