@echo off
title TradeTalk Clean Quant Engine
cd /d "%~dp0"

echo =====================================================================
echo    TRADETALK AI - ZERO-BLOAT QUANT ENGINE STARTUP
echo =====================================================================
echo.

echo [1/2] Verifying Python Dependencies...
pip install fastapi uvicorn requests yfinance pandas --quiet

echo.
echo [2/2] Launching Clean Engine Dashboard on http://127.0.0.1:8000 ...
echo cBot HTTP Bridge target: http://127.0.0.1:5001
echo.

python clean_engine.py

pause
