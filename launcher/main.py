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

from core.envcheck import EnvCheckCancelled, run_env_check
from core.i18n import environment_summary, get_texts, translate_progress
from core.jsonio import read_json
from core.paths import IS_PORTABLE, PROJECT_ROOT, USER_DIR
from core.single_instance import SingleInstance
from ui.splash import SplashWindow
from ui.theme import QSS, app_icon


class BootstrapWorker(QThread):
    progress = Signal(str, int)
    failed = Signal(str)
    finished_ok = Signal(object)

    def __init__(self, language: str) -> None:
        super().__init__()
        self._language = language

    def run(self) -> None:
        try:
            texts = get_texts(self._language)
            mode = texts["mode_portable"] if IS_PORTABLE else texts["mode_dev"]
            self.progress.emit(texts["splash_identify"], 12)
            self.progress.emit(texts["splash_mode"].format(mode=mode), 22)

            def _cb(message: str, percent: int) -> None:
                # Map envcheck 0–100 into splash 25–92
                mapped = 25 + int(percent * 0.67)
                self.progress.emit(
                    translate_progress(self._language, message),
                    mapped,
                )

            self.progress.emit(texts["splash_checking"], 28)
            report = run_env_check(
                progress=_cb,
                cancelled=self.isInterruptionRequested,
            )
            self.progress.emit(environment_summary(self._language, report), 95)
            self.finished_ok.emit(report)
        except EnvCheckCancelled:
            return
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{exc}\n{traceback.format_exc()}")


def main() -> int:
    config = read_json(USER_DIR / "config.json", {})
    language = config.get("miku-language", "zh") if isinstance(config, dict) else "zh"
    texts = get_texts(language)
    # Windows 任务栏图标分组 / 显示自定义图标
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                "MikuCure.Launcher.1.2.2"
            )
        except Exception:
            pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(texts["app_title"])
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
            texts["app_title"],
            texts["single_instance"],
        )
        return 0

    splash = SplashWindow()
    if not icon.isNull():
        splash.setWindowIcon(icon)
    mode = texts["mode_portable"] if IS_PORTABLE else texts["mode_dev"]
    mode_detail = texts[
        "mode_detail_portable" if IS_PORTABLE else "mode_detail_dev"
    ].format(root=PROJECT_ROOT)
    splash.set_mode(mode, mode_detail)
    splash.set_step(texts["splash_starting"], 5)
    splash.show()
    app.processEvents()

    worker = BootstrapWorker(language)
    state: dict = {}

    def on_progress(message: str, percent: int) -> None:
        splash.set_step(message, percent)

    def on_failed(err: str) -> None:
        state["error"] = err
        splash.set_step(texts["splash_check_failed"], 88)
        _open_main()

    def on_ok(report) -> None:
        state["report"] = report
        splash.set_step(texts["splash_ready"], 95)
        _open_main()

    def _open_main() -> None:
        from ui.main_window import MainWindow

        app.processEvents()
        report = state.get("report")
        try:
            # The splash already paid for the environment check. Supplying its
            # report avoids immediately running the same expensive imports a
            # second time while preserving MainWindow's auto-start timer.
            window = MainWindow(initial_env_report=report)
        except Exception as exc:  # noqa: BLE001
            splash.close()
            QMessageBox.critical(
                None,
                texts["app_title"],
                texts["main_load_error"].format(
                    error=exc,
                    trace=traceback.format_exc()[-800:],
                ),
            )
            app.quit()
            return

        if report is None and state.get("error"):
            window.statusBar().showMessage(texts["check_error"])

        splash.close()
        window.show()
        app._miku_window = window  # type: ignore[attr-defined]
        app._miku_instance = instance  # type: ignore[attr-defined]
        app.aboutToQuit.connect(window.shutdown_workers)

    worker.progress.connect(on_progress)
    worker.failed.connect(on_failed)
    worker.finished_ok.connect(on_ok)
    worker.start()

    def stop_bootstrap_worker() -> None:
        if worker.isRunning():
            worker.requestInterruption()

    app.aboutToQuit.connect(stop_bootstrap_worker)
    try:
        return app.exec()
    finally:
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(2500)
        instance.release()


if __name__ == "__main__":
    raise SystemExit(main())
