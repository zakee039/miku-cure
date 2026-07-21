"""主窗口：控制台 + 托盘守护 + 隐藏/显示桌宠。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
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

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        nav = QListWidget()
        nav.setObjectName("nav")
        nav.setFixedWidth(176)
        for name in ("控制台", "环境检查", "关于"):
            QListWidgetItem(name, nav)
        nav.setCurrentRow(0)
        root.addWidget(nav)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.page_dash = self._build_dashboard()
        self.page_env = self._build_env_page()
        self.page_about = self._build_about()
        self.stack.addWidget(self.page_dash)
        self.stack.addWidget(self.page_env)
        self.stack.addWidget(self.page_about)
        nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.logbus.line.connect(self._on_log)
        self.statusBar().showMessage(deploy_mode_label())

        self._setup_tray()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(600)
        self._refresh_status()
        QTimer.singleShot(200, self.refresh_env)

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
        act_exit = QAction("退出（停止全部服务）", self)
        act_exit.triggered.connect(self._tray_exit)
        menu.addAction(act_exit)

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
        self.services.stop_all()
        self._force_quit = True
        self.tray.hide()
        QApplication.instance().quit()

    def _build_dashboard(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)

        head = QLabel("控制台")
        head.setObjectName("h1")
        sub = QLabel(deploy_mode_detail())
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        lay.addWidget(head)
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

        tip = QLabel(
            "启动器是守护精灵：关闭窗口将最小化到托盘；右键托盘可隐藏/显示桌宠或完全退出。"
        )
        tip.setObjectName("sub")
        tip.setWordWrap(True)
        lay.addWidget(tip)

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
        head = QLabel("环境检查")
        head.setObjectName("h1")
        lay.addWidget(head)
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
        self.services.stop_all()
        self._linked_stop_done = False
        self._refresh_status()

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

        # Pet process exited (user closed window) → stop backend via our PID handle (no PowerShell)
        if self.services.electron_proc is not None and self.services.electron_proc.poll() is not None:
            if not self._linked_stop_done:
                self._linked_stop_done = True
                self.services.log("system", "检测到桌宠已退出，正在停止后端…")
                self.services.stop_backend_only()
                self.services.electron_proc = None
                self.services.pet_hidden = False
                self.services.log("system", "服务已全部停止")
                self.statusBar().showMessage("桌宠已关闭，后端已停止")
        elif ctrl.get("action") == "pet_closed" and not self._linked_stop_done and self.services.backend_running():
            # Electron external-backend mode signals pet closed without killing backend itself
            self._linked_stop_done = True
            self.services.log("system", "桌宠发来关闭信号，停止后端…")
            self.services.stop_backend_only()
            if self.services.electron_proc and self.services.electron_proc.poll() is not None:
                self.services.electron_proc = None
            self.services.pet_hidden = False

        if self.services.backend_proc is not None and self.services.backend_proc.poll() is not None:
            self.services.backend_proc = None

        self.status_label.setText(self.services.status_text())
        busy = bool(
            (self._start_worker and self._start_worker.isRunning())
            or (self._env_worker and self._env_worker.isRunning())
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
        # 关闭窗口 = 最小化到托盘（守护精灵不退出）
        event.ignore()
        self.hide()
        self.tray.showMessage(
            APP_NAME,
            "已最小化到托盘。右键托盘图标可退出或控制桌宠。",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )
        self.statusBar().showMessage("已最小化到托盘")
