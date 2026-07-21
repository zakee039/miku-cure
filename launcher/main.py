#!/usr/bin/env python3
"""Miku Cure 桌面启动器。

参考 RAG-PRO「RAG智能体」：
1. 启动进度窗
2. 识别源码 / 便携模式
3. 环境自检
4. 一键托管后端 + Electron 桌宠

运行：python main.py
打包：build.bat → 项目根 MikuCure-Launcher.exe
"""
from __future__ import annotations

import sys
import traceback

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from core.paths import APP_NAME, deploy_mode_detail, deploy_mode_label
from core.single_instance import SingleInstance
from ui.splash import SplashWindow
from ui.theme import QSS, app_icon


class BootstrapWorker(QThread):
    progress = Signal(str, int)
    failed = Signal(str)
    finished_ok = Signal(object)

    def run(self) -> None:
        try:
            from core.envcheck import run_env_check

            self.progress.emit("识别部署模式…", 12)
            self.progress.emit(f"模式：{deploy_mode_label()}", 22)

            def _cb(message: str, percent: int) -> None:
                # Map envcheck 0–100 into splash 25–92
                mapped = 25 + int(percent * 0.67)
                self.progress.emit(message, mapped)

            self.progress.emit("环境检查中…", 28)
            report = run_env_check(progress=_cb)
            self.progress.emit(report.summary_line(), 95)
            self.finished_ok.emit(report)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{exc}\n{traceback.format_exc()}")


def main() -> int:
    # Windows 任务栏图标分组 / 显示自定义图标
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                "MikuCure.Launcher.1.1.0"
            )
        except Exception:
            pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Tray guardian: hiding the main window must NOT quit the process
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(QSS)
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)


    instance = SingleInstance()
    if not instance.acquire():
        QMessageBox.warning(
            None,
            APP_NAME,
            "启动器已在运行中。\n请关闭已有实例后再试。",
        )
        return 0

    splash = SplashWindow()
    if not icon.isNull():
        splash.setWindowIcon(icon)
    splash.set_mode(deploy_mode_label(), deploy_mode_detail())
    splash.set_step("正在启动，请稍候…", 5)
    splash.show()
    app.processEvents()

    worker = BootstrapWorker()
    state: dict = {}

    def on_progress(message: str, percent: int) -> None:
        splash.set_step(message, percent)

    def on_failed(err: str) -> None:
        state["error"] = err
        splash.set_step("检测异常，继续加载主界面…", 88)
        _open_main()

    def on_ok(report) -> None:
        state["report"] = report
        splash.set_step("环境就绪，加载主界面…", 95)
        _open_main()

    def _open_main() -> None:
        from ui.main_window import MainWindow

        app.processEvents()
        try:
            window = MainWindow()
        except Exception as exc:  # noqa: BLE001
            splash.close()
            QMessageBox.critical(
                None,
                APP_NAME,
                f"主界面加载失败：\n{exc}\n\n{traceback.format_exc()[-800:]}",
            )
            app.quit()
            return

        report = state.get("report")
        if report is not None:
            window.statusBar().showMessage(report.summary_line())
            window.refresh_env()
        elif state.get("error"):
            window.statusBar().showMessage("启动检测异常，请打开「环境检查」")

        splash.close()
        window.show()
        app._miku_window = window  # type: ignore[attr-defined]
        app._miku_instance = instance  # type: ignore[attr-defined]

    worker.progress.connect(on_progress)
    worker.failed.connect(on_failed)
    worker.finished_ok.connect(on_ok)
    worker.start()

    code = app.exec()
    instance.release()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
