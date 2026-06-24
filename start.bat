@echo off
chcp 65001 >nul
setlocal

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   Miku Cure - 启动  v0.1.0               ║
echo  ╚══════════════════════════════════════════╝
echo.

set "ROOT=%~dp0"
set "FRONTEND=%ROOT%frontend"
set "VENV=%ROOT%backend\.venv"

:: ── 检查安装是否完成 ──────────────────────────
if not exist "%VENV%\Scripts\python.exe" (
    echo  ✗ 未检测到虚拟环境，请先运行 install.bat
    pause
    exit /b 1
)

if not exist "%FRONTEND%\node_modules\electron" (
    echo  ✗ 未检测到 Electron，请先运行 install.bat
    pause
    exit /b 1
)

:: ── 检查 .env ────────────────────────────────
if not exist "%ROOT%.env" (
    echo  ⚠  未检测到 .env，DeepSeek API 将不可用，使用本地语录兜底
    echo.
)

:: ── 启动 Electron（内含后端自启动逻辑）─────────
echo  ✓ 启动 Miku Cure...
echo  （后端将由 Electron 自动管理，关闭窗口即可完全退出）
echo.

cd /d "%FRONTEND%"
call npm start

:: 脚本运行到这里说明 Electron 已退出
echo.
echo  Miku Cure 已退出，再见！
timeout /t 2 >nul
