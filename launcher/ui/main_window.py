"""主窗口：控制台 + 托盘守护 + 隐藏/显示桌宠。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    Property,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)

from core.envcheck import run_env_check
from core.paths import APP_NAME, APP_VERSION, PROJECT_ROOT, USER_DIR, deploy_mode_detail, deploy_mode_label
from core.services import ServiceManager, read_pet_control
from ui.theme import app_icon


class LogBus(QObject):
    line = Signal(str, str)


class AnimatedCheckBox(QCheckBox):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._check_progress = 1.0 if self.isChecked() else 0.0
        self._animation = QPropertyAnimation(self, b"checkProgress", self)
        self._animation.setDuration(170)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_check)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _get_check_progress(self) -> float:
        return self._check_progress

    def _set_check_progress(self, value: float) -> None:
        self._check_progress = max(0.0, min(1.0, value))
        self.update()

    checkProgress = Property(float, _get_check_progress, _set_check_progress)

    def _animate_check(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._check_progress)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    @staticmethod
    def _mix(start: QColor, end: QColor, amount: float) -> QColor:
        return QColor(
            round(start.red() + (end.red() - start.red()) * amount),
            round(start.green() + (end.green() - start.green()) * amount),
            round(start.blue() + (end.blue() - start.blue()) * amount),
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        return QSize(base.width() + 8, max(base.height(), 26))

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        box_size = 18.0
        box = QRectF(1.0, (self.height() - box_size) / 2.0, box_size, box_size)
        progress = self._check_progress
        background = self._mix(QColor("#ffffff"), QColor("#39c5bb"), progress)
        border = self._mix(QColor("#9aa9b8"), QColor("#2aa89f"), progress)
        if not self.isEnabled():
            background.setAlpha(120)
            border.setAlpha(120)

        painter.setPen(QPen(border, 1.5))
        painter.setBrush(background)
        painter.drawRoundedRect(box, 4.0, 4.0)

        if progress > 0.0:
            first = QPointF(box.left() + 4.0, box.top() + 9.2)
            middle = QPointF(box.left() + 7.6, box.top() + 12.8)
            end = QPointF(box.left() + 14.3, box.top() + 5.2)
            pen = QPen(QColor("#ffffff"), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            if progress <= 0.42:
                amount = progress / 0.42
                painter.drawLine(first, first + (middle - first) * amount)
            else:
                painter.drawLine(first, middle)
                amount = (progress - 0.42) / 0.58
                painter.drawLine(middle, middle + (end - middle) * amount)

        text_rect = self.rect().adjusted(27, 0, 0, 0)
        text_color = self.palette().windowText().color()
        if not self.isEnabled():
            text_color.setAlpha(130)
        painter.setPen(text_color)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.text(),
        )

        if self.hasFocus():
            focus = QPen(QColor("#39c5bb"), 1.0, Qt.PenStyle.DotLine)
            painter.setPen(focus)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(0, 1, -1, -1), 4, 4)


class _StartWorker(QThread):
    progress = Signal(str, int)
    finished_ok = Signal(bool)

    def __init__(self, services: ServiceManager) -> None:
        super().__init__()
        self._services = services

    def run(self) -> None:
        ok = self._services.start_all(progress=lambda m, p: self.progress.emit(m, p))
        self.finished_ok.emit(ok)


class _EnvWorker(QThread):
    progress = Signal(str, int)
    finished_ok = Signal(object)

    def run(self) -> None:
        report = run_env_check(progress=lambda m, p: self.progress.emit(m, p))
        self.finished_ok.emit(report)


class _StopWorker(QThread):
    finished_ok = Signal()

    def __init__(self, services: ServiceManager, *, backend_only: bool = False) -> None:
        super().__init__()
        self._services = services
        self._backend_only = backend_only

    def run(self) -> None:
        try:
            if self._backend_only:
                self._services.stop_backend_only()
            else:
                self._services.stop_all()
        except Exception as exc:
            self._services.log("system", f"停止服务时发生错误：{exc}")
        finally:
            self.finished_ok.emit()


def _config_path():
    return USER_DIR / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(config: dict) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "MikuCureLauncher"


def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --autostart'
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{Path(sys.executable).resolve()}" "{main_py}" --autostart'


def _windows_autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE_NAME)
            if value and value != _autostart_command():
                winreg.SetValueEx(
                    key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, _autostart_command()
                )
        return bool(value)
    except (FileNotFoundError, OSError):
        return False


def _set_windows_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        raise OSError("当前系统不支持 Windows 开机自启")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, _RUN_VALUE_NAME)
            except FileNotFoundError:
                pass


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(980, 640)
        self.setMinimumSize(860, 520)

        self.logbus = LogBus()
        self.services = ServiceManager(log=self.logbus.line.emit)
        self._force_quit = False
        self._linked_stop_done = False
        self._start_worker: _StartWorker | None = None
        self._env_worker: _EnvWorker | None = None
        self._stop_worker: _StopWorker | None = None
        self._exit_after_stop = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(176)
        for name in ("控制台", "环境检查", "系统设置", "关于"):
            QListWidgetItem(name, self.nav)
        self.nav.setCurrentRow(0)
        root.addWidget(self.nav)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.page_dash = self._build_dashboard()
        self.page_env = self._build_env_page()
        self.page_system = self._build_system_page()
        self.page_about = self._build_about()
        self.stack.addWidget(self.page_dash)
        self.stack.addWidget(self.page_env)
        self.stack.addWidget(self.page_system)
        self.stack.addWidget(self.page_about)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.logbus.line.connect(self._on_log)
        self.statusBar().showMessage(deploy_mode_label())

        self._setup_tray()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(600)
        self._refresh_status()
        self._apply_launcher_language()
        QTimer.singleShot(200, self.refresh_env)
        QTimer.singleShot(700, self._auto_start_services)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()

        self.act_show_launcher = QAction("显示启动器", self)
        self.act_show_launcher.triggered.connect(self._restore_from_tray)
        menu.addAction(self.act_show_launcher)

        self.act_toggle_pet = QAction("隐藏桌宠", self)
        self.act_toggle_pet.triggered.connect(self._tray_toggle_pet)
        menu.addAction(self.act_toggle_pet)

        menu.addSeparator()
        self.act_exit = QAction("退出（停止全部服务）", self)
        self.act_exit.triggered.connect(self._tray_exit)
        menu.addAction(self.act_exit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_toggle_pet(self) -> None:
        if not self.services.electron_running():
            self.tray.showMessage(APP_NAME, "桌宠未运行", QSystemTrayIcon.MessageIcon.Information, 2000)
            return
        self.services.toggle_pet()
        self._refresh_status()

    def _tray_exit(self) -> None:
        self._begin_stop(exit_after=True)

    def _build_dashboard(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)

        self.dash_head = QLabel("控制台")
        self.dash_head.setObjectName("h1")
        sub = QLabel(deploy_mode_detail())
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        lay.addWidget(self.dash_head)
        lay.addWidget(sub)

        self.status_label = QLabel("—")
        self.status_label.setObjectName("h2")
        lay.addWidget(self.status_label)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("sub")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        self.progress_label.hide()
        lay.addWidget(self.progress_label)
        lay.addWidget(self.progress_bar)

        btns = QHBoxLayout()
        self.btn_start = QPushButton("一键启动")
        self.btn_start.clicked.connect(self._start_all)
        self.btn_stop = QPushButton("停止服务")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.clicked.connect(self._stop_all)
        self.btn_toggle_pet = QPushButton("隐藏桌宠")
        self.btn_toggle_pet.setObjectName("secondary")
        self.btn_toggle_pet.clicked.connect(self._toggle_pet_btn)
        self.btn_toggle_pet.setEnabled(False)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_stop)
        btns.addWidget(self.btn_toggle_pet)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.dash_tip = QLabel(
            "启动器是守护精灵：关闭窗口将最小化到托盘；右键托盘可隐藏/显示桌宠或完全退出。"
        )
        self.dash_tip.setObjectName("sub")
        self.dash_tip.setWordWrap(True)
        lay.addWidget(self.dash_tip)

        self.tabs = QTabWidget()
        self.log_all = QPlainTextEdit()
        self.log_all.setReadOnly(True)
        self.log_backend = QPlainTextEdit()
        self.log_backend.setReadOnly(True)
        self.log_electron = QPlainTextEdit()
        self.log_electron.setReadOnly(True)
        self.tabs.addTab(self.log_all, "全部日志")
        self.tabs.addTab(self.log_backend, "后端")
        self.tabs.addTab(self.log_electron, "桌宠")
        lay.addWidget(self.tabs, 1)
        return w

    def _build_env_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.env_head = QLabel("环境检查")
        self.env_head.setObjectName("h1")
        lay.addWidget(self.env_head)
        self.env_progress_label = QLabel("")
        self.env_progress_label.setObjectName("sub")
        self.env_progress = QProgressBar()
        self.env_progress.setRange(0, 100)
        self.env_progress.hide()
        self.env_progress_label.hide()
        lay.addWidget(self.env_progress_label)
        lay.addWidget(self.env_progress)
        self.env_list = QPlainTextEdit()
        self.env_list.setReadOnly(True)
        lay.addWidget(self.env_list, 1)
        btn = QPushButton("重新检查")
        btn.setObjectName("secondary")
        btn.clicked.connect(self.refresh_env)
        self.btn_env = btn
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)
        return w

    def _build_about(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._label("h1", "关于 Miku Cure 启动器"))
        lay.addWidget(self._label("sub", f"版本 {APP_VERSION}"))
        lay.addWidget(self._label("sub", f"项目根：{PROJECT_ROOT}"))
        tip = QLabel(
            "启动器是守护进程：\n"
            "· 一键启动 / 停止 后端与桌宠\n"
            "· 关闭窗口 = 最小化到托盘（服务继续）\n"
            "· 托盘右键：隐藏/显示桌宠、退出并停止全部服务\n"
            "· 默认 RNN 情绪模型；便携包 CPU 推理"
        )
        tip.setWordWrap(True)
        tip.setObjectName("sub")
        lay.addWidget(tip)
        lay.addStretch(1)
        return w

    def _build_system_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)
        self.system_head = self._label("h1", "系统设置")
        self.system_tip = self._label("sub", "语言设置同时应用于启动器和桌宠前端。")
        lay.addWidget(self.system_head)
        lay.addWidget(self.system_tip)

        form = QFormLayout()
        form.setSpacing(12)
        self.lang_select = QComboBox()
        self.lang_select.addItem("中文", "zh")
        self.lang_select.addItem("日本語", "ja")
        self.lang_select.addItem("English", "en")
        current_lang = _load_config().get("miku-language", "zh")
        index = self.lang_select.findData(current_lang)
        self.lang_select.setCurrentIndex(max(index, 0))
        self.lang_select.currentIndexChanged.connect(self._save_language)
        self.lang_label = QLabel("语言")
        form.addRow(self.lang_label, self.lang_select)
        self.close_action_select = QComboBox()
        self.close_action_select.addItem("每次询问", "ask")
        self.close_action_select.addItem("最小化到托盘", "tray")
        self.close_action_select.addItem("退出并停止服务", "exit")
        close_action = _load_config().get("launcher-close-action", "ask")
        self.close_action_select.setCurrentIndex(max(self.close_action_select.findData(close_action), 0))
        self.close_action_select.currentIndexChanged.connect(self._save_close_action)
        self.close_action_label = QLabel("关闭窗口时")
        form.addRow(self.close_action_label, self.close_action_select)

        self.windows_autostart_check = AnimatedCheckBox("开机自动启动 Miku Cure")
        self.windows_autostart_check.setChecked(_windows_autostart_enabled())
        self.windows_autostart_check.toggled.connect(self._save_windows_autostart)
        form.addRow(self.windows_autostart_check)

        self.auto_monitor_check = AnimatedCheckBox(
            "启动桌宠时自动连接摄像头并开启情绪监控"
        )
        config = _load_config()
        self.auto_monitor_check.setChecked(
            bool(
                config.get(
                    "camera-monitor-on-start",
                    config.get("launcher-auto-monitor", True),
                )
            )
        )
        self.auto_monitor_check.toggled.connect(self._save_auto_monitor)
        form.addRow(self.auto_monitor_check)
        lay.addLayout(form)

        folders = (
            ("打开音乐文件夹", PROJECT_ROOT / "miku" / "sing"),
            ("打开跳舞（视频）文件夹", PROJECT_ROOT / "miku" / "dance"),
            ("打开表情文件夹", PROJECT_ROOT / "miku" / "gif"),
        )
        self.folder_buttons = []
        for text, folder in folders:
            btn = QPushButton(text)
            btn.setObjectName("secondary")
            btn.clicked.connect(lambda _checked=False, p=folder: self._open_folder(p))
            lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)
            self.folder_buttons.append(btn)
        lay.addStretch(1)
        return w

    def _save_language(self) -> None:
        config = _load_config()
        config["miku-language"] = self.lang_select.currentData()
        _save_config(config)
        self._apply_launcher_language()
        self.statusBar().showMessage("语言设置已保存，桌宠前端会立即同步或在下次启动时生效")
        if self.services.electron_running():
            write_pet_command("language", lang=self.lang_select.currentData())

    def _save_close_action(self) -> None:
        config = _load_config()
        action = self.close_action_select.currentData()
        if action == "ask":
            config.pop("launcher-close-action", None)
        else:
            config["launcher-close-action"] = action
        _save_config(config)

    def _save_windows_autostart(self, enabled: bool) -> None:
        try:
            _set_windows_autostart(enabled)
            self.statusBar().showMessage(
                "已开启开机自启" if enabled else "已关闭开机自启"
            )
        except OSError as exc:
            self.windows_autostart_check.blockSignals(True)
            self.windows_autostart_check.setChecked(not enabled)
            self.windows_autostart_check.blockSignals(False)
            QMessageBox.warning(self, APP_NAME, f"无法修改开机自启：\n{exc}")

    def _save_auto_monitor(self, enabled: bool) -> None:
        config = _load_config()
        config["camera-monitor-on-start"] = enabled
        config.pop("launcher-auto-monitor", None)
        _save_config(config)
        self.statusBar().showMessage(
            "启动桌宠时将开启摄像头情绪监控"
            if enabled
            else "启动桌宠时摄像头保持关闭"
        )

    def _auto_start_services(self) -> None:
        if os.environ.get("MIKU_SKIP_AUTO_START") == "1":
            return
        if self._env_worker and self._env_worker.isRunning():
            QTimer.singleShot(400, self._auto_start_services)
            return
        if not self.services.any_running():
            self.services.log("system", "启动器已就绪，自动启动后端与桌宠")
            self._start_all()

    def _apply_launcher_language(self) -> None:
        lang = self.lang_select.currentData() if hasattr(self, "lang_select") else "zh"
        texts = {
            "zh": {
                "nav": ("控制台", "环境检查", "系统设置", "关于"),
                "dash": "控制台", "env": "环境检查", "system": "系统设置",
                "tip": "语言设置同时应用于启动器和桌宠前端。",
                "language": "语言", "close": "关闭窗口时",
                "actions": ("每次询问", "最小化到托盘", "退出并停止服务"),
                "windows_autostart": "开机自动启动 Miku Cure",
                "auto_monitor": "启动桌宠时自动连接摄像头并开启情绪监控",
                "folders": ("打开音乐文件夹", "打开跳舞（视频）文件夹", "打开表情文件夹"),
                "show": "显示启动器", "exit": "退出（停止全部服务）",
                "start": "一键启动", "stop": "停止服务",
            },
            "ja": {
                "nav": ("コンソール", "環境チェック", "システム設定", "このアプリについて"),
                "dash": "コンソール", "env": "環境チェック", "system": "システム設定",
                "tip": "言語設定はランチャーとデスクトップペットの両方に適用されます。",
                "language": "言語", "close": "ウィンドウを閉じる時",
                "actions": ("毎回確認", "トレイに最小化", "終了してサービスを停止"),
                "windows_autostart": "Windows 起動時に Miku Cure を起動",
                "auto_monitor": "ペット起動時にカメラへ接続して感情モニターを開始",
                "folders": ("音楽フォルダーを開く", "ダンス（動画）フォルダーを開く", "表情フォルダーを開く"),
                "show": "ランチャーを表示", "exit": "終了（全サービス停止）",
                "start": "すべて起動", "stop": "サービス停止",
            },
            "en": {
                "nav": ("Console", "Environment", "System Settings", "About"),
                "dash": "Console", "env": "Environment Check", "system": "System Settings",
                "tip": "The language setting applies to both the launcher and desktop pet.",
                "language": "Language", "close": "When closing",
                "actions": ("Ask every time", "Minimize to tray", "Exit and stop services"),
                "windows_autostart": "Start Miku Cure with Windows",
                "auto_monitor": "Connect the camera and monitor emotions when the pet starts",
                "folders": ("Open music folder", "Open dance video folder", "Open expression folder"),
                "show": "Show launcher", "exit": "Exit (stop all services)",
                "start": "Start all", "stop": "Stop services",
            },
        }[lang if lang in ("zh", "ja", "en") else "zh"]
        for index, value in enumerate(texts["nav"]):
            self.nav.item(index).setText(value)
        self.dash_head.setText(texts["dash"])
        self.env_head.setText(texts["env"])
        self.system_head.setText(texts["system"])
        self.system_tip.setText(texts["tip"])
        self.lang_label.setText(texts["language"])
        self.close_action_label.setText(texts["close"])
        self.windows_autostart_check.setText(texts["windows_autostart"])
        self.auto_monitor_check.setText(texts["auto_monitor"])
        for index, value in enumerate(texts["actions"]):
            self.close_action_select.setItemText(index, value)
        for button, value in zip(self.folder_buttons, texts["folders"]):
            button.setText(value)
        self.act_show_launcher.setText(texts["show"])
        self.act_exit.setText(texts["exit"])
        self.btn_start.setText(texts["start"])
        self.btn_stop.setText(texts["stop"])

    def _open_folder(self, folder) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"无法打开文件夹：\n{folder}\n\n{exc}")

    @staticmethod
    def _label(obj: str, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName(obj)
        return lb

    def _show_progress(self, msg: str, pct: int, *, env_page: bool = False) -> None:
        if env_page:
            self.env_progress_label.show()
            self.env_progress.show()
            self.env_progress_label.setText(msg)
            self.env_progress.setValue(pct)
        self.progress_label.show()
        self.progress_bar.show()
        self.progress_label.setText(msg)
        self.progress_bar.setValue(pct)
        self.statusBar().showMessage(msg)

    def _hide_progress(self, *, env_page: bool = False) -> None:
        self.progress_label.hide()
        self.progress_bar.hide()
        if env_page:
            self.env_progress_label.hide()
            self.env_progress.hide()

    def refresh_env(self) -> None:
        if self._env_worker and self._env_worker.isRunning():
            return
        self.btn_env.setEnabled(False)
        self.env_list.setPlainText("环境检查中，请稍候…")
        self._show_progress("环境检查中…", 5, env_page=True)
        worker = _EnvWorker()
        self._env_worker = worker

        def on_prog(msg: str, pct: int) -> None:
            self._show_progress(msg, pct, env_page=True)

        def on_done(report) -> None:
            lines = [report.summary_line(), ""]
            for it in report.items:
                mark = "✓" if it.ok else "✗"
                req = "" if it.required else " (可选)"
                lines.append(f"{mark} {it.name}{req}")
                lines.append(f"    {it.detail}")
            self.env_list.setPlainText("\n".join(lines))
            self.statusBar().showMessage(report.summary_line())
            self._hide_progress(env_page=True)
            self.btn_env.setEnabled(True)

        worker.progress.connect(on_prog)
        worker.finished_ok.connect(on_done)
        worker.start()

    def _start_all(self) -> None:
        if self._start_worker and self._start_worker.isRunning():
            return
        if self.services.any_running():
            return
        self._linked_stop_done = False
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self._show_progress("正在启动…", 5)
        worker = _StartWorker(self.services)
        self._start_worker = worker

        def on_prog(msg: str, pct: int) -> None:
            self._show_progress(msg, pct)

        def on_done(ok: bool) -> None:
            self._hide_progress()
            self._refresh_status()
            self.statusBar().showMessage("启动完成" if ok else "启动未完全成功，请查看日志")

        worker.progress.connect(on_prog)
        worker.finished_ok.connect(on_done)
        worker.start()

    def _stop_all(self) -> None:
        self._begin_stop(exit_after=False)

    def _begin_stop(self, *, exit_after: bool, backend_only: bool = False) -> None:
        if self._stop_worker and self._stop_worker.isRunning():
            self._exit_after_stop = self._exit_after_stop or exit_after
            return
        self._exit_after_stop = exit_after
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.statusBar().showMessage("正在停止服务…")
        worker = _StopWorker(self.services, backend_only=backend_only)
        self._stop_worker = worker

        def on_done() -> None:
            if not backend_only:
                self._linked_stop_done = False
            self._refresh_status()
            if self._exit_after_stop:
                self._force_quit = True
                self.tray.hide()
                QApplication.instance().quit()
            else:
                self.statusBar().showMessage("服务已停止")

        worker.finished_ok.connect(on_done)
        worker.start()

    def _toggle_pet_btn(self) -> None:
        self.services.toggle_pet()
        self._refresh_status()

    def _refresh_status(self) -> None:
        # Sync pet_hidden from control file if electron wrote back
        ctrl = read_pet_control()
        if ctrl.get("state") == "hidden":
            self.services.pet_hidden = True
        elif ctrl.get("state") == "visible":
            self.services.pet_hidden = False

        stop_in_progress = bool(self._stop_worker and self._stop_worker.isRunning())

        # During an intentional stop, the worker owns both process handles.
        # Do not start a second linked stop or clear a handle underneath it.
        if (
            not stop_in_progress
            and self.services.electron_proc is not None
            and self.services.electron_proc.poll() is not None
        ):
            if not self._linked_stop_done:
                self._linked_stop_done = True
                self.services.log("system", "检测到桌宠已退出，正在停止后端…")
                self._begin_stop(exit_after=False, backend_only=True)
            self.services.electron_proc = None
            self.services.pet_hidden = False
        elif (
            not stop_in_progress
            and
            ctrl.get("action") == "pet_closed"
            and ctrl.get("launch_session") == self.services.launch_session
            and self.services.electron_running()
            and not self._linked_stop_done
            and self.services.backend_running()
        ):
            # Electron external-backend mode signals pet closed without killing backend itself
            self._linked_stop_done = True
            self.services.log("system", "桌宠发来关闭信号，停止后端…")
            self._begin_stop(exit_after=False, backend_only=True)
            if self.services.electron_proc and self.services.electron_proc.poll() is not None:
                self.services.electron_proc = None
            self.services.pet_hidden = False

        if (
            not stop_in_progress
            and self.services.backend_proc is not None
            and self.services.backend_proc.poll() is not None
        ):
            self.services.backend_proc = None

        self.status_label.setText(self.services.status_text())
        busy = bool(
            (self._start_worker and self._start_worker.isRunning())
            or (self._env_worker and self._env_worker.isRunning())
            or (self._stop_worker and self._stop_worker.isRunning())
        )
        running = self.services.any_running()
        self.btn_start.setEnabled(not running and not busy)
        self.btn_stop.setEnabled(running and not busy)
        pet_on = self.services.electron_running()
        self.btn_toggle_pet.setEnabled(pet_on and not busy)
        if pet_on:
            self.btn_toggle_pet.setText("显示桌宠" if self.services.pet_hidden else "隐藏桌宠")
            self.act_toggle_pet.setText("显示桌宠" if self.services.pet_hidden else "隐藏桌宠")
            self.act_toggle_pet.setEnabled(True)
        else:
            self.btn_toggle_pet.setText("隐藏桌宠")
            self.act_toggle_pet.setText("隐藏桌宠")
            self.act_toggle_pet.setEnabled(False)

    def _on_log(self, source: str, text: str) -> None:
        line = f"[{source}] {text}"
        self.log_all.appendPlainText(line)
        self.log_all.moveCursor(QTextCursor.MoveOperation.End)
        if source == "backend":
            self.log_backend.appendPlainText(text)
            self.log_backend.moveCursor(QTextCursor.MoveOperation.End)
        elif source == "electron":
            self.log_electron.appendPlainText(text)
            self.log_electron.moveCursor(QTextCursor.MoveOperation.End)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._force_quit:
            event.accept()
            return
        config = _load_config()
        remembered = config.get("launcher-close-action")
        if remembered == "tray":
            event.ignore()
            self._minimize_to_tray()
            return
        if remembered == "exit":
            event.ignore()
            self.hide()
            self._begin_stop(exit_after=True)
            return

        box = QMessageBox(self)
        box.setWindowTitle("关闭启动器")
        box.setText("关闭窗口后要执行什么操作？")
        box.setInformativeText("最小化会保持服务运行；退出会关闭桌宠和后端服务。")
        btn_tray = box.addButton("最小化到托盘", QMessageBox.ButtonRole.AcceptRole)
        btn_exit = box.addButton("退出并停止服务", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        remember = AnimatedCheckBox("记住我的选择")
        box.setCheckBox(remember)
        box.exec()
        chosen = box.clickedButton()
        if chosen not in (btn_tray, btn_exit):
            event.ignore()
            return
        if remember.isChecked():
            config["launcher-close-action"] = "tray" if chosen is btn_tray else "exit"
            _save_config(config)
        event.ignore()
        if chosen is btn_exit:
            self.hide()
            self._begin_stop(exit_after=True)
        else:
            self._minimize_to_tray()

    def _minimize_to_tray(self) -> None:
        self.hide()
        self.tray.showMessage(
            APP_NAME,
            "已最小化到托盘。右键托盘图标可退出或控制桌宠。",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )
        self.statusBar().showMessage("已最小化到托盘")
