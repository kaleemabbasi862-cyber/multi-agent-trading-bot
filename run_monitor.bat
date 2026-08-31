@echo off
title TradeTalk AI - Autonomous TradingView Monitor
echo ================================================================
echo       TradeTalk AI - Autonomous TradingView Monitor Agent
echo ================================================================
echo.
echo [*] Target Chart: XAUUSD (Gold)
echo [*] Live Webhook: https://multi-agent-trading-bot.onrender.com/webhook/tradingview
echo [*] Dashboard   : https://multi-agent-trading-bot.onrender.com
echo.
echo [*] Starting Playwright Chromium monitor...
echo.
python tradingview_live_monitor.py --symbol OANDA:XAUUSD --interval 3
pause
