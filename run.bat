@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto not_installed
".venv\Scripts\python.exe" launcher.py run
set "RUN_RESULT=%errorlevel%"
pause
exit /b %RUN_RESULT%
:not_installed
echo First, double-click setup.bat and finish installation.
echo See START_HERE.txt for installation steps.
pause
exit /b 1
