@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "VENV=%BACKEND%\.venv"
set "TRAIN=%ROOT%train"

echo.
echo  +==========================================+
echo  ^|   Miku Cure - Training Web UI Launcher   ^|
echo  +==========================================+
echo.

if not exist "%VENV%\Scripts\python.exe" (
    echo  [!] ERROR: Python virtual environment not found.
    echo      Please run install.bat first to set up the environment.
    pause
    exit /b 1
)

echo [*] Starting Training Web UI backend...
start "Miku Cure Training WebUI" "%VENV%\Scripts\python.exe" "%TRAIN%\webui.py"

echo [*] Waiting for the server to initialize...
timeout /t 3 /nobreak >nul

echo [*] Opening browser...
start http://localhost:8000

echo.
echo [*] The Training Web UI is now running in your browser.
echo [*] You can close this window. The backend will continue running in the new console window.
echo.
pause
