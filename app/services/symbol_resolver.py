import os
import re
import logging
from typing import Dict, Any, Optional, List
from app.database.db import get_db_connection

logger = logging.getLogger("TradeTalk.SymbolResolver")

# Standard Contract Specifications Defaults
DEFAULT_SYMBOL_SPECS = {
    "XAUUSD": {"symbol_id": 1, "name": "XAUUSD", "base": "XAU", "quote": "USD", "digits": 2, "pip_size": 0.01, "lot_size": 100.0, "min_vol": 0.01, "max_vol": 100.0, "vol_step": 0.01},
    "XAGUSD": {"symbol_id": 2, "name": "XAGUSD", "base": "XAG", "quote": "USD", "digits": 3, "pip_size": 0.001, "lot_size": 5000.0, "min_vol": 0.01, "max_vol": 50.0, "vol_step": 0.01},
    "EURUSD": {"symbol_id": 3, "name": "EURUSD", "base": "EUR", "quote": "USD", "digits": 5, "pip_size": 0.0001, "lot_size": 100000.0, "min_vol": 0.01, "max_vol": 100.0, "vol_step": 0.01},
    "GBPUSD": {"symbol_id": 4, "name": "GBPUSD", "base": "GBP", "quote": "USD", "digits": 5, "pip_size": 0.0001, "lot_size": 100000.0, "min_vol": 0.01, "max_vol": 100.0, "vol_step": 0.01},
    "USDJPY": {"symbol_id": 5, "name": "USDJPY", "base": "USD", "quote": "JPY", "digits": 3, "pip_size": 0.01, "lot_size": 100000.0, "min_vol": 0.01, "max_vol": 100.0, "vol_step": 0.01},
    "AUDUSD": {"symbol_id": 6, "name": "AUDUSD", "base": "AUD", "quote": "USD", "digits": 5, "pip_size": 0.0001, "lot_size": 100000.0, "min_vol": 0.01, "max_vol": 100.0, "vol_step": 0.01},
    "USDCHF": {"symbol_id": 7, "name": "USDCHF", "base": "USD", "quote": "CHF", "digits": 5, "pip_size": 0.0001, "lot_size": 100000.0, "min_vol": 0.01, "max_vol": 100.0, "vol_step": 0.01},
    "BTCUSD": {"symbol_id": 8, "name": "BTCUSD", "base": "BTC", "quote": "USD", "digits": 2, "pip_size": 0.01, "lot_size": 1.0, "min_vol": 0.01, "max_vol": 10.0, "vol_step": 0.01}
}

class SymbolResolver:
    """
    Resolves broker-specific symbol names (e.g. 'GOLD', 'XAUUSD.c', 'XAUUSDm', 'XAUUSD.pro')
    to standard internal instruments and retrieves broker contract specifications.
    """
    def __init__(self):
        self._broker_symbol_cache: Dict[str, Dict[str, Any]] = {}
        self._load_from_db()

    def _load_from_db(self):
        try:
            with get_db_connection() as conn:
                rows = conn.execute("SELECT * FROM symbols").fetchall()
                for r in rows:
                    item = dict(r)
                    self._broker_symbol_cache[item["name"].upper()] = item
        except Exception as e:
            logger.debug(f"Note loading symbols from DB: {e}")

    def normalize_symbol(self, raw_symbol: str) -> str:
        """Converts any broker-specific variation into canonical standard symbol."""
        if not raw_symbol:
            return "XAUUSD"
        s = raw_symbol.upper().strip()
        
        # Gold aliases
        if "XAU" in s or "GOLD" in s:
            return "XAUUSD"
        # Silver aliases
        if "XAG" in s or "SILVER" in s:
            return "XAGUSD"
        # Bitcoin aliases
        if "BTC" in s:
            return "BTCUSD"
            
        # Strip common broker suffixes: .c, .pro, m, _i, .ecn, .r
        clean = re.sub(r'(\.C|\.PRO|M|_I|\.ECN|\.R|\.SB)$', '', s)
        clean = clean.replace('/', '')
        return clean

    def register_broker_symbols(self, symbols_list: List[Dict[str, Any]]):
        """Stores symbols discovered directly from cTrader Open API."""
        now = "2026-09-08T19:00:00Z"
        with get_db_connection() as conn:
            for s in symbols_list:
                sym_id = s.get("symbol_id", 0)
                name = s.get("name", "").upper()
                norm = self.normalize_symbol(name)
                defaults = DEFAULT_SYMBOL_SPECS.get(norm, DEFAULT_SYMBOL_SPECS["XAUUSD"])
                
                digits = s.get("digits", defaults["digits"])
                pip_size = 10 ** (-digits) if digits > 2 else 0.01
                
                spec = {
                    "symbol_id": sym_id,
                    "name": name,
                    "base_asset": defaults["base"],
                    "quote_asset": defaults["quote"],
                    "digits": digits,
                    "pip_size": pip_size,
                    "min_volume": defaults["min_vol"],
                    "max_volume": defaults["max_vol"],
                    "volume_step": defaults["vol_step"],
                    "lot_size": defaults["lot_size"],
                    "is_trading_enabled": 1,
                    "updated_at": now
                }
                
                self._broker_symbol_cache[name] = spec
                self._broker_symbol_cache[norm] = spec
                
                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO symbols
                        (symbol_id, name, base_asset, quote_asset, digits, pip_size, min_volume, max_volume, volume_step, lot_size, is_trading_enabled, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sym_id, name, spec["base_asset"], spec["quote_asset"],
                            spec["digits"], spec["pip_size"], spec["min_volume"], spec["max_volume"],
                            spec["volume_step"], spec["lot_size"], spec["is_trading_enabled"], now
                        )
                    )
                except Exception as e:
                    logger.debug(f"DB symbol write note: {e}")
            conn.commit()
            logger.info(f"Registered {len(symbols_list)} broker symbols into symbol cache and database.")

    def get_symbol_spec(self, symbol: str) -> Dict[str, Any]:
        """Returns the full contract specifications for a symbol."""
        sym_clean = symbol.upper().strip()
        if sym_clean in self._broker_symbol_cache:
            return self._broker_symbol_cache[sym_clean]
        
        norm = self.normalize_symbol(sym_clean)
        if norm in self._broker_symbol_cache:
            return self._broker_symbol_cache[norm]
            
        defaults = DEFAULT_SYMBOL_SPECS.get(norm, DEFAULT_SYMBOL_SPECS["XAUUSD"])
        return {
            "symbol_id": defaults["symbol_id"],
            "name": norm,
            "base_asset": defaults["base"],
            "quote_asset": defaults["quote"],
            "digits": defaults["digits"],
            "pip_size": defaults["pip_size"],
            "min_volume": defaults["min_vol"],
            "max_volume": defaults["max_vol"],
            "volume_step": defaults["vol_step"],
            "lot_size": defaults["lot_size"],
            "is_trading_enabled": 1
        }

    def get_contract_spec(self, symbol: str) -> Dict[str, Any]:
        """Alias for get_symbol_spec for contract specification queries."""
        return self.get_symbol_spec(symbol)

    def convert_lots_to_units(self, symbol: str, lots: float) -> int:

        """Converts lot size to broker contract volume units."""
        spec = self.get_symbol_spec(symbol)
        lot_size = spec.get("lot_size", 100.0)
        return int(round(lots * lot_size))

    def convert_units_to_lots(self, symbol: str, units: int) -> float:
        """Converts broker contract volume units to standard lot size."""
        spec = self.get_symbol_spec(symbol)
        lot_size = spec.get("lot_size", 100.0)
        return round(units / (lot_size + 1e-6), 2)


symbol_resolver = SymbolResolver()
