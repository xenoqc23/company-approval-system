@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" local_full.py run
set "RESULT=%errorlevel%"
pause
exit /b %RESULT%
:missing
echo First run SETUP_LOCAL_FULL.bat
pause
exit /b 1
