@echo off
setlocal EnableExtensions
chcp 65001 >nul

echo.
echo  ==========================================
echo  ^|   Miku Cure - Install Script v1.2.2   ^|
echo  ==========================================
echo.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "VENV=%BACKEND%\.venv"
set "PYTHONUTF8=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
if defined MIKU_DOWNLOAD_PROXY (
    set "HTTP_PROXY=%MIKU_DOWNLOAD_PROXY%"
    set "HTTPS_PROXY=%MIKU_DOWNLOAD_PROXY%"
    set "ELECTRON_GET_USE_PROXY=1"
    set "GLOBAL_AGENT_HTTP_PROXY=%MIKU_DOWNLOAD_PROXY%"
    set "GLOBAL_AGENT_HTTPS_PROXY=%MIKU_DOWNLOAD_PROXY%"
    if not defined ELECTRON_MIRROR set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
    echo  Using download proxy: %MIKU_DOWNLOAD_PROXY%
)

echo [1/5] Checking Python 3.13.12 (64-bit)...
python -c "import struct,sys; raise SystemExit(0 if sys.version_info[:3]==(3,13,12) and struct.calcsize('P')==8 else 1)" >nul 2>&1
if errorlevel 1 (
    echo  ERROR: 64-bit Python 3.13.12 is required so portable native extensions match the embedded runtime.
    python --version 2>nul
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   OK: %%v (64-bit)

echo [2/5] Checking Node.js...
node -e "const [a,b]=process.versions.node.split('.').map(Number);process.exit((a===22&&b>=12)||a>22?0:1)" >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Node.js 22.12 or newer is required by Electron 43.
    node --version 2>nul
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo   OK: Node.js %%v

echo.
echo [3/5] Installing locked Python runtime and launcher dependencies...
if not exist "%VENV%\Scripts\python.exe" (
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo  ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)
"%VENV%\Scripts\python.exe" -c "import struct,sys; raise SystemExit(0 if sys.version_info[:3]==(3,13,12) and struct.calcsize('P')==8 else 1)" >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Existing backend\.venv was created by a different Python runtime.
    echo         Remove backend\.venv and rerun install.bat with 64-bit Python 3.13.12.
    pause
    exit /b 1
)

"%VENV%\Scripts\python.exe" -m pip install --upgrade "pip==26.1.2" "setuptools==81.0.0"
if errorlevel 1 (
    echo  ERROR: Failed to install the locked packaging toolchain.
    pause
    exit /b 1
)

set "TORCH_WHL="
set "TORCHVISION_WHL="
for %%f in ("%ROOT%torch-2.12.1+cpu*.whl" "%ROOT%??????\torch-2.12.1+cpu*.whl") do if exist "%%~ff" if not defined TORCH_WHL set "TORCH_WHL=%%~ff"
for %%f in ("%ROOT%torchvision-0.27.1+cpu*.whl" "%ROOT%??????\torchvision-0.27.1+cpu*.whl") do if exist "%%~ff" if not defined TORCHVISION_WHL set "TORCHVISION_WHL=%%~ff"

if defined TORCH_WHL (
    echo   Installing local CPU PyTorch wheel...
    "%VENV%\Scripts\python.exe" -m pip install "%TORCH_WHL%"
    if errorlevel 1 goto :torch_failed
    if defined TORCHVISION_WHL (
        "%VENV%\Scripts\python.exe" -m pip install "%TORCHVISION_WHL%"
    ) else (
        "%VENV%\Scripts\python.exe" -m pip install "torchvision==0.27.1+cpu" --index-url https://download.pytorch.org/whl/cpu
    )
    if errorlevel 1 goto :torch_failed
) else (
    echo   Installing locked CPU-only PyTorch...
    "%VENV%\Scripts\python.exe" -m pip install "torch==2.12.1+cpu" "torchvision==0.27.1+cpu" --index-url https://download.pytorch.org/whl/cpu
    if errorlevel 1 goto :torch_failed
)

echo   Removing conflicting OpenCV distributions before the locked install...
"%VENV%\Scripts\python.exe" -m pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python opencv-contrib-python-headless torchaudio >nul
if errorlevel 1 (
    echo  ERROR: Failed to remove conflicting OpenCV distributions.
    pause
    exit /b 1
)

"%VENV%\Scripts\python.exe" -m pip install -r "%BACKEND%\requirements.txt" -r "%ROOT%launcher\requirements.txt"
if errorlevel 1 (
    echo  ERROR: Failed to install locked application dependencies.
    pause
    exit /b 1
)

"%VENV%\Scripts\python.exe" -c "import struct; from importlib.metadata import distributions,version; import cv2,mediapipe,numpy,openai,PIL,torch,torchvision,websockets; import PySide6,PyInstaller; installed={d.metadata['Name'].lower() for d in distributions()}; assert struct.calcsize('P')==8; assert torch.version.cuda is None and not torch.cuda.is_available(); assert version('torch')=='2.12.1+cpu' and version('torchvision')=='0.27.1+cpu'; assert version('opencv-contrib-python')=='4.13.0.92'; assert not installed.intersection({'opencv-python','opencv-python-headless','opencv-contrib-python-headless'}); assert tuple(map(int,PIL.__version__.split('.')[:2])) >= (12,3); print('  Runtime verified:',torch.__version__,'CPU, MediaPipe',mediapipe.__version__)"
if errorlevel 1 (
    echo  ERROR: Dependency verification failed or a CUDA PyTorch build was installed.
    pause
    exit /b 1
)
"%VENV%\Scripts\python.exe" -m pip check
if errorlevel 1 (
    echo  ERROR: Installed Python distributions have incompatible requirements.
    pause
    exit /b 1
)
echo   OK: Python runtime and source launcher are ready.

echo.
echo [4/5] Installing locked Electron dependencies...
cd /d "%FRONTEND%"
call npm.cmd ci --prefer-offline --no-audit
if errorlevel 1 (
    echo  ERROR: npm ci failed. package.json and package-lock.json must agree.
    pause
    exit /b 1
)
node "%FRONTEND%\node_modules\electron\install.js"
if errorlevel 1 (
    echo  ERROR: Electron binary download or checksum verification failed.
    pause
    exit /b 1
)
if not exist "%FRONTEND%\node_modules\electron\dist\electron.exe" (
    echo  ERROR: Electron binary is missing after npm ci.
    pause
    exit /b 1
)
echo   OK: Electron installed from package-lock.json.

echo.
echo [5/5] Optional training environment...
if /i not "%MIKU_INSTALL_TRAINING%"=="1" (
    echo   Skipped. Set MIKU_INSTALL_TRAINING=1 to install and build training tools.
    goto :install_done
)

"%VENV%\Scripts\python.exe" -m pip install "pandas==3.0.3" "matplotlib==3.11.0" "scikit-learn==1.9.0" "fastapi==0.138.0" "uvicorn==0.49.0" "psutil==7.2.2"
if errorlevel 1 (
    echo  ERROR: Failed to install optional training dependencies.
    pause
    exit /b 1
)
cd /d "%ROOT%train\frontend"
call npm.cmd ci --prefer-offline --no-audit
if errorlevel 1 (
    echo  ERROR: npm ci failed for Train WebUI.
    pause
    exit /b 1
)
call npm.cmd run build
if errorlevel 1 (
    echo  ERROR: Train WebUI build failed.
    pause
    exit /b 1
)
echo   OK: Optional training environment is ready.

:install_done
echo.
echo  Installation complete. Run start.bat to launch Miku Cure.
echo.
pause
exit /b 0

:torch_failed
echo  ERROR: CPU PyTorch installation failed.
pause
exit /b 1
