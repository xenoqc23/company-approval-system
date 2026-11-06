@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 launch.py
goto finished
:use_python
where python >nul 2>&1
if errorlevel 1 goto missing
python launch.py
goto finished
:missing
echo Python 3.10 or later is required. Python 3.12 is recommended.
echo Install from https://www.python.org/downloads/windows/
echo Enable "Add python.exe to PATH", then run this file again.
pause
exit /b 1
:finished
set "RESULT=%errorlevel%"
pause
exit /b %RESULT%
