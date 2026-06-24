@echo off
setlocal

echo.
echo  +==========================================+
echo  ^|   Miku Cure - Start  v0.1.0              ^|
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

:: -- Warn if .env is missing --
if not exist "%ROOT%.env" (
    echo  WARNING: .env file not found.
    echo  DeepSeek API will be unavailable; local fallback phrases will be used.
    echo.
)

:: -- Launch --
echo  Starting Miku Cure...
echo  The backend is managed automatically by Electron.
echo  Close the desktop pet window to fully exit.
echo.

cd /d "%FRONTEND%"
call npm start

echo.
echo  Miku Cure has exited. Goodbye!
timeout /t 2 >nul
