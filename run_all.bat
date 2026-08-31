@echo off
title TradeTalk AI - Full Autonomous System
echo ================================================================
echo         TradeTalk AI - Full System Launcher (Local + Monitor)
echo ================================================================
echo.

:: 1. Start Local FastAPI Dashboard Server
echo [*] Starting Local FastAPI Webhook & UI Dashboard on port 8000...
start "TradeTalk AI - FastAPI Server" cmd /k "python -m uvicorn main_native:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3 >nul

:: 2. Start Autonomous TradingView Live Monitor
echo [*] Starting Autonomous Playwright TradingView Monitor...
start "TradeTalk AI - TradingView Monitor" cmd /k "python tradingview_live_monitor.py --symbol OANDA:XAUUSD --interval 3"

echo.
echo ================================================================
echo [+] Full System is running!
echo     - Local Dashboard: http://localhost:8000
echo     - Cloud Dashboard: https://multi-agent-trading-bot.onrender.com
echo ================================================================
echo.
pause
