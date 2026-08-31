@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "ROOT=%~dp0"
set "FRONTEND=%ROOT%frontend"
set "VENV=%ROOT%backend\.venv"
set "PYTHONUTF8=1"

echo.
echo  ==========================================
echo  ^|       Miku Cure - Start v1.2.1        ^|
echo  ==========================================
echo.

rem This source-tree entry point must prefer current launcher source. Otherwise
rem a stale root EXE can control newer backend/Electron protocol code.
if exist "%VENV%\Scripts\pythonw.exe" if exist "%ROOT%launcher\main.py" (
    if not exist "%FRONTEND%\node_modules\electron\dist\electron.exe" (
        echo  ERROR: Electron is not installed. Run install.bat first.
        pause
        exit /b 1
    )
    echo  Starting source launcher from the project virtual environment...
    start "" "%VENV%\Scripts\pythonw.exe" "%ROOT%launcher\main.py"
    if errorlevel 1 (
        echo  ERROR: Failed to start the source launcher.
        pause
        exit /b 1
    )
    exit /b 0
)

rem Fallback for a deliberately launcher-only tree.
if exist "%ROOT%MikuCure-Launcher.exe" (
    echo  Source launcher unavailable; starting packaged launcher...
    start "" "%ROOT%MikuCure-Launcher.exe"
    exit /b 0
)

echo  ERROR: Launcher source/runtime is incomplete. Run install.bat first.
pause
exit /b 1
