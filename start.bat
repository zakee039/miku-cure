@echo off
setlocal

echo.
echo  ========================================
echo  ^|                                      ^|
echo  ^|   Miku Cure - Start  v1.1.2              ^|
echo  +==========================================+
echo.

set "ROOT=%~dp0"
set "FRONTEND=%ROOT%frontend"
set "VENV=%ROOT%backend\.venv"

:: -- Check installation --
if not exist "%VENV%\Scripts\python.exe" (
    echo  ERROR: Virtual environment not found.
    echo  Please run install.bat first.
    pause
    exit /b 1
)

if not exist "%FRONTEND%\node_modules\electron" (
    echo  ERROR: Electron not found.
    echo  Please run install.bat first.
    pause
    exit /b 1
)

:: -- Prefer desktop launcher if present --
if exist "%ROOT%MikuCure-Launcher.exe" (
    echo  Starting MikuCure-Launcher.exe ...
    echo  Use the launcher to start/stop backend and desktop pet.
    echo.
    start "" "%ROOT%MikuCure-Launcher.exe"
    exit /b 0
)

if exist "%ROOT%launcher\main.py" (
    echo  Starting launcher from source...
    cd /d "%ROOT%launcher"
    where python >nul 2>&1 && (
        start "" python main.py
        exit /b 0
    )
)

:: -- Fallback: Electron manages backend --
echo  Starting Miku Cure via Electron...
echo  The backend is managed automatically by Electron.
echo  Close the desktop pet window to fully exit.
echo  Configure LLM APIs in Settings if chat is needed.
echo.
echo  Tip: run launcher\build.bat then use MikuCure-Launcher.exe for service control.
echo.

cd /d "%FRONTEND%"
call npm start

echo.
echo  Miku Cure has exited. Goodbye!
timeout /t 2 >nul
