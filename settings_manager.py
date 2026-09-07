import os
import json

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")

# Exclusively EURUSD and GBPUSD (Metals/Crypto disabled per Zero-Failure Capital Preserver rules)
ALL_SUPPORTED_PAIRS = [
    {"symbol": "EURUSD", "name": "EUR / USD", "category": "Forex", "icon": "fa-euro-sign", "color": "blue"},
    {"symbol": "GBPUSD", "name": "GBP / USD", "category": "Forex", "icon": "fa-sterling-sign", "color": "indigo"},
]

DEFAULT_SETTINGS = {
    "active_pairs": ["EURUSD", "GBPUSD"],
    "auto_trade_enabled": True,
    "scanner_active": True,
    "max_risk_percent": 1.0,
    "environment_mode": "DEMO_FIRST"
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
    """Returns list of currently active pair symbols (restricted to EURUSD, GBPUSD)."""
    settings = load_settings()
    pairs = settings.get("active_pairs", [])
    valid = [s for s in pairs if s in ["EURUSD", "GBPUSD"]]
    if not valid:
        valid = ["EURUSD", "GBPUSD"]
    return valid

def set_active_pairs(pairs: list) -> list:
    """Replaces the active pair whitelist with the given list and persists."""
    settings = load_settings()
    all_syms = [p["symbol"] for p in ALL_SUPPORTED_PAIRS]
    valid_pairs = [s.upper() for s in pairs if s.upper() in all_syms]
    if not valid_pairs:
        valid_pairs = ["EURUSD", "GBPUSD"]
    settings["active_pairs"] = valid_pairs
    save_settings(settings)
    return valid_pairs

def toggle_pair(symbol: str) -> list:
    """Toggles a single pair on/off in the whitelist and persists."""
    sym = symbol.upper().strip()
    all_syms = [p["symbol"] for p in ALL_SUPPORTED_PAIRS]
    if sym not in all_syms:
        return get_active_pairs()

    settings = load_settings()
    active = list(settings.get("active_pairs", []))
    if sym in active:
        if len(active) > 1: # Maintain at least 1 active pair
            active.remove(sym)
    else:
        active.append(sym)
    settings["active_pairs"] = active
    save_settings(settings)
    return active

def is_pair_whitelisted(symbol: str) -> bool:
    """Checks if a given symbol is currently active in the whitelist."""
    sym_clean = symbol.upper().replace("M", "").replace(".PRO", "").replace("_I", "")
    active = get_active_pairs()
    return sym_clean in active or any(s in sym_clean for s in active)
