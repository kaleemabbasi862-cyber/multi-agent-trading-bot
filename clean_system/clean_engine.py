"""
TradeTalk Clean Engine - Standalone Quant Engine & Web Dashboard
Unified 2-File Architecture
"""

import asyncio
import datetime
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import uvicorn
import yfinance as yf
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

# Setup Plain-Text Logging (Immune to Windows cp1252 charmap errors)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CleanEngine")

# Configuration
BRIDGE_URL = "http://127.0.0.1:5001"
SYMBOL = "XAUUSD"
LOT_SIZE = 0.01
# 350 pips on Gold (where pipSize=0.01) = $3.50 price distance
SL_PIPS = 350.0   # $3.50 on Gold
TP_PIPS = 700.0   # $7.00 on Gold (1:2 R:R)
TRADE_COOLDOWN_SECONDS = 900  # 15 minutes
SCAN_INTERVAL_SECONDS = 30    # Scan interval for candle close check

# Engine State
state: Dict[str, Any] = {
    "autopilot": False,
    "last_scan_time": None,
    "last_trade_time": None,
    "last_trade_action": None,
    "cooldown_remaining": 0,
    "bridge_connected": False,
    "bridge_account": {},
    "positions": [],
    "history": [],
    "last_signal": None,
    "market_data": {
        "symbol": "XAUUSD (Gold)",
        "price": 0.0,
        "ema50_15m": 0.0,
        "ema200_15m": 0.0,
        "rsi14_15m": 0.0,
        "trend_1h": "NEUTRAL",
        "trend_15m": "NEUTRAL",
        "last_candle_time": None,
    },
    "logs": [],
}


def add_log(msg: str):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {msg}"
    safe_msg = msg.encode("ascii", "replace").decode("ascii")
    try:
        logger.info(safe_msg)
    except Exception:
        pass
    state["logs"].append(log_entry)
    if len(state["logs"]) > 100:
        state["logs"].pop(0)


def fetch_bridge_status() -> bool:
    """Fetch status, account info, open positions, and history from cBot Bridge."""
    try:
        r = requests.get(f"{BRIDGE_URL}/", timeout=3)
        if r.status_code == 200:
            data = r.json()
            state["bridge_connected"] = True
            state["bridge_account"] = {
                "account_id": data.get("account_id", "--"),
                "broker": data.get("broker", "--"),
                "is_live": data.get("is_live", False),
                "balance": data.get("balance", 0.0),
                "equity": data.get("equity", 0.0),
                "margin": data.get("margin", 0.0),
                "free_margin": data.get("free_margin", 0.0),
                "open_count": data.get("open_positions_count", 0),
            }
            state["positions"] = data.get("positions", [])
            state["history"] = data.get("history", [])
            return True
        else:
            state["bridge_connected"] = False
            return False
    except Exception:
        state["bridge_connected"] = False
        return False


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    for i in range(period, len(series)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss.replace(0, 0.00001)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def fetch_and_analyze_market() -> Optional[Dict[str, Any]]:
    """Fetch XAUUSD candles and compute EMA 50, EMA 200, and RSI 14."""
    try:
        ticker = yf.Ticker("GC=F")
        df_15m = ticker.history(period="5d", interval="15m")
        if df_15m.empty or len(df_15m) < 60:
            ticker = yf.Ticker("XAUUSD=X")
            df_15m = ticker.history(period="5d", interval="15m")

        if df_15m.empty:
            add_log("[WARN] No market data received from feed.")
            return None

        # 1H Macro Trend
        df_1h = ticker.history(period="30d", interval="1h")
        if not df_1h.empty and len(df_1h) >= 50:
            df_1h["EMA50"] = df_1h["Close"].ewm(span=50, adjust=False).mean()
            last_1h_close = float(df_1h["Close"].iloc[-1])
            last_1h_ema50 = float(df_1h["EMA50"].iloc[-1])
            trend_1h = "BULLISH" if last_1h_close > last_1h_ema50 else "BEARISH"
        else:
            trend_1h = "NEUTRAL"

        # 15M Indicators
        df_15m["EMA50"] = df_15m["Close"].ewm(span=50, adjust=False).mean()
        df_15m["EMA200"] = df_15m["Close"].ewm(span=200, adjust=False).mean()
        df_15m["RSI14"] = calculate_rsi(df_15m["Close"], 14)

        latest = df_15m.iloc[-1]
        candle_time = str(df_15m.index[-1])
        current_price = float(latest["Close"])
        ema50 = float(latest["EMA50"])
        ema200 = float(latest["EMA200"])
        rsi = float(latest["RSI14"]) if not pd.isna(latest["RSI14"]) else 50.0

        trend_15m = "BULLISH" if (ema50 > ema200 and current_price > ema50) else ("BEARISH" if (ema50 < ema200 and current_price < ema50) else "NEUTRAL")

        state["market_data"] = {
            "symbol": "XAUUSD (Gold)",
            "price": round(current_price, 2),
            "ema50_15m": round(ema50, 2),
            "ema200_15m": round(ema200, 2),
            "rsi14_15m": round(rsi, 2),
            "trend_1h": trend_1h,
            "trend_15m": trend_15m,
            "last_candle_time": candle_time,
        }

        # Confluence Signal Logic
        signal = "HOLD"
        reason = "No Trend/Momentum confluence"

        if trend_1h == "BULLISH" and ema50 > ema200 and current_price > ema50 and (50.0 <= rsi <= 68.0):
            signal = "BUY"
            reason = f"Confluence BUY: 1H Bullish + 15M EMA50 ({ema50:.1f}) > EMA200 ({ema200:.1f}) + RSI ({rsi:.1f})"
        elif trend_1h == "BEARISH" and ema50 < ema200 and current_price < ema50 and (32.0 <= rsi <= 50.0):
            signal = "SELL"
            reason = f"Confluence SELL: 1H Bearish + 15M EMA50 ({ema50:.1f}) < EMA200 ({ema200:.1f}) + RSI ({rsi:.1f})"

        analysis_result = {
            "signal": signal,
            "reason": reason,
            "price": current_price,
            "ema50": ema50,
            "ema200": ema200,
            "rsi": rsi,
            "trend_1h": trend_1h,
            "trend_15m": trend_15m,
            "candle_time": candle_time,
        }
        state["last_signal"] = analysis_result
        return analysis_result

    except Exception as e:
        add_log(f"[ERROR] Market analysis exception: {str(e)}")
        return None


def forward_trade_to_bridge(payload: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    """Forward trade payload directly to local cBot bridge at http://127.0.0.1:5001/trade."""
    action = payload.get("action", "BUY").upper()
    sym = payload.get("symbol", SYMBOL)
    # Ensure minimum 350 pips ($3.50 on Gold)
    if "sl_pips" not in payload or payload["sl_pips"] < 100:
        payload["sl_pips"] = SL_PIPS
    if "tp_pips" not in payload or payload["tp_pips"] < 200:
        payload["tp_pips"] = TP_PIPS

    add_log(f"[DISPATCH] Direct Forward to Bridge: {action} {sym} (SL {payload['sl_pips']} pips / TP {payload['tp_pips']} pips)")
    try:
        r = requests.post(f"{BRIDGE_URL}/trade", json=payload, timeout=5)
        try:
            res_data = r.json()
        except Exception:
            res_data = {"status": "RAW_RESPONSE", "text": r.text}

        if r.status_code == 200 and res_data.get("status") == "SUCCESS":
            state["last_trade_time"] = time.time()
            state["last_trade_action"] = action
            pos_id = res_data.get("position_id", "--")
            entry = res_data.get("entry_price", "--")
            sl = res_data.get("sl", "--")
            tp = res_data.get("tp", "--")
            add_log(f"[FILLED] Bridge [200 OK]: #{pos_id} {action} @ {entry} | SL: {sl} | TP: {tp}")
        else:
            err = res_data.get("error", res_data.get("message", "Bridge rejected order"))
            add_log(f"[BRIDGE_REJECT] Status {r.status_code}: {err}")

        fetch_bridge_status()
        return r.status_code, res_data
    except requests.exceptions.ConnectionError:
        err_msg = "Bridge connection failed. Make sure TradeTalkBridge is running in cTrader on port 5001."
        add_log(f"[ERROR] {err_msg}")
        return 502, {"status": "ERROR", "error": err_msg}
    except Exception as ex:
        add_log(f"[ERROR] Bridge request exception: {str(ex)}")
        return 500, {"status": "ERROR", "error": str(ex)}


# FastAPI App
app = FastAPI(title="TradeTalk CleanEngine", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return HTML_DASHBOARD


@app.get("/api/status")
async def get_status():
    fetch_bridge_status()
    now = time.time()
    if state["last_trade_time"]:
        elapsed = now - state["last_trade_time"]
        state["cooldown_remaining"] = max(0, int(TRADE_COOLDOWN_SECONDS - elapsed))
    else:
        state["cooldown_remaining"] = 0

    return JSONResponse(state)


@app.post("/trade")
@app.post("/api/trade")
@app.post("/api/trade/manual")
async def api_trade_forward(req: Request):
    """Direct forwarder from Dashboard to cTrader C# HTTP Bridge."""
    try:
        payload = await req.json()
    except Exception:
        payload = {}

    status_code, res_data = forward_trade_to_bridge(payload)
    return JSONResponse(res_data, status_code=status_code)


@app.post("/api/scan")
async def api_scan():
    state["last_scan_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    add_log("[SCAN] Manual Market Confluence Scan triggered...")
    analysis = fetch_and_analyze_market()
    return JSONResponse({"status": "SUCCESS", "analysis": analysis, "state": state})


@app.post("/api/autopilot")
async def api_toggle_autopilot(req: Request):
    try:
        data = await req.json()
        enabled = data.get("enabled", not state["autopilot"])
    except Exception:
        enabled = not state["autopilot"]

    state["autopilot"] = enabled
    mode_str = "ENABLED [ON]" if enabled else "DISABLED [OFF]"
    add_log(f"[AUTOPILOT] Mode changed to: {mode_str}")
    return JSONResponse({"status": "SUCCESS", "autopilot": state["autopilot"]})


# Background Auto-Pilot Worker
async def quant_worker_loop():
    logger.info("[STARTUP] Background Quant Loop running...")
    while True:
        try:
            fetch_bridge_status()
            now = time.time()
            if state["last_trade_time"]:
                elapsed = now - state["last_trade_time"]
                state["cooldown_remaining"] = max(0, int(TRADE_COOLDOWN_SECONDS - elapsed))

            if state["autopilot"]:
                if len(state["positions"]) == 0 and state["cooldown_remaining"] == 0:
                    analysis = fetch_and_analyze_market()
                    state["last_scan_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if analysis and analysis["signal"] in ["BUY", "SELL"]:
                        add_log(f"[AUTOPILOT] Signal Triggered: {analysis['signal']} ({analysis['reason']})")
                        payload = {
                            "action": analysis["signal"],
                            "symbol": SYMBOL,
                            "volume": LOT_SIZE,
                            "sl_pips": SL_PIPS,
                            "tp_pips": TP_PIPS,
                            "comment": f"AutoPilot {analysis['signal']}",
                        }
                        forward_trade_to_bridge(payload)
                else:
                    fetch_and_analyze_market()
            else:
                fetch_and_analyze_market()

        except Exception as e:
            logger.error(f"Quant loop error: {e}")

        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@app.on_event("startup")
async def startup_event():
    add_log("[STARTUP] CleanEngine initialized on http://127.0.0.1:8000")
    fetch_bridge_status()
    asyncio.create_task(quant_worker_loop())


# Embedded Modern HTML Dashboard
HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TradeTalk AI - Quant Control Room</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #090c10;
            --card-bg: #161b22;
            --card-border: #30363d;
            --accent-blue: #58a6ff;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-yellow: #d29922;
            --text-main: #f0f6fc;
            --text-dim: #8b949e;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg-dark);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            font-size: 14px;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 24px;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            margin-bottom: 20px;
        }
        .logo { display: flex; align-items: center; gap: 12px; }
        .logo-badge {
            background: linear-gradient(135deg, #1f6feb, #8957e5);
            padding: 8px 14px;
            border-radius: 8px;
            font-weight: 800;
            font-size: 16px;
            letter-spacing: 0.5px;
        }
        .controls { display: flex; align-items: center; gap: 14px; }
        .badge {
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .badge-online { background: rgba(63, 185, 80, 0.15); color: var(--accent-green); border: 1px solid var(--accent-green); }
        .badge-offline { background: rgba(248, 81, 73, 0.15); color: var(--accent-red); border: 1px solid var(--accent-red); }
        .btn {
            background: #21262d;
            color: var(--text-main);
            border: 1px solid var(--card-border);
            padding: 8px 16px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 13px;
        }
        .btn:hover { background: #30363d; border-color: var(--accent-blue); }
        .btn-primary { background: #238636; border-color: #2ea043; color: #fff; }
        .btn-primary:hover { background: #2ea043; }
        .btn-danger { background: #da3633; border-color: #f85149; color: #fff; }
        .btn-danger:hover { background: #f85149; }
        
        .toggle-btn {
            padding: 8px 18px;
            border-radius: 8px;
            font-weight: 700;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
        }
        .toggle-on { background: var(--accent-green); color: #000; }
        .toggle-off { background: #30363d; color: var(--text-dim); }

        .grid-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 16px;
        }
        .stat-label { color: var(--text-dim); font-size: 12px; margin-bottom: 6px; text-transform: uppercase; font-weight: 600; }
        .stat-val { font-size: 22px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }

        .main-layout {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        @media (max-width: 1024px) {
            .main-layout { grid-template-columns: 1fr; }
        }

        .section-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .section-title {
            font-size: 15px;
            font-weight: 700;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 10px;
        }

        .indicator-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin-bottom: 16px;
        }
        .ind-box {
            background: #0d1117;
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 12px;
            text-align: center;
        }
        .ind-box .label { font-size: 11px; color: var(--text-dim); margin-bottom: 4px; }
        .ind-box .val { font-family: 'JetBrains Mono', monospace; font-size: 16px; font-weight: 700; }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        th {
            text-align: left;
            padding: 10px 12px;
            background: #0d1117;
            color: var(--text-dim);
            font-weight: 600;
            border-bottom: 1px solid var(--card-border);
        }
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #21262d;
            font-family: 'JetBrains Mono', monospace;
        }
        tr:hover { background: #1f242c; }

        .log-box {
            background: #0d1117;
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 14px;
            height: 240px;
            overflow-y: auto;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: #7ee787;
            line-height: 1.6;
        }
        .pill-buy { color: var(--accent-green); font-weight: bold; }
        .pill-sell { color: var(--accent-red); font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="logo">
                <div class="logo-badge">TRADETALK QUANT</div>
                <div>
                    <h2 style="font-size: 18px; font-weight: 700;">Zero-Bloat Production Engine</h2>
                    <p style="color: var(--text-dim); font-size: 12px;">cTrader cBot Clean Bridge & Bull/Bear Trend Confluence</p>
                </div>
            </div>
            <div class="controls">
                <span id="bridgeBadge" class="badge badge-offline">BRIDGE OFFLINE</span>
                <button id="autopilotBtn" class="toggle-btn toggle-off" onclick="toggleAutopilot()">AUTO-PILOT: OFF</button>
                <button class="btn btn-primary" onclick="triggerScan()">Scan Now</button>
            </div>
        </div>

        <!-- Metric Stat Cards -->
        <div class="grid-stats">
            <div class="stat-card">
                <div class="stat-label">Balance / Equity</div>
                <div id="statBalance" class="stat-val">$0.00</div>
                <div id="statEquity" style="color: var(--text-dim); font-size: 12px; font-family: 'JetBrains Mono'; margin-top: 4px;">Equity: $0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">XAUUSD Live Feed</div>
                <div id="statGoldPrice" class="stat-val" style="color: var(--accent-yellow);">$0.00</div>
                <div id="statCandleTime" style="color: var(--text-dim); font-size: 11px; margin-top: 4px;">15M Candle: --</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Strategy Signal</div>
                <div id="statSignal" class="stat-val" style="color: var(--text-dim);">HOLD</div>
                <div id="statSignalReason" style="color: var(--text-dim); font-size: 11px; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">Awaiting setup</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Safety & Cooldown</div>
                <div id="statCooldown" class="stat-val" style="color: var(--accent-green);">READY</div>
                <div id="statActivePosCount" style="color: var(--text-dim); font-size: 12px; margin-top: 4px;">Open Trades: 0 / 1 Max</div>
            </div>
        </div>

        <div class="main-layout">
            <!-- Left Main Column -->
            <div>
                <!-- Market & Strategy Indicators -->
                <div class="section-card">
                    <div class="section-title">
                        <span>15M / 1H Trend Confluence Matrix (XAUUSD)</span>
                        <span id="macroTrendBadge" class="badge badge-online">1H: NEUTRAL</span>
                    </div>
                    <div class="indicator-grid">
                        <div class="ind-box">
                            <div class="label">EMA 50 (15M)</div>
                            <div id="indEma50" class="val">--</div>
                        </div>
                        <div class="ind-box">
                            <div class="label">EMA 200 (15M)</div>
                            <div id="indEma200" class="val">--</div>
                        </div>
                        <div class="ind-box">
                            <div class="label">RSI 14 (15M)</div>
                            <div id="indRsi" class="val">--</div>
                        </div>
                        <div class="ind-box">
                            <div class="label">15M Bias</div>
                            <div id="indTrend15m" class="val">--</div>
                        </div>
                    </div>

                    <!-- Manual Controls -->
                    <div style="display: flex; gap: 12px; margin-top: 14px;">
                        <button class="btn btn-primary" style="flex: 1; padding: 12px 16px; font-size: 14px;" onclick="sendManualTrade('BUY')">Buy 0.01 XAUUSD (SL $3.50 / TP $7.00)</button>
                        <button class="btn btn-danger" style="flex: 1; padding: 12px 16px; font-size: 14px;" onclick="sendManualTrade('SELL')">Sell 0.01 XAUUSD (SL $3.50 / TP $7.00)</button>
                    </div>
                </div>

                <!-- Active Open Positions -->
                <div class="section-card">
                    <div class="section-title">
                        <span>Active Position (Hard Max Limit: 1)</span>
                        <span id="openCountBadge" style="font-size: 12px; color: var(--text-dim);">0 Open</span>
                    </div>
                    <div id="positionsContainer">
                        <p style="color: var(--text-dim); padding: 12px 0;">No active positions open. Scanner ready for valid candle close setups.</p>
                    </div>
                </div>

                <!-- Closed Trades History Ledger -->
                <div class="section-card">
                    <div class="section-title">
                        <span>Closed Trades Ledger (cTrader History)</span>
                        <span style="font-size: 12px; color: var(--text-dim);">Last 50 Verified Trades</span>
                    </div>
                    <div style="max-height: 280px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Symbol</th>
                                    <th>Side</th>
                                    <th>Lots</th>
                                    <th>Entry</th>
                                    <th>Close</th>
                                    <th>PnL ($)</th>
                                    <th>Closed Time</th>
                                </tr>
                            </thead>
                            <tbody id="historyTableBody">
                                <tr><td colspan="8" style="text-align: center; color: var(--text-dim);">No closed trade history yet.</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Right Sidebar Column: Real-time Terminal Log -->
            <div>
                <div class="section-card">
                    <div class="section-title">
                        <span>System Telemetry Log</span>
                        <button class="btn" style="padding: 3px 8px; font-size: 11px;" onclick="clearLogsUI()">Clear</button>
                    </div>
                    <div id="logBox" class="log-box"></div>
                </div>

                <div class="section-card">
                    <div class="section-title">
                        <span>Active Safety Rules</span>
                    </div>
                    <ul style="color: var(--text-dim); font-size: 12px; line-height: 1.8; padding-left: 18px;">
                        <li><strong style="color: var(--text-main);">Max Positions:</strong> 1 concurrent trade</li>
                        <li><strong style="color: var(--text-main);">Min SL Buffer:</strong> $3.50 on Gold (350 points)</li>
                        <li><strong style="color: var(--text-main);">Min Hold Time:</strong> 300s (5 minutes)</li>
                        <li><strong style="color: var(--text-main);">Trade Cooldown:</strong> 15 minutes between trades</li>
                        <li><strong style="color: var(--text-main);">Spread Guard:</strong> Rejected if spread > $0.45</li>
                    </ul>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                // Bridge Badge
                const bBadge = document.getElementById('bridgeBadge');
                if (data.bridge_connected) {
                    bBadge.textContent = 'BRIDGE CONNECTED (' + (data.bridge_account.broker || 'cTrader') + ' #' + data.bridge_account.account_id + ')';
                    bBadge.className = 'badge badge-online';
                } else {
                    bBadge.textContent = 'BRIDGE OFFLINE (Port 5001)';
                    bBadge.className = 'badge badge-offline';
                }

                // Auto-Pilot Button
                const apBtn = document.getElementById('autopilotBtn');
                if (data.autopilot) {
                    apBtn.textContent = 'AUTO-PILOT: ACTIVE [ON]';
                    apBtn.className = 'toggle-btn toggle-on';
                } else {
                    apBtn.textContent = 'AUTO-PILOT: OFF [OFF]';
                    apBtn.className = 'toggle-btn toggle-off';
                }

                // Balance & Stats
                if (data.bridge_account && data.bridge_account.balance !== undefined) {
                    document.getElementById('statBalance').textContent = '$' + Number(data.bridge_account.balance).toFixed(2);
                    document.getElementById('statEquity').textContent = 'Equity: $' + Number(data.bridge_account.equity).toFixed(2);
                }

                // Gold & Indicators
                if (data.market_data) {
                    document.getElementById('statGoldPrice').textContent = '$' + Number(data.market_data.price).toFixed(2);
                    document.getElementById('statCandleTime').textContent = '15M Candle: ' + (data.market_data.last_candle_time ? data.market_data.last_candle_time.split(' ')[0] : '--');
                    document.getElementById('indEma50').textContent = '$' + Number(data.market_data.ema50_15m).toFixed(2);
                    document.getElementById('indEma200').textContent = '$' + Number(data.market_data.ema200_15m).toFixed(2);
                    document.getElementById('indRsi').textContent = Number(data.market_data.rsi14_15m).toFixed(1);
                    document.getElementById('indTrend15m').textContent = data.market_data.trend_15m;
                    document.getElementById('macroTrendBadge').textContent = '1H Trend: ' + data.market_data.trend_1h;
                    document.getElementById('macroTrendBadge').className = data.market_data.trend_1h === 'BULLISH' ? 'badge badge-online' : (data.market_data.trend_1h === 'BEARISH' ? 'badge badge-offline' : 'badge');
                }

                // Signal
                if (data.last_signal) {
                    const sigEl = document.getElementById('statSignal');
                    sigEl.textContent = data.last_signal.signal;
                    sigEl.style.color = data.last_signal.signal === 'BUY' ? 'var(--accent-green)' : (data.last_signal.signal === 'SELL' ? 'var(--accent-red)' : 'var(--text-dim)');
                    document.getElementById('statSignalReason').textContent = data.last_signal.reason;
                }

                // Cooldown & Position Guard
                const cdEl = document.getElementById('statCooldown');
                if (data.cooldown_remaining > 0) {
                    cdEl.textContent = 'COOLDOWN (' + data.cooldown_remaining + 's)';
                    cdEl.style.color = 'var(--accent-yellow)';
                } else {
                    cdEl.textContent = 'READY';
                    cdEl.style.color = 'var(--accent-green)';
                }
                document.getElementById('statActivePosCount').textContent = 'Open Trades: ' + (data.positions ? data.positions.length : 0) + ' / 1 Max';

                // Positions View
                const posContainer = document.getElementById('positionsContainer');
                if (data.positions && data.positions.length > 0) {
                    let html = '<table><thead><tr><th>ID</th><th>Symbol</th><th>Side</th><th>Lots</th><th>Entry</th><th>SL</th><th>TP</th><th>PnL ($)</th><th>Action</th></tr></thead><tbody>';
                    data.positions.forEach(p => {
                        const pnlColor = p.net_profit >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
                        html += `<tr>
                            <td>#${p.id}</td>
                            <td><strong>${p.symbol}</strong></td>
                            <td class="${p.trade_type === 'BUY' ? 'pill-buy' : 'pill-sell'}">${p.trade_type}</td>
                            <td>${p.volume}</td>
                            <td>$${Number(p.entry_price).toFixed(2)}</td>
                            <td>$${Number(p.sl).toFixed(2)}</td>
                            <td>$${Number(p.tp).toFixed(2)}</td>
                            <td style="color: ${pnlColor}; font-weight: bold;">$${Number(p.net_profit).toFixed(2)} (${Number(p.pips).toFixed(1)} pips)</td>
                            <td><button class="btn btn-danger" style="padding: 4px 8px; font-size: 11px;" onclick="closePosition(${p.id})">Close</button></td>
                        </tr>`;
                    });
                    html += '</tbody></table>';
                    posContainer.innerHTML = html;
                } else {
                    posContainer.innerHTML = '<p style="color: var(--text-dim); padding: 12px 0;">No active positions open. Scanner ready for valid candle close setups.</p>';
                }

                // History View
                const histBody = document.getElementById('historyTableBody');
                if (data.history && data.history.length > 0) {
                    let hHtml = '';
                    data.history.forEach(h => {
                        const pnlColor = h.net_profit >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
                        hHtml += `<tr>
                            <td>#${h.id || h.position_id}</td>
                            <td>${h.symbol}</td>
                            <td class="${h.trade_type === 'BUY' ? 'pill-buy' : 'pill-sell'}">${h.trade_type}</td>
                            <td>${h.volume}</td>
                            <td>$${Number(h.entry_price).toFixed(2)}</td>
                            <td>$${Number(h.closing_price).toFixed(2)}</td>
                            <td style="color: ${pnlColor}; font-weight: bold;">$${Number(h.net_profit).toFixed(2)}</td>
                            <td style="font-size: 11px; color: var(--text-dim);">${h.closing_time ? h.closing_time.replace('T', ' ').substring(0, 19) : '--'}</td>
                        </tr>`;
                    });
                    histBody.innerHTML = hHtml;
                }

                // Logs View
                const logBox = document.getElementById('logBox');
                if (data.logs && data.logs.length > 0) {
                    logBox.innerHTML = data.logs.map(l => `<div>${l}</div>`).join('');
                    logBox.scrollTop = logBox.scrollHeight;
                }

            } catch (err) {
                console.error('Fetch error:', err);
            }
        }

        async function toggleAutopilot() {
            const res = await fetch('/api/autopilot', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
            fetchStatus();
        }

        async function triggerScan() {
            await fetch('/api/scan', { method: 'POST' });
            fetchStatus();
        }

        async function sendManualTrade(action) {
            if (!confirm(`Execute immediate manual ${action} order on XAUUSD (0.01 lots, SL $3.50, TP $7.00)?`)) return;
            try {
                const payload = {
                    action: action,
                    symbol: "XAUUSD",
                    volume: 0.01,
                    sl_pips: 350,
                    tp_pips: 700,
                    comment: "Manual UI " + action
                };
                const res = await fetch('/trade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.status === 200 && data.status === 'SUCCESS') {
                    alert(`Order Filled: #${data.position_id} | ${data.trade_type || action} @ ${data.entry_price} (SL: ${data.sl}, TP: ${data.tp})`);
                } else {
                    alert(`Bridge Note: ${data.error || data.message || JSON.stringify(data)}`);
                }
                fetchStatus();
            } catch (err) {
                alert('Network error communicating with engine /trade endpoint: ' + err.message);
            }
        }

        async function closePosition(posId) {
            if (!confirm(`Close position #${posId}?`)) return;
            try {
                const res = await fetch('/trade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'CLOSE', position_id: posId, force: true })
                });
                const data = await res.json();
                alert(data.message || data.error || 'Request sent');
                fetchStatus();
            } catch (err) {
                alert('Error closing position: ' + err.message);
            }
        }

        function clearLogsUI() {
            document.getElementById('logBox').innerHTML = '';
        }

        // Auto Refresh every 3 seconds
        setInterval(fetchStatus, 3000);
        fetchStatus();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    print("=================================================================")
    print("   TRADETALK ZERO-BLOAT QUANT ENGINE (clean_engine.py)")
    print("=================================================================")
    print("Dashboard listening on: http://127.0.0.1:8000")
    print("Connected to Bridge on: http://127.0.0.1:5001")
    print("=================================================================")
    uvicorn.run("clean_engine:app", host="127.0.0.1", port=8000, reload=False, log_level="warning")
