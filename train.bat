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

echo [*] Opening browser...
start /b cmd /c "timeout /t 3 >nul & start http://localhost:8000"

echo [*] Starting Training Web UI backend (Port 8000)...
echo [*] DO NOT close this window. Closing it will shut down the server.
echo.

call "%VENV%\Scripts\activate.bat"
cd /d "%TRAIN%"
uvicorn webui:app --host 0.0.0.0 --port 8000

echo.
pause
