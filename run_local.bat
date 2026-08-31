@echo off
setlocal enabledelayedexpansion

title Multi-Agent Trading System - Local Launcher
echo ================================================================
echo       Multi-Agent AI Forex Trading System - Local Runner
echo ================================================================
echo.

:: 1. Check for .env file
if not exist .env (
    if exist .env.example (
        echo [*] Creating .env from .env.example...
        copy .env.example .env
        echo [!] Please update your API key in .env if not already set.
    )
)

:: 2. Check for Cloudflared executable
if not exist cloudflared.exe (
    where cloudflared >nul 2>nul
    if %errorlevel% neq 0 (
        echo [*] cloudflared.exe not found. Downloading Cloudflare Tunnel for Windows...
        powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
        if exist cloudflared.exe (
            echo [+] cloudflared.exe downloaded successfully.
        ) else (
            echo [!] Cloudflared download skipped. You can manually install cloudflared or use ngrok.
        )
    )
)

echo.
echo [*] Starting FastAPI Multi-Agent Webhook Server on port 8000...
start "Multi-Agent FastAPI Server" cmd /k "python -m uvicorn main_native:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 2 >nul

echo [*] Starting Cloudflare Tunnel...
if exist cloudflared.exe (
    start "Cloudflare Public Tunnel" cmd /k "cloudflared.exe tunnel --url http://localhost:8000"
) else (
    where cloudflared >nul 2>nul
    if %errorlevel% equ 0 (
        start "Cloudflare Public Tunnel" cmd /k "cloudflared tunnel --url http://localhost:8000"
    ) else (
        echo [!] Cloudflare tunnel executable not found. Running local server only.
    )
)

echo.
echo ================================================================
echo [+] System started!
echo     - Local Endpoint: http://localhost:8000/webhook/tradingview
echo     - Check the Cloudflare window for your public HTTPS Webhook URL
echo     - Use that HTTPS URL in your TradingView Webhook alert settings
echo ================================================================
echo.
pause
