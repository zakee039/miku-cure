@echo off
setlocal

echo.
echo  +==========================================+
echo  ^|   Miku Cure - Install Script  v1.0.1    ^|
echo  +==========================================+
echo.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "VENV=%BACKEND%\.venv"

:: -- Check Python --
echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Please install Python 3.10+ and add it to PATH.
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

:: Check for local torch .whl package
set "TORCH_WHL="
for %%f in ("%ROOT%torch-*.whl") do set "TORCH_WHL=%%f"

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

if not exist "%ROOT%.env" (
    echo  WARNING: .env file not found.
    echo  Create .env in the project root and add:
    echo    DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
    echo.
)

pause
