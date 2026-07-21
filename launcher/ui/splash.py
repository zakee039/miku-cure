"""启动进度窗。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class SplashWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setFixedSize(420, 180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        self.title = QLabel("Miku Cure")
        self.title.setObjectName("h1")
        self.mode = QLabel("正在识别部署模式…")
        self.mode.setObjectName("sub")
        self.step = QLabel("请稍候…")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(5)

        layout.addWidget(self.title)
        layout.addWidget(self.mode)
        layout.addWidget(self.step)
        layout.addWidget(self.bar)

    def set_mode(self, label: str, detail: str = "") -> None:
        self.mode.setText(f"{label}" + (f"  ·  {detail.splitlines()[0]}" if detail else ""))

    def set_step(self, message: str, percent: int) -> None:
        self.step.setText(message)
        self.bar.setValue(max(0, min(100, percent)))
