@echo off
setlocal
cd /d "%~dp0"
title Build HumanPredict standalone EXE

echo.
echo  Build a standalone HumanPredict.exe
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
  --name HumanPredict ^
  --hidden-import humanPredict ^
  --hidden-import pdf_export ^
  app.py
if errorlevel 1 goto :fail

echo.
echo Done.
echo EXE location:
echo   %cd%\dist\HumanPredict.exe
echo.
echo Copy that single file to another PC and double-click to run.
echo Logs will be created next to the EXE on first use.
echo.
pause
exit /b 0

:fail
echo Build failed.
pause
exit /b 1
