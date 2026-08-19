@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\backend\.venv\Scripts\python.exe"
set "DIST=%~dp0dist\build-%RANDOM%-%RANDOM%"
set "WORK=%~dp0build\build-%RANDOM%-%RANDOM%"

if not exist "%PYTHON%" (
    echo ERROR: Project virtual environment is missing. Run ..\install.bat first.
    exit /b 1
)

echo [1/4] Validating locked launcher dependencies...
"%PYTHON%" -c "from importlib.metadata import version; import PIL,PyInstaller,PySide6; assert version('PySide6')=='6.10.2'; assert version('pyinstaller')=='6.19.0'; assert version('Pillow')=='12.3.0'"
if errorlevel 1 (
    echo ERROR: Launcher build dependencies are missing or outdated. Run ..\install.bat.
    exit /b 1
)

echo [2/4] Generating icon...
"%PYTHON%" make_icon.py
if errorlevel 1 (
    echo ERROR: Icon generation failed.
    exit /b 1
)

echo [3/4] Building a fresh isolated launcher...
"%PYTHON%" -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "MikuCure-Launcher" ^
  --icon "%~dp0icon.ico" ^
  --add-data "%ROOT%\miku\icon.png;miku" ^
  --distpath "%DIST%" ^
  --workpath "%WORK%" ^
  --specpath "%WORK%" ^
  "%~dp0main.py"
if errorlevel 1 (
    echo ERROR: PyInstaller failed. No previous launcher was reused.
    exit /b 1
)
if not exist "%DIST%\MikuCure-Launcher.exe" (
    echo ERROR: Fresh launcher artifact is missing.
    exit /b 1
)

echo [4/4] Publishing to the project root...
copy /b /y "%DIST%\MikuCure-Launcher.exe" "%ROOT%\MikuCure-Launcher.exe" >nul
if errorlevel 1 (
    echo ERROR: Could not replace the root launcher. Close the running launcher and retry.
    exit /b 1
)
echo OK: %ROOT%\MikuCure-Launcher.exe
rmdir /s /q "%DIST%" >nul 2>&1
rmdir /s /q "%WORK%" >nul 2>&1
exit /b 0
