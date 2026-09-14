@echo off
setlocal
cd /d "%~dp0"
title TradeTalk AI - Desktop App Launcher

set "PYEXE="
for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PYEXE set "PYEXE=%%P"
if not defined PYEXE (
    for /f "delims=" %%P in ('where py.exe 2^>nul') do if not defined PYEXE set "PYEXE=%%P"
)

if not defined PYEXE (
    echo [ERROR] Python was not found. Install Python or add it to PATH.
    exit /b 1
)

"%PYEXE%" "launch_desktop_app.py" %*
exit /b %errorlevel%
