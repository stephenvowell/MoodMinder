@echo off
setlocal
cd /d "%~dp0"
title Build Mood Minder standalone EXE

echo.
echo  Build a standalone MoodMinder.exe
echo  (Target PC will NOT need Python installed)
echo.

where py >nul 2>&1
if %errorlevel%==0 (
  set PY=py -3
) else (
  set PY=python
)

echo Installing PyInstaller...
%PY% -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

echo.
echo Building EXE...
%PY% -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name MoodMinder ^
  --hidden-import mood_engine ^
  --hidden-import pdf_export ^
  app.py
if errorlevel 1 goto :fail

echo.
echo Done.
echo EXE location:
echo   %cd%\dist\MoodMinder.exe
echo.
pause
exit /b 0

:fail
echo Build failed.
pause
exit /b 1
