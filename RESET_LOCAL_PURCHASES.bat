@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" local_purchases.py reset
set "RESULT=%errorlevel%"
pause
exit /b %RESULT%
:missing
echo First run SETUP_LOCAL_PURCHASES.bat
pause
exit /b 1
