"""明亮浅色主题 + 图标加载（Miku 青绿点缀）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

from core.paths import PROJECT_ROOT

QSS = """
/* 正文整体 +1 号（13→14）；左侧导航 +3 号（13→16） */
QWidget {
    background-color: #f5f8fb;
    color: #1a2433;
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 14px;
}
QMainWindow, QDialog {
    background-color: #f5f8fb;
}
QLabel#h1 {
    font-size: 21px;
    font-weight: 700;
    color: #1a9e94;
}
QLabel#h2 {
    font-size: 16px;
    font-weight: 600;
    color: #2c3e50;
}
QLabel#sub {
    color: #5a6b7d;
    font-size: 13px;
}
QPushButton {
    background-color: #39c5bb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #4dd6cc;
}
QPushButton:pressed {
    background-color: #2aa89f;
}
QPushButton:disabled {
    background-color: #c5d0db;
    color: #f0f4f8;
}
QPushButton#danger {
    background-color: #e85d5d;
    color: white;
}
QPushButton#danger:hover {
    background-color: #f07070;
}
QPushButton#secondary {
    background-color: #e8eef5;
    color: #2c3e50;
    border: 1px solid #cfd9e6;
}
QPushButton#secondary:hover {
    background-color: #dce6f2;
}
/* 左侧导航：字号放大 3 号 */
QListWidget#nav {
    background-color: #ffffff;
    border: 1px solid #d5dee8;
    border-radius: 12px;
    padding: 8px;
    outline: none;
    font-size: 16px;
}
QListWidget#nav::item {
    padding: 14px 16px;
    border-radius: 8px;
    margin: 3px 0;
    color: #3a4a5c;
    font-size: 16px;
}
QListWidget#nav::item:selected {
    background-color: #e0f7f5;
    color: #1a9e94;
    font-weight: 700;
    font-size: 16px;
}
QListWidget#nav::item:hover {
    background-color: #f0f6fa;
}
QListWidget {
    background-color: #ffffff;
    border: 1px solid #d5dee8;
    border-radius: 12px;
    padding: 6px;
    outline: none;
    font-size: 14px;
}
QListWidget::item {
    padding: 11px 14px;
    border-radius: 8px;
    margin: 2px 0;
    color: #3a4a5c;
    font-size: 14px;
}
QListWidget::item:selected {
    background-color: #e0f7f5;
    color: #1a9e94;
    font-weight: 600;
}
QListWidget::item:hover {
    background-color: #f0f6fa;
}
QTextEdit, QPlainTextEdit {
    background-color: #ffffff;
    border: 1px solid #d5dee8;
    border-radius: 8px;
    color: #2c3e50;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 13px;
    selection-background-color: #b8ebe6;
}
QStatusBar {
    background-color: #eef3f8;
    color: #5a6b7d;
    border-top: 1px solid #d5dee8;
    font-size: 13px;
}
QFrame#card {
    background-color: #ffffff;
    border: 1px solid #d5dee8;
    border-radius: 12px;
}
QProgressBar {
    border: none;
    border-radius: 6px;
    background: #e2eaf2;
    height: 12px;
    text-align: center;
    color: #1a2433;
    font-size: 13px;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #39c5bb, stop:1 #7ae0d8);
}
QTabWidget::pane {
    border: 1px solid #d5dee8;
    border-radius: 8px;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: #e8eef5;
    color: #5a6b7d;
    padding: 9px 16px;
    margin-right: 3px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border: 1px solid #d5dee8;
    border-bottom: none;
    font-size: 14px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #1a9e94;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background: #f0f6fa;
}
QMessageBox {
    background-color: #ffffff;
}
QMessageBox QLabel {
    color: #1a2433;
    font-size: 14px;
}
"""


def app_icon() -> QIcon:
    """Load miku face icon for window / taskbar (prefer multi-size .ico on Windows)."""
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    # .ico first so Windows taskbar gets proper multi-resolution glyphs
    candidates = [
        PROJECT_ROOT / "miku" / "icon.ico",
        Path(__file__).resolve().parent.parent / "icon.ico",
        Path(meipass) / "miku" / "icon.png" if meipass else None,
        Path(meipass) / "miku" / "icon.ico" if meipass else None,
        PROJECT_ROOT / "miku" / "icon.png",
        PROJECT_ROOT / "frontend" / "assets" / "miku.ico",
    ]
    icon = QIcon()
    for p in candidates:
        if p is None or not p.exists():
            continue
        icon.addFile(str(p))
        if not icon.isNull():
            return icon
    return QIcon()

