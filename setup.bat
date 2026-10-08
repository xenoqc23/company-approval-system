@echo off
chcp 65001 >nul
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 launcher.py setup
goto finished
:use_python
where python >nul 2>&1
if errorlevel 1 goto missing_python
python launcher.py setup
goto finished
:missing_python
echo Python was not found. Install Python and then run setup.bat again.
echo See START_HERE.txt for installation steps.
pause
exit /b 1
:finished
set "SETUP_RESULT=%errorlevel%"
pause
exit /b %SETUP_RESULT%
