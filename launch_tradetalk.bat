@echo off
setlocal
cd /d "%~dp0"
title TradeTalk AI Launcher

echo ===================================================
echo        TradeTalk AI - Professional Launcher
echo ===================================================
echo [*] Verifying the existing TradeTalk backend safely...

call "%~dp0launch_desktop_app.bat" %*
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo [ERROR] TradeTalk launcher exited with code %RC%.
)
exit /b %RC%
