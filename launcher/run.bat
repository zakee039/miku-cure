@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=%~dp0..\backend\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo ERROR: Project virtual environment is missing. Run ..\install.bat first.
    exit /b 1
)
"%PYTHON%" -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo ERROR: PySide6 is missing. Run ..\install.bat first.
    exit /b 1
)
"%PYTHON%" main.py
exit /b %errorlevel%
