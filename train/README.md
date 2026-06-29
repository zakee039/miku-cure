# 🎵 Miku Cure Emotion Model Training Station (模型训练工作站)

欢迎来到 **Miku Cure** 的核心训练引擎！这是一个专为面部微表情识别设计的、完全可视化的深度学习训练环境。通过前后端分离的架构，你可以直接在浏览器中优雅地配置参数、监控进度、评估模型，并最终将它们注入到 Miku Cure 的情绪感知系统中。

---

## 📂 目录结构

*   **`frontend/`**: 基于 Vue 3 + Vite 编写的现代 Web 界面。采用了 Miku 专属的扁平化、高对比度“机甲风”设计，支持多语言 (i18n)。
*   **`webui.py`**: FastAPI 后端。作为前后端通信的桥梁，负责接收 WebSocket 请求，管理底层的 Python 训练子进程。
*   **`train_cnn.py`**: 轻量级卷积神经网络 (EmotionCNN) 的训练脚本。它是系统中最稳定、泛化能力极强的“基石模型”。
*   **`train_rnn.py`**: 深层 Bi-LSTM + 8 头自注意力机制 (Multi-Head Attention) 的训练脚本。目前在 FER2013+ 上表现最强（Val Acc高达84.33%）。
*   **`train_mobilenet.py`**: 基于 MobileNetV2 迁移学习的训练脚本。经过了极速收敛与抗过拟合优化的“敏捷模型”。
*   **`models_extra.py`**: 存放非原生 CNN 模型（如 RNN+Attention 架构）的 PyTorch 网络定义代码。
*   **`datasets/`**: 存放训练所用的 CSV 格式数据集（如 FER2013 等）。
*   **`logs/`**: 每次训练产生的详细终端输出，会自动以 `时间戳-模型.txt` 的格式保存于此。
*   **`models/`**: 训练好的最优权重文件 (`.pth`) 存放点。

---

## ✨ 核心特性与我们的魔改升级

在过去的迭代中，我们对这个训练工作站进行了大量的深层优化，赋予了它商用级别的强悍能力：

### 1. 独创的双轨模型保存机制 (Dual-Save System)
我们摒弃了传统的“仅看验证集准确率”的粗暴保存方式，为所有模型设计了 **4:1 泛化评分算法**：
`Gen-Score = Val_Acc - 4.0 * max(0, Train_Acc - Val_Acc)`
每次训练，系统会同时输出两份权重文件：
*   `*_gen.pth`: 泛化分最高、最抗过拟合的“高分版”，适合实战部署。
*   `*_acc.pth`: 验证集准确率极限最高的“最强版”。

### 2. 真·系统级进程挂起 (Deep OS-Level Pause)
原本的训练暂停往往只在 Python 主线程中生效，导致由于 DataLoader 的多线程 (`num_workers`) 的存在，后台依然会吃满 CPU/GPU。
我们引入了 `psutil`，重写了后端的暂停逻辑：当点击“暂停”时，系统会**递归查找所有的 Python 子进程并强制挂起 (Suspend)**，瞬间将系统资源占用降为 0%，并且在点击“继续”时无缝恢复。

### 3. 反过拟合防御矩阵 (Anti-Overfitting Matrix)
为了应对 FER2013 等小型人脸数据集易被“死记硬背”的问题，我们在 `train_mobilenet.py` 及其他脚本中布下了天罗地网：
*   **强效 Dropout**: 在全连接分类层前加入了高达 0.5 的随机失活。
*   **高压权重衰减 (Weight Decay)**: 将优化器的权重惩罚从 `1e-4` 提升到了 `5e-4`。
*   **早停辅助**: 结合动态学习率衰减 (Dynamic LR on Plateau) 和我们的 Gen-Score，完美拦截模型记忆噪声的企图。

### 4. 极致沉浸的交互体验 (Immersive UI)
*   完美闭环：训练结束后自动弹出“训练完毕”提示，动态重置为“返回主页”大按钮。
*   队列式训练：你可以一次性勾选 CNN、RNN、MobileNet，调整好共用参数，点击开始，去喝杯咖啡，系统会依次自动帮你把所有模型全部跑完并生成报告。
*   秒级终端刷新：通过 WebSocket 的形式，后端的 Loss 和 Accuracy 及终端 Log 被毫无延迟地投射在网页上。

---

## 🚀 如何使用

1.  **准备环境**: 确保你在 `f:\project\期末大作业\backend\.venv` 激活了虚拟环境。
2.  **启动引擎**: 运行本目录下的 `start_webui.bat`，或手动执行：
    ```bash
    python webui.py
    ```
3.  **打开界面**: 在浏览器中访问 `http://localhost:8000`。
4.  选择数据集，配置学习率与轮数，点击下方耀眼的白色按钮，开始孕育能够读懂你情绪的 Miku 之心吧！
