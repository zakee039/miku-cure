"""主窗口：控制台 + 托盘守护 + 隐藏/显示桌宠。"""
from __future__ import annotations

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

from core.envcheck import EnvCheckCancelled, run_env_check
from core.i18n import (
    environment_summary,
    get_texts,
    translate_environment_detail,
    translate_progress,
)
from core.jsonio import atomic_write_json, read_json
from core.paths import APP_VERSION, IS_PORTABLE, PROJECT_ROOT, USER_DIR
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
    cancelled = Signal()

    def run(self) -> None:
        try:
            report = run_env_check(
                progress=lambda m, p: self.progress.emit(m, p),
                cancelled=self.isInterruptionRequested,
            )
        except EnvCheckCancelled:
            self.cancelled.emit()
            return
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
    config = read_json(_config_path(), {})
    return config if isinstance(config, dict) else {}


def _save_config(config: dict) -> None:
    atomic_write_json(_config_path(), config, indent=2)


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
    def __init__(self, initial_env_report=None) -> None:
        super().__init__()
        self.setWindowTitle(f"Miku Cure  v{APP_VERSION}")
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
        self._restart_after_stop = False
        self._restart_spinner_frames = ("◐", "◓", "◑", "◒")
        self._restart_spinner_index = 0
        self._restart_spinner_timer = QTimer(self)
        self._restart_spinner_timer.setInterval(120)
        self._restart_spinner_timer.timeout.connect(self._advance_restart_spinner)
        self._last_env_report = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(176)
        for _ in range(4):
            QListWidgetItem("", self.nav)
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
        self.statusBar().showMessage("")

        self._setup_tray()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(600)
        self._refresh_status()
        self._apply_launcher_language()
        if initial_env_report is not None:
            self._show_env_report(initial_env_report)
        else:
            QTimer.singleShot(200, self.refresh_env)
        QTimer.singleShot(700, self._auto_start_services)

    def _setup_tray(self) -> None:
        texts = self._texts()
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(texts["app_title"])
        menu = QMenu()

        self.act_show_launcher = QAction(texts["show_launcher"], self)
        self.act_show_launcher.triggered.connect(self._restore_from_tray)
        menu.addAction(self.act_show_launcher)

        self.act_toggle_pet = QAction(texts["hide_pet"], self)
        self.act_toggle_pet.triggered.connect(self._tray_toggle_pet)
        menu.addAction(self.act_toggle_pet)

        menu.addSeparator()
        self.act_exit = QAction(texts["exit_all"], self)
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
            texts = self._texts()
            self.tray.showMessage(
                texts["app_title"],
                texts["pet_not_running"],
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
            return
        self.services.toggle_pet()
        self._refresh_status()

    def _tray_exit(self) -> None:
        self._begin_stop(exit_after=True)

    def _build_dashboard(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)

        self.dash_head = QLabel("")
        self.dash_head.setObjectName("h1")
        self.deploy_sub = QLabel("")
        self.deploy_sub.setObjectName("sub")
        self.deploy_sub.setWordWrap(True)
        lay.addWidget(self.dash_head)
        lay.addWidget(self.deploy_sub)

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
        self.btn_start = QPushButton("")
        self.btn_start.clicked.connect(self._start_all)
        self.btn_stop = QPushButton("")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.clicked.connect(self._stop_all)
        self.btn_toggle_pet = QPushButton("")
        self.btn_toggle_pet.setObjectName("secondary")
        self.btn_toggle_pet.clicked.connect(self._toggle_pet_btn)
        self.btn_toggle_pet.setEnabled(False)
        self.btn_restart = QPushButton("")
        self.btn_restart.setObjectName("secondary")
        self.btn_restart.clicked.connect(self._restart_all)
        self.btn_restart.setEnabled(False)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_stop)
        btns.addWidget(self.btn_toggle_pet)
        btns.addWidget(self.btn_restart)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.dash_tip = QLabel("")
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
        self.tabs.addTab(self.log_all, "")
        self.tabs.addTab(self.log_backend, "")
        self.tabs.addTab(self.log_electron, "")
        lay.addWidget(self.tabs, 1)
        return w

    def _build_env_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.env_head = QLabel("")
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
        btn = QPushButton("")
        btn.setObjectName("secondary")
        btn.clicked.connect(self.refresh_env)
        self.btn_env = btn
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)
        return w

    def _build_about(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.about_head = self._label("h1", "")
        self.about_version = self._label("sub", "")
        self.about_root = self._label("sub", "")
        self.about_tip = QLabel("")
        self.about_tip.setWordWrap(True)
        self.about_tip.setObjectName("sub")
        lay.addWidget(self.about_head)
        lay.addWidget(self.about_version)
        lay.addWidget(self.about_root)
        lay.addWidget(self.about_tip)
        lay.addStretch(1)
        return w

    def _build_system_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)
        self.system_head = self._label("h1", "")
        self.system_tip = self._label("sub", "")
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
        self.lang_label = QLabel("")
        form.addRow(self.lang_label, self.lang_select)
        self.close_action_select = QComboBox()
        self.close_action_select.addItem("", "ask")
        self.close_action_select.addItem("", "tray")
        self.close_action_select.addItem("", "exit")
        close_action = _load_config().get("launcher-close-action", "ask")
        self.close_action_select.setCurrentIndex(max(self.close_action_select.findData(close_action), 0))
        self.close_action_select.currentIndexChanged.connect(self._save_close_action)
        self.close_action_label = QLabel("")
        form.addRow(self.close_action_label, self.close_action_select)

        self.windows_autostart_check = AnimatedCheckBox("")
        self.windows_autostart_check.setChecked(_windows_autostart_enabled())
        self.windows_autostart_check.toggled.connect(self._save_windows_autostart)
        form.addRow(self.windows_autostart_check)

        self.auto_monitor_check = AnimatedCheckBox("")
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
            PROJECT_ROOT / "miku" / "sing",
            PROJECT_ROOT / "miku" / "dance",
            PROJECT_ROOT / "miku" / "gif",
        )
        self.folder_buttons = []
        for folder in folders:
            btn = QPushButton("")
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
        self.statusBar().showMessage(self._texts()["language_saved"])
        self.services.set_language(self.lang_select.currentData())

    def _save_close_action(self) -> None:
        config = _load_config()
        action = self.close_action_select.currentData()
        if action == "ask":
            config.pop("launcher-close-action", None)
        else:
            config["launcher-close-action"] = action
        _save_config(config)

    def _save_windows_autostart(self, enabled: bool) -> None:
        texts = self._texts()
        try:
            _set_windows_autostart(enabled)
            self.statusBar().showMessage(
                texts["autostart_on"] if enabled else texts["autostart_off"]
            )
        except OSError as exc:
            self.windows_autostart_check.blockSignals(True)
            self.windows_autostart_check.setChecked(not enabled)
            self.windows_autostart_check.blockSignals(False)
            QMessageBox.warning(
                self,
                texts["app_title"],
                texts["autostart_error"].format(error=exc),
            )

    def _save_auto_monitor(self, enabled: bool) -> None:
        config = _load_config()
        config["camera-monitor-on-start"] = enabled
        config.pop("launcher-auto-monitor", None)
        _save_config(config)
        texts = self._texts()
        self.statusBar().showMessage(texts["monitor_on"] if enabled else texts["monitor_off"])

    def _auto_start_services(self) -> None:
        if os.environ.get("MIKU_SKIP_AUTO_START") == "1":
            return
        if self._env_worker and self._env_worker.isRunning():
            QTimer.singleShot(400, self._auto_start_services)
            return
        if not self.services.any_running():
            self.services.log("system", "启动器已就绪，自动启动后端与桌宠")
            self._start_all()

    def _language(self) -> str:
        if not hasattr(self, "lang_select"):
            return "zh"
        language = self.lang_select.currentData()
        return language if language in {"zh", "ja", "en"} else "zh"

    def _texts(self) -> dict:
        return get_texts(self._language())

    def _apply_launcher_language(self) -> None:
        texts = self._texts()
        app = QApplication.instance()
        if app is not None:
            app.setApplicationName(texts["app_title"])
        self.setWindowTitle(f"{texts['app_title']}  v{APP_VERSION}")
        self.tray.setToolTip(texts["app_title"])
        for index, value in enumerate(texts["nav"]):
            self.nav.item(index).setText(value)
        self.dash_head.setText(texts["dashboard"])
        self.deploy_sub.setText(
            texts["mode_detail_portable" if IS_PORTABLE else "mode_detail_dev"].format(
                root=PROJECT_ROOT
            )
        )
        self.dash_tip.setText(texts["dashboard_tip"])
        for index, value in enumerate(texts["log_tabs"]):
            self.tabs.setTabText(index, value)
        self.env_head.setText(texts["environment"])
        self.btn_env.setText(texts["recheck"])
        self.system_head.setText(texts["system"])
        self.system_tip.setText(texts["settings_tip"])
        self.lang_label.setText(texts["language"])
        self.close_action_label.setText(texts["close_action"])
        self.windows_autostart_check.setText(texts["windows_autostart"])
        self.auto_monitor_check.setText(texts["auto_monitor"])
        for index, value in enumerate(texts["close_actions"]):
            self.close_action_select.setItemText(index, value)
        for button, value in zip(self.folder_buttons, texts["folders"]):
            button.setText(value)
        self.about_head.setText(texts["about_title"])
        self.about_version.setText(texts["version"].format(version=APP_VERSION))
        self.about_root.setText(texts["project_root"].format(root=PROJECT_ROOT))
        self.about_tip.setText(texts["about_detail"])
        self.act_show_launcher.setText(texts["show_launcher"])
        self.act_exit.setText(texts["exit_all"])
        self.btn_start.setText(texts["start_all"])
        self.btn_stop.setText(texts["stop_services"])
        if self._restart_spinner_timer.isActive():
            self._update_restart_button_text()
        else:
            self.btn_restart.setText(texts["restart_services"])
        if self._last_env_report is not None:
            self._show_env_report(self._last_env_report)
        self._refresh_status()

    def _open_folder(self, folder) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except Exception as exc:
            texts = self._texts()
            QMessageBox.warning(
                self,
                texts["app_title"],
                texts["folder_error"].format(folder=folder, error=exc),
            )

    @staticmethod
    def _label(obj: str, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName(obj)
        return lb

    def _show_progress(self, msg: str, pct: int, *, env_page: bool = False) -> None:
        display_message = translate_progress(self._language(), msg)
        if env_page:
            self.env_progress_label.show()
            self.env_progress.show()
            self.env_progress_label.setText(display_message)
            self.env_progress.setValue(pct)
        self.progress_label.show()
        self.progress_bar.show()
        self.progress_label.setText(display_message)
        self.progress_bar.setValue(pct)
        self.statusBar().showMessage(display_message)

    def _hide_progress(self, *, env_page: bool = False) -> None:
        self.progress_label.hide()
        self.progress_bar.hide()
        if env_page:
            self.env_progress_label.hide()
            self.env_progress.hide()

    def _show_env_report(self, report) -> None:
        self._last_env_report = report
        texts = self._texts()
        summary = environment_summary(self._language(), report)
        lines = [summary, ""]
        for item in report.items:
            mark = "✓" if item.ok else "✗"
            optional = "" if item.required else f" ({texts['env_optional']})"
            name = texts["env_names"].get(item.name, item.name)
            lines.append(f"{mark} {name}{optional}")
            detail = translate_environment_detail(self._language(), item.detail)
            lines.append(f"    {detail}")
        self.env_list.setPlainText("\n".join(lines))
        self.statusBar().showMessage(summary)
        self._hide_progress(env_page=True)
        self.btn_env.setEnabled(True)

    def refresh_env(self) -> None:
        if self._env_worker and self._env_worker.isRunning():
            return
        self.btn_env.setEnabled(False)
        self.env_list.setPlainText(self._texts()["env_checking_wait"])
        self._show_progress("环境检查中…", 5, env_page=True)
        worker = _EnvWorker(self)
        self._env_worker = worker

        def on_prog(msg: str, pct: int) -> None:
            self._show_progress(msg, pct, env_page=True)

        def on_done(report) -> None:
            self._show_env_report(report)

        def on_cancelled() -> None:
            self._hide_progress(env_page=True)
            self.btn_env.setEnabled(True)

        worker.progress.connect(on_prog)
        worker.finished_ok.connect(on_done)
        worker.cancelled.connect(on_cancelled)
        worker.start()

    def shutdown_workers(self) -> None:
        """Cancel background waits before Qt destroys their QThread objects."""
        self._timer.stop()
        self._restart_spinner_timer.stop()
        self.services.cancel_startup()

        env_worker = self._env_worker
        if env_worker is not None and env_worker.isRunning():
            env_worker.requestInterruption()
            if not env_worker.wait(2500):
                self.services.log("system", "环境检查线程未能在退出前及时结束")

        # These workers are normally already complete when quit is requested.
        # A short wait closes the small signal-delivery window at app teardown.
        for worker in (self._start_worker, self._stop_worker):
            if worker is not None and worker.isRunning():
                worker.wait(2500)
        self.services.stop_heartbeat()

    def _start_all(self, *, restarting: bool = False) -> None:
        if self._start_worker and self._start_worker.isRunning():
            if restarting:
                self._stop_restart_spinner()
            return
        if self.services.any_running():
            if restarting:
                self._stop_restart_spinner()
            return
        center = self.frameGeometry().center()
        self.services.set_launch_display_point(center.x(), center.y())
        self._linked_stop_done = False
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_restart.setEnabled(False)
        self._show_progress("正在重新启动…" if restarting else "正在启动…", 5)
        worker = _StartWorker(self.services)
        self._start_worker = worker

        def on_prog(msg: str, pct: int) -> None:
            self._show_progress(msg, pct)

        def on_done(ok: bool) -> None:
            self._hide_progress()
            self._refresh_status()
            texts = self._texts()
            if restarting:
                self._stop_restart_spinner()
                message = texts["restart_done"] if ok else texts["restart_failed"]
            else:
                message = texts["start_done"] if ok else texts["start_failed"]
            self.statusBar().showMessage(message)

        worker.progress.connect(on_prog)
        worker.finished_ok.connect(on_done)
        worker.start()
        # Stop doubles as "cancel startup" while backend readiness is pending.
        self.btn_stop.setEnabled(True)

    def _stop_all(self) -> None:
        self._begin_stop(exit_after=False)

    def _update_restart_button_text(self) -> None:
        frame = self._restart_spinner_frames[self._restart_spinner_index]
        self.btn_restart.setText(f"{frame}  {self._texts()['restarting_button']}")

    def _advance_restart_spinner(self) -> None:
        self._restart_spinner_index = (
            self._restart_spinner_index + 1
        ) % len(self._restart_spinner_frames)
        self._update_restart_button_text()

    def _start_restart_spinner(self) -> None:
        self._restart_spinner_index = 0
        self._update_restart_button_text()
        self._restart_spinner_timer.start()

    def _stop_restart_spinner(self) -> None:
        self._restart_spinner_timer.stop()
        self.btn_restart.setText(self._texts()["restart_services"])

    def _restart_all(self) -> None:
        if not self.services.any_running():
            return
        if (self._start_worker and self._start_worker.isRunning()) or (
            self._stop_worker and self._stop_worker.isRunning()
        ):
            return
        center = self.frameGeometry().center()
        self.services.set_launch_display_point(center.x(), center.y())
        self._start_restart_spinner()
        self._show_progress("正在重启服务…", 5)
        self._begin_stop(exit_after=False, restart_after=True)

    def _begin_stop(
        self,
        *,
        exit_after: bool,
        backend_only: bool = False,
        restart_after: bool = False,
    ) -> None:
        if self._stop_worker and self._stop_worker.isRunning():
            self._exit_after_stop = self._exit_after_stop or exit_after
            if exit_after or not restart_after:
                self._restart_after_stop = False
                self._stop_restart_spinner()
            return
        self._exit_after_stop = exit_after
        self._restart_after_stop = restart_after and not exit_after and not backend_only
        if not self._restart_after_stop:
            self._stop_restart_spinner()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_restart.setEnabled(False)
        self.statusBar().showMessage(
            self._texts()["restarting" if self._restart_after_stop else "stopping"]
        )
        worker = _StopWorker(self.services, backend_only=backend_only)
        self._stop_worker = worker

        def on_done() -> None:
            if not backend_only:
                self._linked_stop_done = False
            self._refresh_status()
            if self._exit_after_stop:
                self._restart_after_stop = False
                self._stop_restart_spinner()
                self._force_quit = True
                self.tray.hide()
                QApplication.instance().quit()
            elif self._restart_after_stop:
                self._restart_after_stop = False
                self.statusBar().showMessage(self._texts()["restarting"])
                QTimer.singleShot(0, lambda: self._start_all(restarting=True))
            else:
                self._stop_restart_spinner()
                self.statusBar().showMessage(self._texts()["stopped"])

        worker.finished_ok.connect(on_done)
        worker.start()

    def _toggle_pet_btn(self) -> None:
        self.services.toggle_pet()
        self._refresh_status()

    def _refresh_status(self) -> None:
        # Sync pet_hidden from control file if electron wrote back
        ctrl = read_pet_control()
        ctrl_is_current = self.services.accepts_pet_control(ctrl)
        if ctrl_is_current and ctrl.get("state") == "hidden":
            self.services.pet_hidden = True
        elif ctrl_is_current and ctrl.get("state") == "visible":
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
            ctrl_is_current
            and ctrl.get("action") == "pet_closed"
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

        texts = self._texts()
        self.status_label.setText(self.services.status_text(self._language()))
        starting = bool(self._start_worker and self._start_worker.isRunning())
        env_busy = bool(self._env_worker and self._env_worker.isRunning())
        stopping = bool(self._stop_worker and self._stop_worker.isRunning())
        busy = starting or env_busy or stopping
        running = self.services.any_running()
        self.btn_start.setEnabled(not running and not busy)
        self.btn_stop.setEnabled((running or starting) and not env_busy and not stopping)
        self.btn_restart.setEnabled(running and not busy)
        pet_on = self.services.electron_running()
        self.btn_toggle_pet.setEnabled(pet_on and not busy)
        if pet_on:
            toggle_text = texts["show_pet"] if self.services.pet_hidden else texts["hide_pet"]
            self.btn_toggle_pet.setText(toggle_text)
            self.act_toggle_pet.setText(toggle_text)
            self.act_toggle_pet.setEnabled(True)
        else:
            self.btn_toggle_pet.setText(texts["hide_pet"])
            self.act_toggle_pet.setText(texts["hide_pet"])
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

        texts = self._texts()
        box = QMessageBox(self)
        box.setWindowTitle(texts["close_title"])
        box.setText(texts["close_question"])
        box.setInformativeText(texts["close_info"])
        btn_tray = box.addButton(texts["close_tray"], QMessageBox.ButtonRole.AcceptRole)
        btn_exit = box.addButton(texts["close_exit"], QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(texts["cancel"], QMessageBox.ButtonRole.RejectRole)
        remember = AnimatedCheckBox(texts["remember"])
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
        texts = self._texts()
        self.tray.showMessage(
            texts["app_title"],
            texts["tray_notice"],
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )
        self.statusBar().showMessage(texts["tray_status"])
