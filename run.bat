@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "app.py"
  exit /b 0
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "app.py"
  exit /b 0
)

where py >nul 2>&1
if %errorlevel%==0 (
  py -3 "app.py"
  exit /b 0
)

where python >nul 2>&1
if %errorlevel%==0 (
  python "app.py"
  exit /b 0
)

echo Python was not found. Run install.bat first.
pause
exit /b 1
