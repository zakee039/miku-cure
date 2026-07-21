@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  Building Miku Cure portable package (CPU)…
echo  This may take 10–30 minutes (site-packages + zip).
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0package_portable.ps1" %*
if errorlevel 1 (
  echo.
  echo  PACKAGE FAILED
  pause
  exit /b 1
)
echo.
pause
