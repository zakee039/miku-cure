@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/4] Installing launcher deps...
python -m pip install -r requirements.txt pyinstaller pillow -q

echo [2/4] Generating icon.ico from miku\icon.png ...
python make_icon.py
if errorlevel 1 (
  echo WARNING: icon generation failed, building without custom icon
  set "ICON_ARGS="
) else (
  set "ICON_ARGS=--icon icon.ico"
)

echo [3/4] Building MikuCure-Launcher.exe ...
python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "MikuCure-Launcher" ^
  %ICON_ARGS% ^
  --add-data "..\miku\icon.png;miku" ^
  --distpath ".." ^
  main.py

if errorlevel 1 (
  echo BUILD FAILED
  pause
  exit /b 1
)

echo [4/4] Done: ..\MikuCure-Launcher.exe
echo Keep the exe inside the project root (or portable package root).
pause
