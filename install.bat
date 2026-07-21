@echo off
setlocal

echo.
echo  ========================================
echo  ^|                                      ^|
echo  ^|   Miku Cure - Install Script  v1.1.0    ^|
echo  +==========================================+
echo.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "VENV=%BACKEND%\.venv"

:: -- Check Python (3.10 – 3.13) --
echo [1/5] Checking Python...
python -c "import sys; v=sys.version_info[:2]; sys.exit(0 if v>=(3,10) and v<=(3,13) else 1)" >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python 3.10 – 3.13 is required for compatibility!
    echo  Current version:
    python --version
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   OK: %%v

:: -- Check Node.js --
echo [2/5] Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Node.js not found. Please install Node.js 18+ and add it to PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo   OK: Node.js %%v

:: -- Python virtual environment and dependencies --
echo.
echo [3/5] Installing Python dependencies...
if not exist "%VENV%\Scripts\python.exe" (
    echo   Creating virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo  ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo   Upgrading pip...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip -q

:: Check for local torch .whl package (root or 开发/)
set "TORCH_WHL="
for %%f in ("%ROOT%torch-*.whl") do set "TORCH_WHL=%%f"
if not defined TORCH_WHL (
    for %%f in ("%ROOT%开发\torch-*.whl") do set "TORCH_WHL=%%f"
)

if defined TORCH_WHL (
    echo   Found local PyTorch package, installing from file...
    "%VENV%\Scripts\pip.exe" install "%TORCH_WHL%" -q
) else (
    echo   Installing CPU-only PyTorch from PyPI...
    echo   (For GPU support, install the appropriate CUDA build manually.)
    "%VENV%\Scripts\pip.exe" install torch torchvision --index-url https://download.pytorch.org/whl/cpu -q
)

echo   Installing remaining Python dependencies...
"%VENV%\Scripts\pip.exe" install -r "%BACKEND%\requirements.txt" -q
if errorlevel 1 (
    echo  ERROR: Failed to install Python dependencies. Check requirements.txt.
    pause
    exit /b 1
)

:: Verify critical imports (MediaPipe Tasks face stack)
echo   Verifying MediaPipe...
"%VENV%\Scripts\python.exe" -c "import mediapipe as mp; from mediapipe.tasks.python import vision; assert hasattr(vision,'FaceDetector'); print('  MediaPipe', getattr(mp,'__version__','?'), 'Tasks OK')"
if errorlevel 1 (
    echo  WARNING: MediaPipe Tasks import failed. Face detection will use Haar fallback.
    echo  Try: "%VENV%\Scripts\pip.exe" install --force-reinstall "mediapipe>=0.10.14,<0.11"
) else (
    echo   OK: MediaPipe verified.
)

echo   OK: Python dependencies installed.

:: -- Node.js dependencies --
echo.
echo [4/5] Installing Node.js dependencies (Electron)...
cd /d "%FRONTEND%"
call npm install --prefer-offline
if errorlevel 1 (
    echo  ERROR: npm install failed.
    pause
    exit /b 1
)
echo   OK: Node.js dependencies installed.

:: -- Train WebUI dependencies --
echo.
echo [5/5] Installing Node.js dependencies (Train WebUI)...
cd /d "%ROOT%train\frontend"
call npm install --prefer-offline
if errorlevel 1 (
    echo  ERROR: npm install failed for Train WebUI.
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo  ERROR: npm run build failed for Train WebUI.
    pause
    exit /b 1
)
echo   OK: Train WebUI built successfully.

:: -- Done --
echo.
echo  +==========================================+
echo  ^|   Installation complete!                 ^|
echo  ^|   Run start.bat to launch the app.       ^|
echo  +==========================================+
echo.

echo  TIP: Configure LLM APIs in the Settings panel (keys are encrypted at rest).
echo  TIP: Smoke test: backend\.venv\Scripts\python.exe backend\test_smoke_e2e.py
echo  TIP: Live camera:  backend\.venv\Scripts\python.exe backend\test_smoke_e2e.py --live
echo.

pause
