@echo off
setlocal
cd /d "%~dp0"
title HumanPredict Installer

echo.
echo  HumanPredict Installer
echo  ----------------------
echo  This will:
echo    1) Check for Python 3.10+
echo    2) Create a local virtual environment
echo    3) Install requirements
echo    4) Add Desktop and Start Menu shortcuts
echo.

REM Prefer PowerShell 7 if present, else Windows PowerShell
where pwsh >nul 2>&1
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
)

set EXITCODE=%errorlevel%
echo.
if not %EXITCODE%==0 (
  echo Installer finished with errors.
  pause
  exit /b %EXITCODE%
)
pause
exit /b 0
