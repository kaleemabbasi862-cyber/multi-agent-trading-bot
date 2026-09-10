import os
import json
import tempfile

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")
_IN_MEMORY_SETTINGS = None

# Full Whitelist: Metals & Major FX Pairs
ALL_SUPPORTED_PAIRS = [
    {"symbol": "XAUUSD", "name": "Gold / USD", "category": "Metals", "icon": "fa-coins", "color": "amber", "default_price": 4400.0, "pip_size": 0.01},
    {"symbol": "XAGUSD", "name": "Silver / USD", "category": "Metals", "icon": "fa-gem", "color": "slate", "default_price": 32.50, "pip_size": 0.001},
    {"symbol": "EURUSD", "name": "EUR / USD", "category": "Forex", "icon": "fa-euro-sign", "color": "blue", "default_price": 1.0850, "pip_size": 0.0001},
    {"symbol": "GBPUSD", "name": "GBP / USD", "category": "Forex", "icon": "fa-sterling-sign", "color": "emerald", "default_price": 1.2950, "pip_size": 0.0001},
    {"symbol": "USDJPY", "name": "USD / JPY", "category": "Forex", "icon": "fa-yen-sign", "color": "rose", "default_price": 153.50, "pip_size": 0.01},
    {"symbol": "AUDUSD", "name": "AUD / USD", "category": "Forex", "icon": "fa-dollar-sign", "color": "teal", "default_price": 0.6580, "pip_size": 0.0001},
    {"symbol": "USDCHF", "name": "USD / CHF", "category": "Forex", "icon": "fa-franc-sign", "color": "purple", "default_price": 0.8850, "pip_size": 0.0001},
]

DEFAULT_SETTINGS = {
    "active_symbol": "XAUUSD",
    "active_pairs": ["XAUUSD"],
    "active_lot_size": 0.01,
    "fixed_lot_size": 0.01,
    "auto_trade_enabled": False,
    "scanner_active": True,
    "max_risk_percent": 1.0,
    "min_confidence_threshold": 75.0,
    "min_consensus_agents": 4,
    "trading_mode": "DEMO",
    "account_id": "",
    "environment_mode": "MULTI_ASSET_QUANT"
}

def is_test_env() -> bool:
    """Check if execution is running within a test framework."""
    return os.environ.get("TESTING") == "1" or "pytest" in sys.modules if "sys" in globals() else os.environ.get("TESTING") == "1"

def load_settings() -> dict:
    """Load settings from persistent JSON file or return defaults (isolated in-memory during tests)."""
    global _IN_MEMORY_SETTINGS
    if os.environ.get("TESTING") == "1":
        if _IN_MEMORY_SETTINGS is not None:
            return dict(_IN_MEMORY_SETTINGS)

    all_syms = [p["symbol"] for p in ALL_SUPPORTED_PAIRS]
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = {**DEFAULT_SETTINGS, **json.load(f)}
                
                # Normalize active_symbol
                act_sym = str(data.get("active_symbol", "XAUUSD")).upper()
                if act_sym not in all_syms:
                    act_sym = "XAUUSD"
                data["active_symbol"] = act_sym

                # Normalize lot size
                lot = float(data.get("active_lot_size") or data.get("fixed_lot_size") or 0.01)
                data["active_lot_size"] = max(0.01, min(1.00, round(lot, 2)))
                data["fixed_lot_size"] = data["active_lot_size"]

                # Normalize confidence threshold (50% to 90%)
                thresh = float(data.get("min_confidence_threshold", 75.0))
                data["min_confidence_threshold"] = max(50.0, min(90.0, round(thresh, 1)))
                data["min_consensus_agents"] = int(data.get("min_consensus_agents", 4))

                if "active_pairs" in data and isinstance(data["active_pairs"], list) and len(data["active_pairs"]) > 0:
                    valid = [s.upper() for s in data["active_pairs"] if s.upper() in all_syms]
                    data["active_pairs"] = valid if valid else [act_sym]
                else:
                    data["active_pairs"] = [act_sym]

                if os.environ.get("TESTING") == "1":
                    _IN_MEMORY_SETTINGS = dict(data)
                return data
        except Exception as e:
            print(f"[SettingsManager] Error loading settings: {e}")

    default_data = dict(DEFAULT_SETTINGS)
    if os.environ.get("TESTING") != "1":
        save_settings(default_data)
    else:
        _IN_MEMORY_SETTINGS = dict(default_data)
    return default_data

def save_settings(settings: dict) -> dict:
    """Save settings dictionary to persistent JSON file or in-memory when testing."""
    global _IN_MEMORY_SETTINGS
    if os.environ.get("TESTING") == "1":
        _IN_MEMORY_SETTINGS = dict(settings)
        return settings
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(SETTINGS_FILE), delete=False) as f:
            temp_path = f.name
            json.dump(settings, f, indent=2)
        os.replace(temp_path, SETTINGS_FILE)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
    return settings

def get_active_symbol() -> str:
    """Returns currently selected active symbol."""
    return load_settings().get("active_symbol", "XAUUSD")

def set_active_symbol(symbol: str) -> str:
    """Updates active symbol."""
    all_syms = [p["symbol"] for p in ALL_SUPPORTED_PAIRS]
    sym_clean = symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")
    if sym_clean in all_syms:
        s = load_settings()
        s["active_symbol"] = sym_clean
        if sym_clean not in s.get("active_pairs", []):
            s["active_pairs"] = [sym_clean]
        save_settings(s)
        return sym_clean
    return get_active_symbol()

def get_active_lot_size() -> float:
    """Returns currently configured lot size."""
    return float(load_settings().get("active_lot_size", 0.01))

def set_active_lot_size(lot_size: float) -> float:
    """Updates lot size within [0.01, 1.00]."""
    clamped = max(0.01, min(1.00, round(float(lot_size), 2)))
    s = load_settings()
    s["active_lot_size"] = clamped
    s["fixed_lot_size"] = clamped
    save_settings(s)
    return clamped

def get_active_pairs() -> list:
    """Returns list of currently active pair symbols."""
    return load_settings().get("active_pairs", ["XAUUSD"])

def get_min_confidence_threshold() -> float:
    """Returns the current quantitative conviction threshold for execution."""
    return float(load_settings().get("min_confidence_threshold", 75.0))

def set_min_confidence_threshold(threshold: float) -> float:
    """Updates quantitative conviction threshold within [60.0, 90.0]."""
    clamped = max(60.0, min(90.0, round(float(threshold), 1)))
    s = load_settings()
    s["min_confidence_threshold"] = clamped
    save_settings(s)
    return clamped

def is_pair_whitelisted(symbol: str) -> bool:
    """Checks if a given symbol is in the supported pair whitelist."""
    all_syms = [p["symbol"] for p in ALL_SUPPORTED_PAIRS]
    sym_clean = symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")
    return any(sym_clean == s or sym_clean in s or s in sym_clean for s in all_syms)

def get_active_account_id() -> str:
    """Returns currently selected cTrader Account ID."""
    return str(load_settings().get("account_id", "")).strip()

def set_active_account_id(account_id: str) -> str:
    """Updates selected cTrader Account ID."""
    clean_id = str(account_id).strip().replace("#", "")
    s = load_settings()
    s["account_id"] = clean_id
    save_settings(s)
    return clean_id


