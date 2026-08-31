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

配置文件最大 64 KiB。未知字段、任意脚本函数、无效标识符、越界数值和引用不存在动作的按钮都会被忽略。
