@echo off
chcp 65001 >nul
setlocal

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   Miku Cure - 一键安装脚本  v0.1.0       ║
echo  ╚══════════════════════════════════════════╝
echo.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "VENV=%BACKEND%\.venv"

:: ── 检查 Python ───────────────────────────────
echo [1/4] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo  ✗ 未检测到 Python，请先安装 Python 3.10+ 并添加到 PATH
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  ✓ %%v

:: ── 检查 Node.js ──────────────────────────────
echo [2/4] 检查 Node.js 环境...
node --version >nul 2>&1
if errorlevel 1 (
    echo  ✗ 未检测到 Node.js，请先安装 Node.js 18+ 并添加到 PATH
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo  ✓ Node.js %%v

:: ── Python 虚拟环境与依赖 ─────────────────────
echo.
echo [3/4] 安装 Python 依赖（虚拟环境）...
if not exist "%VENV%\Scripts\python.exe" (
    echo  → 创建虚拟环境...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo  ✗ 虚拟环境创建失败
        pause
        exit /b 1
    )
)

echo  → 升级 pip...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip -q

:: 检查是否存在本地 torch whl 包
set "TORCH_WHL="
for %%f in ("%ROOT%torch-*.whl") do set "TORCH_WHL=%%f"

if defined TORCH_WHL (
    echo  → 检测到本地 PyTorch 安装包，从本地安装...
    "%VENV%\Scripts\pip.exe" install "%TORCH_WHL%" -q
) else (
    echo  → 从 PyPI 安装 CPU 版 PyTorch（如需 GPU 版请手动安装）...
    "%VENV%\Scripts\pip.exe" install torch torchvision --index-url https://download.pytorch.org/whl/cpu -q
)

echo  → 安装其余依赖...
"%VENV%\Scripts\pip.exe" install -r "%BACKEND%\requirements.txt" -q
if errorlevel 1 (
    echo  ✗ Python 依赖安装失败，请检查 requirements.txt
    pause
    exit /b 1
)
echo  ✓ Python 依赖安装完成

:: ── Node.js 依赖 ──────────────────────────────
echo.
echo [4/4] 安装 Node.js 依赖（Electron）...
cd /d "%FRONTEND%"
call npm install --prefer-offline
if errorlevel 1 (
    echo  ✗ npm install 失败
    pause
    exit /b 1
)
echo  ✓ Node.js 依赖安装完成

:: ── 完成 ──────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   ✓ 安装完成！运行 start.bat 启动应用    ║
echo  ╚══════════════════════════════════════════╝
echo.

:: 检查 .env 文件
if not exist "%ROOT%.env" (
    echo  ⚠  提示：未检测到 .env 文件
    echo     请在项目根目录创建 .env 并填入：
    echo     DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
    echo.
)

pause
