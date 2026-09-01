# 模型独立配置

每个 Live2D 模型可在其 `.model3.json` 同目录放置 `miku-cure.config.json`。桌宠主进程会读取并校验该文件；启动器只负责启动、停止和重启服务，不读取或控制模型功能。

当前配置格式版本为 `1`。示例：

```json
{
  "version": 1,
  "framing": {
    "horizontalOffset": 0,
    "verticalFill": 2.35,
    "hitAreas": [
      { "name": "face", "left": 0.32, "right": 0.68, "top": 0.27, "bottom": 0.52 }
    ]
  },
  "resetParameters": ["Param133"],
  "actions": {
    "cry": {
      "expression": "哭",
      "duration": 5200,
      "parameters": { "Param133": 1 }
    }
  },
  "homeButtons": [
    {
      "id": "cry",
      "function": "action",
      "action": "cry",
      "icon": "😭",
      "title": "哭",
      "order": 0
    }
  ],
  "editButtons": [],
  "interactions": {
    "hitActions": { "face": "cry" }
  },
  "tracking": {
    "mouse": {
      "supported": true,
      "eyeStrength": 0.75,
      "headStrength": 0.45,
      "bodyStrength": 0.15
    },
    "face": {
      "supported": true,
      "profile": "mediapipe-face-landmarker-v1",
      "parameters": {
        "headX": { "id": "ParamAngleX", "scale": 30, "offset": 0, "min": -30, "max": 30 },
        "eyeX": { "id": "ParamEyeBallX", "scale": -1, "offset": 0, "min": -1, "max": 1 }
      }
    }
  },
  "emotions": {
    "sadness": "哭"
  }
}
```

支持的字段：

- `framing`：模型默认偏移、缩放填充、不同动作的缩放及点击区域。
- `watermark`：可选。只有模型确实支持水印切换时才声明 `parameterIds` 或 `partIds`；未声明则编辑模式不显示水印按钮。
- `resetParameters`：每帧恢复到中性的动作参数，防止不同表情残留叠加。
- `actions`：动作名到 Live2D 表情、持续时间和参数值的映射。
- `homeButtons`：只在普通首页显示的模型快捷按钮。普通 Miku 在这里配置投喂，樱花 Miku 配置脸红动作。
- `editButtons`：只在编辑模式显示的模型按钮。它与首页按钮使用完全独立的列表。
- 两类按钮的 `function` 当前只允许安全的声明式 `action`，且 `action` 必须存在于同一配置的 `actions` 中。旧版 `buttons` 字段仍会作为 `homeButtons` 读取。
- `interactions`：可配置点击区域、双击、画圈、闲置、负面报告和音乐播放时触发的动作。
- `interactions.music`：模型有唱歌表情时指向对应动作；未声明时，播放歌曲会自动使用表情包模式的唱歌/暂停视频。
- `emotions`：识别情绪到模型表情文件名的精确映射。
- `tracking.mouse`：声明模型是否支持鼠标追踪，以及眼睛、头部和身体的相对强度。
- `tracking.face`：声明面捕能力和语义参数到 Cubism 参数的安全线性映射。每个绑定必须提供 `id / scale / offset / min / max`；运行时只接受白名单中的面部语义键，不执行脚本表达式。

追踪参数每帧按以下顺序写入：`resetParameters → Tracking → action parameters → watermark`。动作只有在 `actions.*.parameters` 中显式列出的参数才会临时覆盖追踪值。

配置文件最大 64 KiB。未知字段、任意脚本函数、无效标识符、越界数值和引用不存在动作的按钮都会被忽略。
