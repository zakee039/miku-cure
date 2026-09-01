#!/usr/bin/env python3
"""Run PyInstaller with a deterministic Windows DLL search path.

Qt 6 on Windows resolves ``icuuc.dll`` from the operating system.  Developer
toolchains sometimes prepend another ICU build to PATH (for example Poppler's
version-suffixed ICU DLLs).  PyInstaller can mistake that DLL for Qt's runtime
dependency and bundle it, producing an executable that fails while importing
``PySide6.QtCore``.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable


FORBIDDEN_DLLS = {"icuuc.dll"}


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def sanitize_build_path(
    path_value: str,
    *,
    system_root: str | None = None,
) -> tuple[str, list[str]]:
    """Remove non-system PATH entries that can shadow Windows ICU."""
    windows_root = Path(system_root or os.environ.get("SystemRoot", r"C:\Windows"))
    system32 = _normalized_path(windows_root / "System32")
    kept: list[str] = []
    removed: list[str] = []

    for raw_entry in path_value.split(os.pathsep):
        entry = raw_entry.strip().strip('"')
        if not entry:
            kept.append(raw_entry)
            continue

        expanded = Path(os.path.expandvars(entry))
        has_foreign_icu = any((expanded / name).is_file() for name in FORBIDDEN_DLLS)
        if has_foreign_icu and _normalized_path(expanded) != system32:
            removed.append(raw_entry)
            continue
        kept.append(raw_entry)

    return os.pathsep.join(kept), removed


def _argument_value(arguments: list[str], option: str) -> str | None:
    try:
        index = arguments.index(option)
    except ValueError:
        return None
    return arguments[index + 1] if index + 1 < len(arguments) else None


def _forbidden_archive_entries(executable: Path) -> list[str]:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    return sorted(
        name
        for name in archive.toc
        if Path(name).name.casefold() in FORBIDDEN_DLLS
    )


def _built_onefile(arguments: list[str]) -> Path | None:
    if "--onefile" not in arguments:
        return None
    dist = _argument_value(arguments, "--distpath")
    name = _argument_value(arguments, "--name")
    if not dist or not name:
        return None
    suffix = ".exe" if os.name == "nt" else ""
    return Path(dist) / f"{name}{suffix}"


def run_pyinstaller(arguments: Iterable[str]) -> int:
    args = list(arguments)
    env = os.environ.copy()
    env["PATH"], removed = sanitize_build_path(env.get("PATH", ""))
    for entry in removed:
        print(f"Build isolation: removed foreign ICU directory from PATH: {entry}")

    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", *args],
        env=env,
        check=False,
    )
    if result.returncode:
        return result.returncode

    executable = _built_onefile(args)
    if executable and executable.is_file():
        forbidden = _forbidden_archive_entries(executable)
        if forbidden:
            print(
                "ERROR: Launcher archive contains a foreign ICU runtime: "
                + ", ".join(forbidden),
                file=sys.stderr,
            )
            return 2
    return 0


def main() -> int:
    return run_pyinstaller(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
