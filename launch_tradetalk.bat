@echo off
setlocal EnableDelayedExpansion
title TradeTalk AI Launcher
cd /d "%~dp0"

echo ===================================================
echo           TradeTalk AI - System Launcher
echo ===================================================
echo [*] Checking and clearing stale backend ports (8000)...

:: Terminate any lingering process on port 8000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo [*] Starting TradeTalk Desktop Application...
start "" "C:\Users\AL RAZZAQ\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe" "desktop_app.py"

exit /b 0
