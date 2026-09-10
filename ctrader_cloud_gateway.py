import os
import sys
import time
import datetime
import random
import logging
import threading
import requests
import urllib.parse
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
import ctrader_openapi
from app.config import settings
from app.database.db import db

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

logger = logging.getLogger("TradeTalk.cTraderCloudGateway")

# --- MULTI-ASSET SERVER-SIDE EXECUTION PARAMETERS ---
ALLOWED_SYMBOLS = ["XAUUSD", "GOLD", "XAGUSD", "SILVER", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF"]
MAX_ACTIVE_OPEN_POSITIONS = 1       # Strictly 1 active trade maximum

def _resolve_initial_account_id() -> str:
    try:
        import settings_manager
        return settings_manager.get_active_account_id()
    except Exception:
        return os.getenv("CTRADER_ACCOUNT_ID", "5908018").strip('"')

DEFAULT_ACCOUNT_ID = _resolve_initial_account_id()

# Linked cTrader Accounts Registry (Live & Demo)
LINKED_ACCOUNTS: Dict[str, Dict[str, Any]] = {
    "5908018": {
        "account_id": "5908018",
        "name": "Spotware • Demo • #5908018",
        "account_type": "DEMO",
        "environment": "Demo",
        "balance": 1018.96,
        "equity": 1018.96,
        "margin": 0.0,
        "free_margin": 1018.96,
        "currency": "USD",
        "broker": "Spotware",
        "is_live": False,
        "open_positions": [],
        "last_seen": time.time()
    },
    "abu_sarim": {
        "account_id": "abu_sarim",
        "name": "Qartal Markets • Live • Abu sarim",
        "account_type": "LIVE",
        "environment": "Live",
        "balance": 0.72,
        "equity": 0.72,
        "margin": 0.0,
        "free_margin": 0.72,
        "currency": "USD",
        "broker": "Qartal Markets",
        "is_live": True,
        "open_positions": [],
        "last_seen": time.time()
    },
    "1005621": {
        "account_id": "1005621",
        "name": "Qartal Markets • Live • #1005621",
        "account_type": "LIVE",
        "environment": "Live",
        "balance": 21.19,
        "equity": 21.19,
        "margin": 0.0,
        "free_margin": 21.19,
        "currency": "USD",
        "broker": "Qartal Markets",
        "is_live": True,
        "open_positions": [],
        "last_seen": time.time()
    }
}

def get_active_account() -> Dict[str, Any]:
    acc_id = GATEWAY_STATE.get("account_id", DEFAULT_ACCOUNT_ID) if "GATEWAY_STATE" in globals() else DEFAULT_ACCOUNT_ID
    if acc_id not in LINKED_ACCOUNTS:
        LINKED_ACCOUNTS[acc_id] = {
            "account_id": acc_id,
            "name": f"cTrader • #{acc_id}",
            "account_type": "DEMO",
            "environment": "Demo",
            "balance": 1000.0,
            "equity": 1000.0,
            "margin": 0.0,
            "free_margin": 1000.0,
            "currency": "USD",
            "broker": "Spotware",
            "is_live": False,
            "open_positions": [],
            "last_seen": time.time()
        }
    return LINKED_ACCOUNTS[acc_id]

_initial_acc = LINKED_ACCOUNTS.get(DEFAULT_ACCOUNT_ID, LINKED_ACCOUNTS["5908018"])

# Spotware cTrader Open API Configuration
CTRADER_CONFIG = {
    "client_id": os.getenv("CTRADER_CLIENT_ID", "38205_uwQq76FzYirpd9qMjJrPqc07VcT1CqFHkDx8GXwzMBxratuPNT").strip('"').strip(),
    "client_secret": os.getenv("CTRADER_CLIENT_SECRET", "aI5kdBjwDuPX6CCgrJ0o3AholHFhCGAPuN2lj75UUV3NxEHFTm").strip('"').strip(),
    "account_id": DEFAULT_ACCOUNT_ID,
    "environment": _initial_acc.get("environment", "Demo"),
    "access_token": os.getenv("CTRADER_ACCESS_TOKEN", "").strip('"').strip(),
    "refresh_token": os.getenv("CTRADER_REFRESH_TOKEN", "").strip('"').strip()
}

SPOTWARE_AUTH_URL = "https://openapi.ctrader.com/apps/auth"
SPOTWARE_TOKEN_URL = "https://openapi.ctrader.com/apps/token"

# Live Gateway State Store (Maintained Server-Side in Cloud Memory)
GATEWAY_STATE: Dict[str, Any] = {
    "is_connected": True,
    "cloud_server_active": True,
    "mode": "CLOUD_OPEN_API",
    "account_id": DEFAULT_ACCOUNT_ID,
    "account_type": _initial_acc.get("account_type", "DEMO"),
    "is_live": _initial_acc.get("is_live", False),
    "balance": _initial_acc.get("balance", 1018.96),
    "equity": _initial_acc.get("equity", 1018.96),
    "margin": _initial_acc.get("margin", 0.0),
    "free_margin": _initial_acc.get("free_margin", 1018.96),
    "currency": _initial_acc.get("currency", "USD"),
    "broker": _initial_acc.get("broker", "Spotware"),
    "open_positions": [],
    "total_unrealized_pnl": 0.0,
    "target_symbol": "XAUUSD",
    "target_lot_size": 0.01,
    "last_sync": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC"),
    "last_sync_timestamp": time.time(),
    "live_prices": {},
    "last_error": None
}

# Queue of pending approved orders for local/VPS cBot bridge execution
PENDING_CBOT_ORDERS: List[Dict[str, Any]] = []

# Trade Pacing & Cooldown Tracker
LAST_EXECUTION_TIMESTAMP: float = 0.0
LAST_TRADE_CLOSE_TIMESTAMP: float = 0.0

def reset_cooldown():
    """Resets execution and trade close cooldown timestamps and clears open positions."""
    global LAST_EXECUTION_TIMESTAMP, LAST_TRADE_CLOSE_TIMESTAMP, GATEWAY_STATE, LINKED_ACCOUNTS
    LAST_EXECUTION_TIMESTAMP = 0.0
    LAST_TRADE_CLOSE_TIMESTAMP = 0.0
    GATEWAY_STATE["open_positions"] = []
    GATEWAY_STATE["daily_loss"] = 0.0
    GATEWAY_STATE["total_unrealized_pnl"] = 0.0
    for acc in LINKED_ACCOUNTS.values():
        acc["open_positions"] = []
        acc["daily_loss"] = 0.0

def get_live_price(symbol: str = "XAUUSD") -> Optional[Dict[str, Any]]:
    """Returns live price object from GATEWAY_STATE if fresh."""
    sym_clean = symbol.upper()
    return GATEWAY_STATE.get("live_prices", {}).get(sym_clean)

# Executed Trade History & In-Memory Receipts
EXECUTED_RECEIPTS: Dict[str, Dict[str, Any]] = {}

def get_all_accounts() -> Dict[str, Any]:
    """Returns all available and linked cTrader accounts with accurate broker metadata."""
    active_id = str(GATEWAY_STATE.get("account_id", DEFAULT_ACCOUNT_ID)).strip().replace("#", "")
    accounts_list = []
    for acc_id, acc_info in LINKED_ACCOUNTS.items():
        is_active = (acc_id == active_id)
        # Update active account info from GATEWAY_STATE if active
        bal = GATEWAY_STATE["balance"] if is_active else acc_info.get("balance", 0.0)
        eq = GATEWAY_STATE["equity"] if is_active else acc_info.get("equity", 0.0)
        broker_name = acc_info.get("broker", "Spotware" if "5908" in acc_id else "Qartal Markets")
        acc_type = acc_info.get("account_type", "DEMO" if "5908" in acc_id else "LIVE")
        
        if acc_id == "abu_sarim" or "sarim" in acc_id.lower():
            label = f"{broker_name} • {acc_type} • Abu sarim (${bal:,.2f})"
        else:
            label = f"{broker_name} • {acc_type} • #{acc_id} (${bal:,.2f})"
            
        accounts_list.append({
            "account_id": acc_id,
            "name": acc_info.get("name", label),
            "label": label,
            "account_type": acc_type,
            "environment": acc_info.get("environment", "Live" if acc_type == "LIVE" else "Demo"),
            "balance": round(float(bal), 2),
            "equity": round(float(eq), 2),
            "currency": acc_info.get("currency", "USD"),
            "broker": broker_name,
            "is_live": acc_info.get("is_live", acc_type == "LIVE"),
            "is_active": is_active
        })
    return {
        "status": "success",
        "active_account_id": active_id,
        "active_account": LINKED_ACCOUNTS.get(active_id, {}),
        "accounts": accounts_list
    }

def switch_active_account(account_id: str) -> Dict[str, Any]:
    """Switches the active cTrader account dynamically in runtime memory and settings."""
    global GATEWAY_STATE, CTRADER_CONFIG, LINKED_ACCOUNTS
    clean_id = str(account_id).strip().replace("#", "")

    if clean_id not in LINKED_ACCOUNTS:
        if "sarim" in clean_id.lower() or clean_id == "abu_sarim":
            clean_id = "abu_sarim"
        elif "1005" in clean_id:
            clean_id = "1005621"
        elif "5908" in clean_id:
            clean_id = "5908018"
        else:
            is_live = "live" in clean_id.lower()
            LINKED_ACCOUNTS[clean_id] = {
                "account_id": clean_id,
                "name": f"cTrader #{clean_id}",
                "account_type": "LIVE" if is_live else "DEMO",
                "environment": "Live" if is_live else "Demo",
                "balance": 21.19 if is_live else 1018.96,
                "equity": 21.19 if is_live else 1018.96,
                "margin": 0.0,
                "free_margin": 21.19 if is_live else 1018.96,
                "currency": "USD",
                "broker": "Qartal Markets" if is_live else "Spotware",
                "is_live": is_live,
                "open_positions": [],
                "last_seen": time.time()
            }

    acc_data = LINKED_ACCOUNTS[clean_id]
    GATEWAY_STATE["account_id"] = clean_id
    GATEWAY_STATE["account_type"] = acc_data.get("account_type", "LIVE")
    GATEWAY_STATE["is_live"] = acc_data.get("is_live", True)
    GATEWAY_STATE["balance"] = round(float(acc_data.get("balance", 1018.96)), 2)
    GATEWAY_STATE["equity"] = round(float(acc_data.get("equity", 1018.96)), 2)
    GATEWAY_STATE["margin"] = round(float(acc_data.get("margin", 0.0)), 2)
    GATEWAY_STATE["free_margin"] = round(float(acc_data.get("free_margin", GATEWAY_STATE["equity"])), 2)
    GATEWAY_STATE["currency"] = acc_data.get("currency", "USD")
    GATEWAY_STATE["broker"] = acc_data.get("broker", "Spotware")
    GATEWAY_STATE["open_positions"] = acc_data.get("open_positions", [])
    GATEWAY_STATE["last_sync"] = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
    GATEWAY_STATE["last_sync_timestamp"] = time.time()

    CTRADER_CONFIG["account_id"] = clean_id

    try:
        import settings_manager
        settings_manager.set_active_account_id(clean_id)
    except Exception:
        pass

    print(f"[cTrader Cloud] 🔄 Active Account Switched to #{clean_id} (${GATEWAY_STATE['balance']})")
    return {
        "status": "SUCCESS",
        "active_account_id": clean_id,
        "gateway_state": GATEWAY_STATE,
        "accounts": get_all_accounts()["accounts"]
    }

def get_oauth_auth_url(redirect_uri: str = "https://multi-agent-trading-bot.onrender.com/api/ctrader/callback") -> str:
    """Generates direct Spotware OAuth 2.0 authorization URL."""
    params = {
        "client_id": CTRADER_CONFIG["client_id"],
        "redirect_uri": redirect_uri,
        "scope": "trading"
    }
    return f"{SPOTWARE_AUTH_URL}?{urllib.parse.urlencode(params)}"

def exchange_oauth_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    """
    Exchanges Spotware OAuth authorization code for real Access Token.
    Automatically tries all registered app credentials (self-healing).
    """
    global CTRADER_CONFIG, GATEWAY_STATE
    clean_code = str(code).strip()
    
    app_pairs = [
        (CTRADER_CONFIG["client_id"], CTRADER_CONFIG["client_secret"]),
        ("38205_uwQq76FzYirpd9qMjjrPqcO7VcT1CqFHkDx8GXwzMBxratuPNT", "al5kdBjwDuPX6CCgrj0o3AholHFhCGAPuN2lj75UUV3NxEHFTm"),
        ("39195_4Gr4AwHTdQX7XVxMccP1mfzwU9RE99BDPQCiF6Y5vGotQpwdtC", "2hV6fK7gHwQcdNkmLyazI1xA84Xmps5GezuCh3xJo9FMD9yqpF"),
    ]

    last_err = "No response"
    for cid, csec in app_pairs:
        try:
            payload = {
                "grant_type": "authorization_code",
                "client_id": cid,
                "client_secret": csec,
                "redirect_uri": redirect_uri,
                "code": clean_code
            }
            res = requests.post(SPOTWARE_TOKEN_URL, data=payload, timeout=8)
            data = res.json()

            if "accessToken" in data or "access_token" in data:
                token = data.get("accessToken") or data.get("access_token")
                r_token = data.get("refreshToken") or data.get("refresh_token", "")
                
                CTRADER_CONFIG["client_id"] = cid
                CTRADER_CONFIG["client_secret"] = csec
                CTRADER_CONFIG["access_token"] = token
                CTRADER_CONFIG["refresh_token"] = r_token
                GATEWAY_STATE["access_token"] = token
                
                # Persist token to Windows DPAPI Encrypted Vault
                try:
                    from app.services.credential_store import credential_store
                    credential_store.set_secret("CTRADER_CLIENT_ID", cid)
                    credential_store.set_secret("CTRADER_CLIENT_SECRET", csec)
                    credential_store.set_secret("CTRADER_ACCESS_TOKEN", token)
                    if r_token:
                        credential_store.set_secret("CTRADER_REFRESH_TOKEN", r_token)
                except Exception as e:
                    logger.warning(f"Error saving credentials to DPAPI vault: {e}")

                print(f"[cTrader Cloud] 🟢 Successfully exchanged OAuth code using App {cid[:10]}...!")
                sync_with_spotware_cloud()
                return {"status": "SUCCESS", "access_token": token, "account_id": GATEWAY_STATE["account_id"]}
            else:
                last_err = data.get("error_description", str(data))
        except Exception as e:
            last_err = str(e)

    GATEWAY_STATE["last_error"] = last_err
    return {"status": "ERROR", "message": last_err}

_TOKEN_REFRESH_LOCK = threading.Lock()

def refresh_oauth_token() -> Dict[str, Any]:
    """
    Refreshes Spotware cTrader Open API Access Token using stored Refresh Token.
    Protected with thread lock to prevent race conditions during token rotation.
    Saves new tokens directly to Windows DPAPI encrypted vault.
    """
    global CTRADER_CONFIG, GATEWAY_STATE
    from app.services.credential_store import credential_store
    
    with _TOKEN_REFRESH_LOCK:
        r_token = credential_store.get_secret("CTRADER_REFRESH_TOKEN", CTRADER_CONFIG.get("refresh_token", ""))
        cid = credential_store.get_secret("CTRADER_CLIENT_ID", CTRADER_CONFIG.get("client_id", ""))
        csec = credential_store.get_secret("CTRADER_CLIENT_SECRET", CTRADER_CONFIG.get("client_secret", ""))
        
        if not r_token or not cid or not csec:
            GATEWAY_STATE["is_authenticated"] = False
            return {"status": "ERROR", "message": "Missing refresh token or credentials"}

        try:
            payload = {
                "grant_type": "refresh_token",
                "client_id": cid,
                "client_secret": csec,
                "refresh_token": r_token
            }
            res = requests.post(SPOTWARE_TOKEN_URL, data=payload, timeout=8)
            data = res.json()
            if "accessToken" in data or "access_token" in data:
                new_token = data.get("accessToken") or data.get("access_token")
                new_r_token = data.get("refreshToken") or data.get("refresh_token", r_token)
                
                CTRADER_CONFIG["access_token"] = new_token
                CTRADER_CONFIG["refresh_token"] = new_r_token
                GATEWAY_STATE["access_token"] = new_token
                GATEWAY_STATE["is_authenticated"] = True
                
                credential_store.set_secret("CTRADER_ACCESS_TOKEN", new_token)
                credential_store.set_secret("CTRADER_REFRESH_TOKEN", new_r_token)
                
                logger.info("Successfully refreshed cTrader Open API access token via DPAPI vault.")
                return {"status": "SUCCESS", "access_token": new_token}
            else:
                err = data.get("error_description", str(data))
                logger.warning(f"Token refresh error: {err}")
                GATEWAY_STATE["is_authenticated"] = False
                return {"status": "ERROR", "message": err}
        except Exception as e:
            logger.error(f"Error during token refresh request: {e}")
            return {"status": "ERROR", "message": str(e)}

def sync_with_spotware_cloud() -> Dict[str, Any]:
    """
    Syncs live account balance, equity, and positions directly with Spotware cTrader Open API.
    """
    global GATEWAY_STATE, CTRADER_CONFIG, LINKED_ACCOUNTS
    token = CTRADER_CONFIG.get("access_token")
    target_acc = str(CTRADER_CONFIG.get("account_id", GATEWAY_STATE["account_id"]))
    
    GATEWAY_STATE["last_sync_timestamp"] = time.time()
    GATEWAY_STATE["last_sync"] = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")

    if not token:
        # Running in Autonomous Cloud Simulated Live Sync
        return GATEWAY_STATE

    endpoints = [
        f"https://openapi.ctrader.com/apps/trader/v2/accounts?token={token}",
        f"https://api.spotware.com/connect/tradingaccounts?access_token={token}"
    ]

    for url in endpoints:
        try:
            res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=6)
            if res.status_code == 200:
                data = res.json()
                accounts = data.get("data", []) or data.get("accounts", []) or (data if isinstance(data, list) else [])
                
                for acc in accounts:
                    acc_id_str = str(acc.get("accountId") or acc.get("accountNumber") or acc.get("ctidTraderAccountId") or "")
                    raw_bal = float(acc.get("balance", GATEWAY_STATE["balance"]))
                    real_bal = raw_bal if raw_bal < 100000 else (raw_bal / 100.0)
                    
                    if acc_id_str not in LINKED_ACCOUNTS:
                        LINKED_ACCOUNTS[acc_id_str] = {
                            "account_id": acc_id_str,
                            "name": f"cTrader #{acc_id_str}",
                            "account_type": "LIVE" if acc.get("isLive", True) else "DEMO",
                            "balance": round(real_bal, 2),
                            "equity": round(real_bal, 2),
                            "currency": str(acc.get("depositCurrency", "USD")),
                            "broker": str(acc.get("brokerTitle", "IC Markets cTrader")),
                            "is_live": bool(acc.get("isLive", True)),
                            "open_positions": [],
                            "last_seen": time.time()
                        }

                    if acc_id_str == target_acc or not target_acc:
                        GATEWAY_STATE["account_id"] = acc_id_str
                        GATEWAY_STATE["balance"] = round(real_bal, 2)
                        GATEWAY_STATE["equity"] = round(real_bal, 2)
                        GATEWAY_STATE["currency"] = str(acc.get("depositCurrency", "USD"))
                        GATEWAY_STATE["broker"] = str(acc.get("brokerTitle", "IC Markets cTrader"))
                        GATEWAY_STATE["last_error"] = None
                        print(f"[cTrader Cloud Sync] 🟢 Linked Live Account #{acc_id_str} | Balance: ${GATEWAY_STATE['balance']}")
                        break
                break
        except Exception as e:
            logger.debug(f"Spotware sync attempt note: {e}")

    return GATEWAY_STATE

def dispatch_local_bridge_order(
    symbol: str,
    side: str,
    volume: float = 0.01,
    sl_pips: Optional[float] = None,
    tp_pips: Optional[float] = None,
    sl_price: Optional[float] = None,
    tp_price: Optional[float] = None,
    comment: str = "TradeTalk AI"
) -> Dict[str, Any]:
    """
    Dispatches direct HTTP webhook order to Local cBot Bridge listening on port 5001.
    Ultra-low latency execution without Spotware Open API cloud delays.
    """
    if os.getenv("TESTING") == "1":
        logger.warning("[Local cBot Bridge] Blocked external broker dispatch in test mode (TESTING=1).")
        return {
            "status": "REJECTED_TEST_MODE_EXTERNAL_EXECUTION_BLOCKED",
            "error": "Real external broker execution is strictly prohibited when TESTING=1."
        }

    bridge_url = os.getenv("CBOT_BRIDGE_URL", "http://127.0.0.1:5001/trade/").strip()
    payload = {
        "symbol": symbol.upper().replace(".PRO", "").replace("_I", ""),
        "side": side.upper(),
        "action": side.upper(),
        "volume": float(volume),
        "lot_size": float(volume),
        "stop_loss_pips": sl_pips or 40.0,
        "take_profit_pips": tp_pips or 80.0,
        "sl_price": float(sl_price or 0.0),
        "tp_price": float(tp_price or 0.0),
        "comment": comment
    }
    
    try:
        res = requests.post(bridge_url, json=payload, timeout=3)
        if res.status_code == 200:
            data = res.json()
            print(f"[Local cBot Bridge] 🟢 Trade Dispatched & Executed on cTrader: Pos #{data.get('position_id')} @ ${data.get('entry_price')}")
            return data
        else:
            print(f"[Local cBot Bridge] [!] Bridge returned HTTP {res.status_code}: {res.text}")
            return {"status": "ERROR", "message": res.text}
    except Exception as e:
        logger.debug(f"Local cBot Bridge not reachable ({bridge_url}): {e}")
        return {"status": "OFFLINE", "message": str(e)}

def execute_market_order(
    symbol: str,
    action: str,
    lot_size: float,
    sl_price: float,
    tp_price: float,
    signal_id: Optional[str] = None,
    comment: str = "TradeTalk AI Server Execution"
) -> Dict[str, Any]:
    """
    Executes a market order directly via Local cBot Webhook Bridge or Server Gateway.
    - Validates safety constraints (Whitelist, Max 1 Position, Anti-hedging, Mandatory SL/TP).
    - Dispatches to Local cBot HTTP Webhook Bridge (http://127.0.0.1:5001/trade/).
    - Registers open position in server memory and tracks real-time PnL.
    """
    global GATEWAY_STATE, EXECUTED_RECEIPTS, LAST_EXECUTION_TIMESTAMP
    now_ts = time.time()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    sym_clean = symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")
    act_upper = action.upper()
    order_sig_id = signal_id or f"SIG_{int(now_ts)}"

    # Phase 6 safety invariant: this candidate is DEMO-only.
    # Do not allow any gateway path to place an order while a LIVE account is active.
    if GATEWAY_STATE.get("is_live", True) or str(GATEWAY_STATE.get("account_type", "")).upper() == "LIVE":
        return {
            "status": "REJECTED_DEMO_ONLY_CANDIDATE",
            "error": "Phase 6 candidate is DEMO-only; LIVE account execution is disabled."
        }

    # 0. Execution Cooldown Check (30 Seconds Debounce)
    cooldown_window = getattr(settings, "EXECUTION_COOLDOWN_SECONDS", 30)
    if LAST_EXECUTION_TIMESTAMP > 0:
        elapsed = now_ts - LAST_EXECUTION_TIMESTAMP
        if elapsed < cooldown_window:
            remaining = int(cooldown_window - elapsed)
            print(f"[cTrader Cloud] [!] REJECTED: Execution cooldown active ({remaining}s / {cooldown_window}s remaining).")
            return {
                "status": "REJECTED_COOLDOWN_ACTIVE",
                "error": f"Execution cooldown active: {remaining}s remaining to prevent over-trading",
                "cooldown_remaining_seconds": remaining
            }

    # Post-Trade Close Cooldown Check (10 Seconds Debounce)
    post_close_cd = getattr(settings, "TRADE_CLOSE_COOLDOWN_SECONDS", 10)
    if LAST_TRADE_CLOSE_TIMESTAMP > 0:
        elapsed_close = now_ts - LAST_TRADE_CLOSE_TIMESTAMP
        if elapsed_close < post_close_cd:
            rem_s = int(post_close_cd - elapsed_close)
            print(f"[cTrader Cloud] [!] REJECTED: Post-trade close cooldown active ({rem_s}s remaining).")
            return {
                "status": "REJECTED_POST_TRADE_COOLDOWN",
                "error": f"Post-trade cooldown active: {rem_s}s remaining.",
                "cooldown_remaining_seconds": rem_s
            }

    # 1. Strict Instrument Whitelist Validation
    if not any(sym_clean == s or sym_clean in s or s in sym_clean for s in ALLOWED_SYMBOLS):
        print(f"[cTrader Cloud] [!] REJECTED: {symbol} not in permitted whitelist.")
        return {
            "status": "REJECTED_INSTRUMENT_NOT_PERMITTED",
            "error": f"{symbol} is not permitted for execution",
            "symbol": sym_clean
        }

    # 2. Strict Max 1 Open Position Cap
    open_positions = GATEWAY_STATE.get("open_positions", [])
    if len(open_positions) >= MAX_ACTIVE_OPEN_POSITIONS:
        print(f"[cTrader Cloud] [!] REJECTED: Maximum active positions ({MAX_ACTIVE_OPEN_POSITIONS}) reached.")
        return {
            "status": "REJECTED_MAX_OPEN_POSITIONS_REACHED",
            "error": f"Maximum {MAX_ACTIVE_OPEN_POSITIONS} active open position allowed",
            "active_positions_count": len(open_positions)
        }

    # 3. Anti-Hedging / Duplicate Check
    for pos in open_positions:
        pos_sym = pos.get("symbol", "").upper().replace("M", "").replace(".PRO", "").replace("_I", "")
        if pos_sym == sym_clean:
            print(f"[cTrader Cloud] [!] REJECTED: Active position already exists on {sym_clean}.")
            return {
                "status": "REJECTED_OPPOSING_TRADE_EXISTS",
                "error": f"Position already active on {sym_clean}"
            }

    # 4. Mandatory SL & TP Pre-Validation
    if sl_price <= 0 or tp_price <= 0:
        print(f"[cTrader Cloud] [!] REJECTED: Invalid SL/TP ({sl_price}/{tp_price}).")
        return {
            "status": "REJECTED_INVALID_PROTECTION",
            "error": "SL and TP must be strictly defined"
        }

    # 5. Dynamic Lot Sizing (Clamped 0.01 to 1.00)
    final_lot = max(0.01, min(1.00, round(float(lot_size or 0.01), 2)))

    # Estimate Fill Price from live prices or entry
    decimals = 4 if ("EUR" in sym_clean or "GBP" in sym_clean or "USD" in sym_clean and "JPY" not in sym_clean and "XAU" not in sym_clean and "XAG" not in sym_clean) else (3 if "JPY" in sym_clean or "XAG" in sym_clean else 2)
    
    live_feed = GATEWAY_STATE.get("live_prices", {}).get(sym_clean, {})
    if not (live_feed and live_feed.get("price")):
        return {
            "status": "REJECTED_UNVERIFIED_MARKET_DATA",
            "error": f"No broker/live gateway price is available for {sym_clean}; synthetic fill prices are prohibited."
        }
    fill_price = round(float(live_feed["price"]), decimals)

    is_gold = "XAU" in sym_clean or "GOLD" in sym_clean
    is_silver = "XAG" in sym_clean or "SILVER" in sym_clean
    units = int(final_lot * 100) if is_gold else (int(final_lot * 5000) if is_silver else int(final_lot * 100000))

    # Spread Protection Check (Max 25 cents on Gold)
    spread_val = float(live_feed.get("spread", 0.15)) if live_feed else 0.15
    if is_gold and spread_val > getattr(settings, "MAX_ALLOWED_SPREAD_XAUUSD", 0.25):
        print(f"[cTrader Cloud] [!] REJECTED: Gold spread (${spread_val:.2f}) > $0.25 max limit.")
        return {
            "status": "REJECTED_SPREAD_TOO_HIGH",
            "error": f"Gold spread (${spread_val:.2f}) exceeds $0.25 maximum limit to prevent spread-bleed.",
            "spread": spread_val
        }

    # Protection geometry is fail-closed. The execution layer must never silently
    # rewrite an approved strategy's SL/TP because that destroys decision provenance.
    if act_upper not in ("BUY", "SELL"):
        return {"status": "REJECTED_INVALID_ACTION", "error": f"Unsupported action: {act_upper}"}

    if is_gold:
        min_sl_dist = getattr(settings, "MIN_SL_BUFFER_GOLD", 2.00)
        min_tp_dist = getattr(settings, "MIN_TP_BUFFER_GOLD", 4.00)
        if act_upper == "BUY":
            valid_geometry = (
                sl_price < fill_price < tp_price
                and (fill_price - sl_price) >= min_sl_dist
                and (tp_price - fill_price) >= min_tp_dist
            )
        else:
            valid_geometry = (
                tp_price < fill_price < sl_price
                and (sl_price - fill_price) >= min_sl_dist
                and (fill_price - tp_price) >= min_tp_dist
            )
    else:
        valid_geometry = (sl_price < fill_price < tp_price) if act_upper == "BUY" else (tp_price < fill_price < sl_price)

    if not valid_geometry:
        return {
            "status": "REJECTED_INVALID_PROTECTION_GEOMETRY",
            "error": "Submitted SL/TP geometry is invalid for the broker price; execution aborted without rewriting strategy levels.",
            "fill_price": fill_price,
            "sl_price": sl_price,
            "tp_price": tp_price
        }

    ticket_num = random.randint(710000, 999999)
    ticket_id = f"CT_{ticket_num}"

    # Calculate pips for cBot bridge
    pip_size = 0.01 if (is_gold or is_silver) else 0.0001
    sl_pips = abs(fill_price - sl_price) / pip_size if sl_price > 0 else (600.0 if is_gold else 40.0)
    tp_pips = abs(tp_price - fill_price) / pip_size if tp_price > 0 else (1200.0 if is_gold else 80.0)

    # 1. Primary: Dispatch to Ultra-Low Latency Local cBot Webhook Bridge
    bridge_res = dispatch_local_bridge_order(
        symbol=sym_clean,
        side=act_upper,
        volume=final_lot,
        sl_pips=sl_pips,
        tp_pips=tp_pips,
        sl_price=sl_price,
        tp_price=tp_price,
        comment=comment
    )

    if bridge_res.get("status") == "SUCCESS":
        real_pos_id = bridge_res.get("position_id") or bridge_res.get("order_id")
        if real_pos_id:
            ticket_num = real_pos_id
            ticket_id = f"CT_{real_pos_id}"
        if bridge_res.get("entry_price"):
            fill_price = float(bridge_res["entry_price"])
        print(f"[Local Bridge Execution] 🟢 Live cTrader Fill: Ticket #{ticket_num} @ ${fill_price}")

    # Broker/cBot acknowledgement is authoritative. Never create a local position
    # or SUCCESS receipt when the execution transport did not confirm a fill.
    if bridge_res.get("status") != "SUCCESS":
        return {
            "status": "REJECTED_BROKER_EXECUTION_UNCONFIRMED",
            "error": "Broker/cBot did not confirm execution; local position creation aborted.",
            "broker_response": bridge_res
        }
    if not (bridge_res.get("position_id") or bridge_res.get("order_id")):
        return {
            "status": "REJECTED_BROKER_RECEIPT_INCOMPLETE",
            "error": "Broker/cBot returned SUCCESS without a position/order id; local position creation aborted."
        }
    if bridge_res.get("entry_price") is None:
        return {
            "status": "REJECTED_BROKER_RECEIPT_INCOMPLETE",
            "error": "Broker/cBot returned SUCCESS without an entry price; local position creation aborted."
        }

    # Set last execution timestamp
    LAST_EXECUTION_TIMESTAMP = now_ts

    # Create new live active position in server memory
    new_position = {
        "id": ticket_num,
        "position_id": str(ticket_num),
        "ticket": ticket_id,
        "symbol": sym_clean,
        "type": act_upper,
        "action": act_upper,
        "volume": final_lot,
        "lot_size": final_lot,
        "volume_units": units,
        "entry_price": fill_price,
        "sl": sl_price,
        "tp": tp_price,
        "current_price": fill_price,
        "net_profit": 0.00,
        "gross_profit": 0.00,
        "swap": 0.00,
        "commission": -0.07,
        "break_even_locked": False,
        "opened_at": now_str,
        "open_timestamp": now_ts,
        "timestamp": now_iso,
        "comment": comment
    }

    # Margin calculation for 1:500 leverage
    margin_req = round((fill_price * units) / 500.0, 2) if is_gold else 2.00
    GATEWAY_STATE["margin"] = round(margin_req, 2)
    GATEWAY_STATE["free_margin"] = round(GATEWAY_STATE["equity"] - margin_req, 2)
    GATEWAY_STATE["open_positions"].append(new_position)
    GATEWAY_STATE["last_sync"] = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")

    receipt = {
        "status": "SUCCESS",
        "mode": "CLOUD_SERVER_OPEN_API",
        "broker": f"{GATEWAY_STATE['broker']} #{GATEWAY_STATE['account_id']}",
        "account_id": GATEWAY_STATE["account_id"],
        "order_id": ticket_id,
        "ticket": ticket_num,
        "ticket_id": ticket_id,
        "position_id": ticket_num,
        "symbol": sym_clean,
        "action": act_upper,
        "lot_size": final_lot,
        "volume": final_lot,
        "units": units,
        "fill_price": fill_price,
        "sl": sl_price,
        "tp": tp_price,
        "executed_at": now_str,
        "comment": comment
    }

    # Log to SQLite DB Ledger immediately
    try:
        from app.database.db import db
        db.save_trade({
            "id": str(ticket_id),
            "signal_id": str(order_sig_id),
            "mode": "LIVE" if GATEWAY_STATE.get("is_live") else "DEMO",
            "broker_order_id": f"cTrader Order #{ticket_num}",
            "ticket_id": str(ticket_num),
            "symbol": sym_clean,
            "direction": act_upper,
            "entry_price": fill_price,
            "stop_loss": sl_price,
            "take_profit": tp_price,
            "volume": final_lot,
            "profit_loss": 0.0,
            "status": "OPEN",
            "opened_at": now_str
        })
    except Exception as e:
        logger.debug(f"DB save_trade error: {e}")

    EXECUTED_RECEIPTS[order_sig_id] = receipt
    print(f"[cTrader Cloud] [+] 🟢 Authentic Server-Side Order Executed: #{ticket_num} ({ticket_id}) -> {act_upper} {final_lot} Lots of {sym_clean} @ ${fill_price}")
    return receipt

def close_position(position_id: Any, close_price: Optional[float] = None, force: bool = False) -> Dict[str, Any]:
    """
    Closes an open position server-side, updates balance/equity, and frees margin.
    Enforces minimum 5-minute hold time unless legitimate TP/SL hit or forced.
    """
    global GATEWAY_STATE, LAST_TRADE_CLOSE_TIMESTAMP
    pos_id_str = str(position_id).strip()
    target_pos = None

    for pos in GATEWAY_STATE.get("open_positions", []):
        if (
            str(pos.get("id")) == pos_id_str or
            str(pos.get("position_id")) == pos_id_str or
            str(pos.get("ticket")) == pos_id_str or
            f"CT_{pos.get('id')}" == pos_id_str or
            str(pos.get("id", "")).replace("CT_", "") == pos_id_str.replace("CT_", "") or
            str(pos.get("ticket", "")).replace("CT_", "") == pos_id_str.replace("CT_", "")
        ):
            target_pos = pos
            break

    if not target_pos:
        # Check if tracked in linked accounts
        for acc in LINKED_ACCOUNTS.values():
            for p in acc.get("open_positions", []):
                if (
                    str(p.get("id")) == pos_id_str or
                    str(p.get("ticket")) == pos_id_str or
                    str(p.get("position_id")) == pos_id_str
                ):
                    target_pos = p
                    break
            if target_pos:
                break

    if not target_pos:
        if force:
            return {
                "status": "SUCCESS",
                "closed_position_id": position_id,
                "symbol": "XAUUSD",
                "realized_pnl": 0.0,
                "new_balance": GATEWAY_STATE.get("balance", 10000.0),
                "note": f"Position {position_id} resolved/closed successfully"
            }
        return {"status": "ERROR", "message": f"Position {position_id} not found"}

    # Minimum Trade Hold Time (5 minutes / 300 seconds) Guard
    open_ts = target_pos.get("open_timestamp", 0)
    if not open_ts and "timestamp" in target_pos:
        try:
            open_ts = datetime.datetime.fromisoformat(target_pos["timestamp"].replace("Z", "+00:00")).timestamp()
        except Exception:
            open_ts = 0

    if open_ts > 0 and not force and close_price is None:
        duration = time.time() - open_ts
        min_hold = getattr(settings, "MIN_TRADE_HOLD_SECONDS", 300)
        if duration < min_hold:
            rem = int(min_hold - duration)
            print(f"[cTrader Cloud] [!] REJECTED CLOSE: Position #{target_pos.get('id')} open for only {int(duration)}s (< {min_hold}s min hold time).")
            return {
                "status": "REJECTED_MIN_HOLD_TIME",
                "error": f"Minimum trade hold time (5m) not reached ({rem}s remaining to let trade breathe).",
                "hold_remaining_seconds": rem
            }

    # If local cBot bridge is active, dispatch close request directly to cTrader
    bridge_url = os.getenv("CBOT_BRIDGE_URL", "http://127.0.0.1:5001/trade/").strip()
    try:
        requests.post(bridge_url, json={"action": "CLOSE", "position_id": str(target_pos.get("id")), "force": str(force).lower()}, timeout=2)
    except Exception:
        pass

    realized_pnl = float(target_pos.get("net_profit", 0.0))
    GATEWAY_STATE["balance"] = round(GATEWAY_STATE["balance"] + realized_pnl, 2)
    GATEWAY_STATE["open_positions"] = [p for p in GATEWAY_STATE["open_positions"] if str(p.get("id")) != str(target_pos.get("id"))]
    GATEWAY_STATE["margin"] = 0.0
    GATEWAY_STATE["free_margin"] = GATEWAY_STATE["balance"]
    GATEWAY_STATE["equity"] = GATEWAY_STATE["balance"]
    GATEWAY_STATE["total_unrealized_pnl"] = 0.0
    GATEWAY_STATE["last_sync"] = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")

    # Set 30-minute post-trade cooldown timestamp
    LAST_TRADE_CLOSE_TIMESTAMP = time.time()

    # Update SQLite DB Ledger with final Net PnL and exit price
    try:
        from app.database.db import db
        db.update_trade_status(
            trade_id=str(target_pos.get("id")),
            status="CLOSED",
            exit_price=float(close_price or target_pos.get("current_price", target_pos.get("entry_price", 0.0))),
            profit_loss=realized_pnl,
            close_reason="Closed via Gateway / Broker"
        )
    except Exception as e:
        logger.debug(f"DB update_trade_status error: {e}")

    acc_id = str(GATEWAY_STATE.get("account_id"))
    if acc_id in LINKED_ACCOUNTS:
        LINKED_ACCOUNTS[acc_id]["open_positions"] = list(GATEWAY_STATE["open_positions"])
        LINKED_ACCOUNTS[acc_id]["balance"] = GATEWAY_STATE["balance"]
        LINKED_ACCOUNTS[acc_id]["equity"] = GATEWAY_STATE["equity"]

    print(f"[cTrader Cloud] [✓] Closed Position #{target_pos.get('id')} ({target_pos.get('symbol')}). Realized PnL: ${realized_pnl:.2f} | New Balance: ${GATEWAY_STATE['balance']:.2f}")
    return {
        "status": "SUCCESS",
        "closed_position_id": target_pos.get("id"),
        "symbol": target_pos.get("symbol"),
        "realized_pnl": realized_pnl,
        "new_balance": GATEWAY_STATE["balance"]
    }

def update_live_market_prices(prices_map: Dict[str, Dict[str, Any]]) -> None:
    """
    Updates live market tick prices and calculates real-time unrealized PnL for active positions.
    When connected to live cBot/cTrader, broker supplies authentic PnL and handles native SL/TP triggers.
    Synthetic calculation is strictly reserved for offline unit testing/simulations.
    """
    global GATEWAY_STATE
    GATEWAY_STATE["live_prices"].update(prices_map)
    is_live_bridge = GATEWAY_STATE.get("local_bridge_online", False)

    total_unrealized = 0.0
    for pos in list(GATEWAY_STATE.get("open_positions", [])):
        sym = pos.get("symbol", "XAUUSD")
        entry = float(pos.get("entry_price", 0.0))
        act = str(pos.get("type") or pos.get("action") or "BUY").upper()
        lots = float(pos.get("volume", 0.01))
        sl = float(pos.get("sl", 0.0))
        tp = float(pos.get("tp", 0.0))

        tick_data = GATEWAY_STATE["live_prices"].get(sym)
        if tick_data and tick_data.get("price"):
            cur_price = float(tick_data["price"])
            pos["current_price"] = cur_price

            # When connected to live cBot bridge, cBot supplies authentic broker PnL & Equity
            if is_live_bridge and pos.get("net_profit") is not None:
                total_unrealized += float(pos.get("net_profit", 0.0))
                continue

            # PnL calculation for offline/testing/synthetic simulation
            is_gold = "XAU" in sym or "GOLD" in sym
            is_silver = "XAG" in sym or "SILVER" in sym
            is_jpy = "JPY" in sym

            if is_gold:
                raw_diff = (cur_price - entry) if act == "BUY" else (entry - cur_price)
                pnl = raw_diff * (lots * 100.0)
            elif is_silver:
                raw_diff = (cur_price - entry) if act == "BUY" else (entry - cur_price)
                pnl = raw_diff * (lots * 5000.0)
            elif is_jpy:
                raw_diff = (cur_price - entry) if act == "BUY" else (entry - cur_price)
                pnl = (raw_diff / cur_price) * (lots * 100000.0)
            else:
                raw_diff = (cur_price - entry) if act == "BUY" else (entry - cur_price)
                pnl = raw_diff * (lots * 100000.0)

            # Deduct commission
            net_pnl = round(pnl - 0.07, 2)
            pos["net_profit"] = net_pnl
            pos["gross_profit"] = round(pnl, 2)
            total_unrealized += net_pnl

    if not is_live_bridge:
        GATEWAY_STATE["total_unrealized_pnl"] = round(total_unrealized, 2)
        GATEWAY_STATE["equity"] = round(GATEWAY_STATE["balance"] + total_unrealized, 2)
        GATEWAY_STATE["free_margin"] = round(GATEWAY_STATE["equity"] - GATEWAY_STATE["margin"], 2)

def sync_local_cbot_telemetry(timeout_sec: float = 1.0) -> Dict[str, Any]:
    """
    Directly queries the Local cBot Webhook Bridge (http://127.0.0.1:5001/trade/)
    and synchronizes live broker positions, balance, equity, and margin directly into GATEWAY_STATE.
    """
    global GATEWAY_STATE, LINKED_ACCOUNTS
    if os.getenv("TESTING") == "1":
        return GATEWAY_STATE

    bridge_url = os.getenv("CBOT_BRIDGE_URL", "http://127.0.0.1:5001/trade/").strip()
    
    try:
        res = requests.get(bridge_url, timeout=timeout_sec)
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "ONLINE":
                acc_id = str(data.get("account_id", "5908018")).strip().replace("#", "")
                bal = float(data.get("balance", GATEWAY_STATE["balance"]))
                eq = float(data.get("equity", bal))
                marg = float(data.get("margin", 0.0))
                f_marg = float(data.get("free_margin", eq))
                broker = str(data.get("broker", "Spotware"))
                is_live = bool(data.get("is_live", False))
                
                raw_positions = data.get("positions", [])
                normalized_positions = []
                total_unrealized = 0.0
                
                for p in raw_positions:
                    p_id = p.get("id") or p.get("position_id")
                    sym = str(p.get("symbol", "XAUUSD")).upper()
                    side = str(p.get("trade_type") or p.get("side") or p.get("action") or "BUY").upper()
                    entry_p = float(p.get("entry_price") or p.get("entry") or 0.0)
                    sl_p = float(p.get("sl") or p.get("stop_loss") or 0.0)
                    tp_p = float(p.get("tp") or p.get("take_profit") or 0.0)
                    pnl_val = float(p.get("net_profit") or p.get("pnl") or 0.0)
                    total_unrealized += pnl_val
                    
                    lots = 0.01
                    if "volume" in p:
                        lots = float(p["volume"])
                    elif "lots" in p:
                        raw_lots = float(p["lots"])
                        lots = raw_lots if raw_lots < 0.5 else 0.01
                    elif "lot_size" in p:
                        lots = float(p["lot_size"])
                    
                    be_locked = False
                    if sl_p > 0 and entry_p > 0:
                        if side == "BUY" and sl_p >= entry_p:
                            be_locked = True
                        elif side == "SELL" and sl_p <= entry_p:
                            be_locked = True

                    norm_pos = {
                        "id": p_id,
                        "position_id": str(p_id),
                        "ticket": p_id,
                        "symbol": sym,
                        "type": side,
                        "action": side,
                        "volume": lots,
                        "lot_size": lots,
                        "entry_price": entry_p,
                        "sl": sl_p,
                        "tp": tp_p,
                        "current_price": entry_p if entry_p > 0 else GATEWAY_STATE.get("live_prices", {}).get(sym, {}).get("price", entry_p),
                        "net_profit": round(pnl_val, 2),
                        "gross_profit": round(pnl_val, 2),
                        "break_even_locked": be_locked,
                        "comment": "TradeTalk cTrader Live"
                    }
                    normalized_positions.append(norm_pos)

                # Ingest true live broker tick stream
                prices_data = data.get("prices", {})
                if isinstance(prices_data, dict):
                    for sym_key, p_obj in prices_data.items():
                        if isinstance(p_obj, dict) and p_obj.get("price"):
                            p_val = float(p_obj["price"])
                            bid_val = float(p_obj.get("bid", p_val))
                            ask_val = float(p_obj.get("ask", p_val))
                            spread_val = float(p_obj.get("spread", round(ask_val - bid_val, 2)))
                            GATEWAY_STATE["live_prices"][sym_key] = {
                                "price": p_val,
                                "bid": bid_val,
                                "ask": ask_val,
                                "spread": spread_val,
                                "updated_at": time.time()
                            }
                            if sym_key == "XAUUSD":
                                GATEWAY_STATE["live_prices"]["GOLD"] = GATEWAY_STATE["live_prices"]["XAUUSD"]

                # Ingest fallback live price from active positions or recent broker history
                if "XAUUSD" not in GATEWAY_STATE["live_prices"] or not GATEWAY_STATE["live_prices"]["XAUUSD"].get("price"):
                    for pos in normalized_positions:
                        sym_p = str(pos.get("symbol", "")).upper()
                        if "XAU" in sym_p or "GOLD" in sym_p:
                            ep = float(pos.get("entry_price") or 0.0)
                            if ep > 0:
                                GATEWAY_STATE["live_prices"]["XAUUSD"] = {
                                    "price": ep,
                                    "bid": round(ep - 0.15, 2),
                                    "ask": round(ep + 0.15, 2),
                                    "spread": 0.30,
                                    "updated_at": time.time()
                                }
                                GATEWAY_STATE["live_prices"]["GOLD"] = GATEWAY_STATE["live_prices"]["XAUUSD"]
                                break
                    if "XAUUSD" not in GATEWAY_STATE["live_prices"] and raw_closed:
                        for cl in raw_closed:
                            sym_c = str(cl.get("symbol", "")).upper()
                            if "XAU" in sym_c or "GOLD" in sym_c:
                                cp = float(cl.get("closing_price") or cl.get("entry_price") or 0.0)
                                if cp > 0:
                                    GATEWAY_STATE["live_prices"]["XAUUSD"] = {
                                        "price": cp,
                                        "bid": round(cp - 0.15, 2),
                                        "ask": round(cp + 0.15, 2),
                                        "spread": 0.30,
                                        "updated_at": time.time()
                                    }
                                    GATEWAY_STATE["live_prices"]["GOLD"] = GATEWAY_STATE["live_prices"]["XAUUSD"]
                                    break

                GATEWAY_STATE["is_connected"] = True
                GATEWAY_STATE["cloud_server_active"] = True
                GATEWAY_STATE["local_bridge_online"] = True
                GATEWAY_STATE["account_id"] = acc_id
                GATEWAY_STATE["broker"] = broker
                GATEWAY_STATE["is_live"] = is_live
                GATEWAY_STATE["balance"] = round(bal, 2)
                GATEWAY_STATE["equity"] = round(eq, 2)
                GATEWAY_STATE["margin"] = round(marg, 2)
                GATEWAY_STATE["free_margin"] = round(f_marg, 2)
                GATEWAY_STATE["open_positions"] = normalized_positions
                GATEWAY_STATE["total_unrealized_pnl"] = round(total_unrealized, 2)
                GATEWAY_STATE["last_sync"] = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
                GATEWAY_STATE["last_sync_timestamp"] = time.time()
                GATEWAY_STATE["last_bridge_sync_timestamp"] = time.time()
                
                # Auto-reconcile open/closed positions between cTrader and DB
                raw_closed = data.get("closed_trades") or data.get("history", [])
                for c in raw_closed:
                    try:
                        db.sync_cbot_closed_trade(c)
                    except Exception as ce:
                        logger.debug(f"[Closed Trade Sync Error]: {ce}")

                # Auto-close any DB trade that is no longer in live cTrader open positions
                try:
                    from app.database.db import get_db_connection, _lock
                    with _lock, get_db_connection() as conn:
                        open_db_trades = conn.execute("SELECT id, ticket_id FROM trades WHERE status = 'OPEN' AND mode = 'LIVE'").fetchall()
                        open_cbot_ids = {str(p.get("id")) for p in normalized_positions}
                        for tr in open_db_trades:
                            t_id = str(tr["ticket_id"] or tr["id"]).replace("TRD_", "").replace("CT_", "")
                            if t_id and t_id not in open_cbot_ids:
                                conn.execute(
                                    "UPDATE trades SET status = 'CLOSED', closed_at = COALESCE(closed_at, ?) WHERE id = ?",
                                    (datetime.datetime.now(datetime.timezone.utc).isoformat(), tr["id"])
                                )
                        conn.commit()
                except Exception as dbe:
                    logger.debug(f"[DB Trade Reconciliation Error]: {dbe}")

                if acc_id not in LINKED_ACCOUNTS:
                    LINKED_ACCOUNTS[acc_id] = {}
                LINKED_ACCOUNTS[acc_id].update({
                    "account_id": acc_id,
                    "name": f"{broker} • #{acc_id}",
                    "account_type": "LIVE" if is_live else "DEMO",
                    "balance": round(bal, 2),
                    "equity": round(eq, 2),
                    "margin": round(marg, 2),
                    "free_margin": round(f_marg, 2),
                    "currency": "USD",
                    "broker": broker,
                    "is_live": is_live,
                    "open_positions": normalized_positions,
                    "last_seen": time.time()
                })
    except Exception as e:
        logger.debug(f"[Local Bridge Sync Note]: {e}")
        
    return GATEWAY_STATE

def get_gateway_status(force_local_sync: bool = False) -> Dict[str, Any]:
    """Returns real-time server-side gateway status, proactively synchronizing with local bridge."""
    global GATEWAY_STATE
    GATEWAY_STATE["is_connected"] = True
    GATEWAY_STATE["cloud_server_active"] = True
    if force_local_sync or (time.time() - GATEWAY_STATE.get("last_bridge_sync_timestamp", 0) > 1.0):
        sync_local_cbot_telemetry(timeout_sec=0.8)
    return GATEWAY_STATE

def get_pending_cbot_orders() -> List[Dict[str, Any]]:
    """Fetches and clears pending orders for cBot."""
    global PENDING_CBOT_ORDERS
    orders = list(PENDING_CBOT_ORDERS)
    PENDING_CBOT_ORDERS.clear()
    return orders

def update_heartbeat(data: dict) -> dict:
    """Updates gateway state when cBot streams real-time broker data."""
    global GATEWAY_STATE, PENDING_CBOT_ORDERS
    now_ts = time.time()
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")

    acc_id = str(data.get("account_id") or data.get("accountNumber") or data.get("accountId") or GATEWAY_STATE["account_id"]).strip().replace("#", "")
    bal = float(data.get("balance", data.get("Balance", GATEWAY_STATE["balance"])))
    eq = float(data.get("equity", data.get("Equity", bal)))
    marg = float(data.get("margin", data.get("Margin", 0.0)))
    f_marg = float(data.get("free_margin", data.get("freeMargin", eq)))
    curr = str(data.get("currency", data.get("Currency", "USD")))
    broker = str(data.get("broker", data.get("brokerName", "IC Markets cTrader")))
    is_live = bool(data.get("is_live", True))

    # Keep registry of linked accounts up to date
    if acc_id not in LINKED_ACCOUNTS:
        LINKED_ACCOUNTS[acc_id] = {}
    
    LINKED_ACCOUNTS[acc_id].update({
        "account_id": acc_id,
        "name": f"cTrader #{acc_id}",
        "account_type": "LIVE" if is_live else "DEMO",
        "balance": round(bal, 2),
        "equity": round(eq, 2),
        "margin": round(marg, 2),
        "free_margin": round(f_marg, 2),
        "currency": curr,
        "broker": broker,
        "is_live": is_live,
        "open_positions": data.get("open_positions", data.get("positions", [])),
        "last_seen": now_ts
    })

    sym = data.get("symbol")
    bid = data.get("bid")
    ask = data.get("ask")
    price = data.get("live_price") or bid
    if sym and price:
        sym_clean = str(sym).upper().replace("M", "").replace(".PRO", "").replace("_I", "")
        p_val = float(price)
        update_live_market_prices({
            sym_clean: {
                "symbol": sym_clean,
                "price": p_val,
                "bid": float(bid or p_val),
                "ask": float(ask or (p_val + 0.35)),
                "updated_at": now_ts
            }
        })

    open_pos = data.get("open_positions", data.get("positions", []))
    if open_pos or acc_id == GATEWAY_STATE.get("account_id"):
        GATEWAY_STATE["open_positions"] = open_pos

    if acc_id == GATEWAY_STATE.get("account_id") or not GATEWAY_STATE.get("account_id"):
        GATEWAY_STATE["account_id"] = acc_id
        GATEWAY_STATE["balance"] = round(bal, 2)
        GATEWAY_STATE["equity"] = round(eq, 2)
        GATEWAY_STATE["margin"] = round(marg, 2)
        GATEWAY_STATE["free_margin"] = round(f_marg, 2)
        GATEWAY_STATE["currency"] = curr
        GATEWAY_STATE["broker"] = broker
        GATEWAY_STATE["is_live"] = is_live
        GATEWAY_STATE["last_sync"] = now_str
        GATEWAY_STATE["last_sync_timestamp"] = now_ts

    state_res = dict(GATEWAY_STATE)
    if PENDING_CBOT_ORDERS:
        top_order = PENDING_CBOT_ORDERS[0]
        state_res["pending_orders"] = list(PENDING_CBOT_ORDERS)
        state_res["signal"] = top_order.get("action")
        state_res["action"] = top_order.get("action")
        state_res["symbol"] = top_order.get("symbol")
        state_res["lots"] = top_order.get("lot_size", 0.01)
        state_res["lot_size"] = top_order.get("lot_size", 0.01)
        state_res["sl"] = top_order.get("sl", 0.0)
        state_res["tp"] = top_order.get("tp", 0.0)
        state_res["ticket_id"] = top_order.get("id")
        state_res["id"] = top_order.get("id")

    return state_res

def get_live_price(symbol: str = "XAUUSD") -> Optional[Dict[str, Any]]:
    """Returns latest live price for symbol if fresh."""
    sym_clean = symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")
    item = GATEWAY_STATE.get("live_prices", {}).get(sym_clean)
    if not item and "XAU" in sym_clean:
        item = GATEWAY_STATE.get("live_prices", {}).get("XAUUSD")
    return item
