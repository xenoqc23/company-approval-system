@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto use_venv
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 login_reminder.py --disable-autostart
goto finished
:use_venv
".venv\Scripts\python.exe" login_reminder.py --disable-autostart
goto finished
:use_python
python login_reminder.py --disable-autostart
:finished
set "RESULT=%errorlevel%"
pause
exit /b %RESULT%
