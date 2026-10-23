@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 local_full.py setup
goto finished
:use_python
python local_full.py setup
:finished
set "RESULT=%errorlevel%"
pause
exit /b %RESULT%
