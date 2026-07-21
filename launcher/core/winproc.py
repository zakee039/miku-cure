"""Windows 子进程：强制隐藏控制台窗口。"""
from __future__ import annotations

import os
import subprocess
from typing import Any


def hidden_run_kwargs() -> dict[str, Any]:
    """kwargs for subprocess.run / Popen to avoid black CMD flashes on Windows."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
    }
    if os.name != "nt":
        return kwargs

    # 0x08000000 — do not create a console window
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    kwargs["creationflags"] = create_no_window

    # Extra belt: STARTUPINFO hide
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si
    except Exception:
        pass
    return kwargs


def run_hidden(cmd: list[str], **extra) -> subprocess.CompletedProcess:
    kw = hidden_run_kwargs()
    kw.update(extra)
    return subprocess.run(cmd, **kw)


def popen_hidden(cmd: list[str], **extra) -> subprocess.Popen:
    kw = hidden_run_kwargs()
    kw.update(extra)
    return subprocess.Popen(cmd, **kw)
