import os
import json

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")

# Strict Whitelist: Gold (XAUUSD) ONLY
ALL_SUPPORTED_PAIRS = [
    {"symbol": "XAUUSD", "name": "Gold / USD", "category": "Metals", "icon": "fa-coins", "color": "amber"},
]

DEFAULT_SETTINGS = {
    "active_pairs": ["XAUUSD"],
    "auto_trade_enabled": True,
    "scanner_active": True,
    "max_risk_percent": 1.0,
    "min_confidence_threshold": 85,
    "fixed_lot_size": 0.01,
    "environment_mode": "GOLD_SNIPER"
}

def load_settings() -> dict:
    """Load settings from persistent JSON file or return defaults."""
    all_syms = [p["symbol"] for p in ALL_SUPPORTED_PAIRS]
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "active_pairs" in data and isinstance(data["active_pairs"], list) and len(data["active_pairs"]) > 0:
                    valid = [s.upper() for s in data["active_pairs"] if s.upper() in all_syms]
                    data["active_pairs"] = valid if valid else list(all_syms)
                    return data
        except Exception as e:
            print(f"[SettingsManager] Error loading settings: {e}")

    default_data = dict(DEFAULT_SETTINGS)
    save_settings(default_data)
    return default_data

def save_settings(settings: dict) -> dict:
    """Save settings dictionary to persistent JSON file."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"[SettingsManager] Error saving settings: {e}")
    return settings

def get_active_pairs() -> list:
    """Returns list of currently active pair symbols (restricted to XAUUSD)."""
    return ["XAUUSD"]

def set_active_pairs(pairs: list) -> list:
    """Enforces XAUUSD as the only active pair."""
    settings = load_settings()
    settings["active_pairs"] = ["XAUUSD"]
    save_settings(settings)
    return ["XAUUSD"]

def toggle_pair(symbol: str) -> list:
    """Enforces XAUUSD as the only active pair."""
    return ["XAUUSD"]

def is_pair_whitelisted(symbol: str) -> bool:
    """Checks if a given symbol is XAUUSD / Gold."""
    sym_clean = symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")
    return "XAU" in sym_clean or "GOLD" in sym_clean
