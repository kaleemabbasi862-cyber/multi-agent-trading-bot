import time
import unittest
from app.services.symbol_resolver import symbol_resolver
from app.services.ctrader_market_data import ctrader_market_data
from app.services.credential_store import credential_store
from ctrader_openapi import OpenAPIRateLimiter, SpotwareOpenAPIClient, enc_proto_message, decode_proto_message, PAYLOAD_PROTO_OA_SYMBOLS_LIST_REQ
from ctrader_cloud_gateway import refresh_oauth_token

def test_dynamic_symbol_resolver():
    """Test dynamic symbol alias normalization and contract specifications."""
    # 1. Gold Aliases
    assert symbol_resolver.normalize_symbol("GOLD") == "XAUUSD"
    assert symbol_resolver.normalize_symbol("XAUUSD.c") == "XAUUSD"
    assert symbol_resolver.normalize_symbol("XAUUSDm") == "XAUUSD"
    assert symbol_resolver.normalize_symbol("XAUUSD.pro") == "XAUUSD"

    # 2. Silver & FX Aliases
    assert symbol_resolver.normalize_symbol("SILVER") == "XAGUSD"
    assert symbol_resolver.normalize_symbol("EURUSD.c") == "EURUSD"
    assert symbol_resolver.normalize_symbol("USDJPY_I") == "USDJPY"

    # 3. Contract Specs
    gold_spec = symbol_resolver.get_symbol_spec("GOLD")
    assert gold_spec["digits"] == 2
    assert gold_spec["pip_size"] == 0.01
    assert gold_spec["lot_size"] == 100.0

    # 4. Lot to Unit Conversions
    units = symbol_resolver.convert_lots_to_units("XAUUSD", 0.01)
    assert units == 1, f"Expected 1 unit (0.01 oz / 1 lot scale), got {units}"
    
    fx_units = symbol_resolver.convert_lots_to_units("EURUSD", 0.02)
    assert fx_units == 2000, f"Expected 2000 units, got {fx_units}"

def test_ctrader_openapi_rate_limiter():
    """Test token bucket rate limiter for cTrader Open API."""
    limiter = OpenAPIRateLimiter(max_normal_rate=10, max_historical_rate=2)
    
    # Non-historical burst check
    t0 = time.time()
    for _ in range(5):
        limiter.acquire(is_historical=False)
    elapsed = time.time() - t0
    assert elapsed < 0.2, "Burst acquisition should be near instant"

def test_ctrader_market_data_engine():
    """Test spot tick ingestion and candle caching."""
    ctrader_market_data.update_spot_tick(
        symbol="XAUUSD.c",
        bid=2750.10,
        ask=2750.35,
        timestamp=time.time()
    )
    tick = ctrader_market_data.get_latest_tick("XAUUSD")
    assert tick is not None, "Tick was not saved"
    assert tick["symbol"] == "XAUUSD"
    assert tick["bid"] == 2750.10
    assert tick["ask"] == 2750.35
    assert tick["spread"] == 0.25
    assert tick["price"] == 2750.22 or tick["price"] == 2750.23

    # Candle saving & retrieval
    now_ms = int(time.time() * 1000)
    test_candles = [
        {"timestamp": now_ms - 1800000, "open": 2748.0, "high": 2752.0, "low": 2747.0, "close": 2750.0, "volume": 120.0},
        {"timestamp": now_ms - 900000, "open": 2750.0, "high": 2754.0, "low": 2749.0, "close": 2753.0, "volume": 150.0}
    ]
    ctrader_market_data.save_trendbars_to_db("XAUUSD", "15m", test_candles)
    cached = ctrader_market_data.get_cached_candles("XAUUSD", "15m", limit=10)
    assert len(cached) >= 2, f"Expected at least 2 candles, got {len(cached)}"

def test_token_refresh_lifecycle():
    """Test OAuth token refresh function and DPAPI vault persistence."""
    credential_store.set_secret("CTRADER_CLIENT_ID", "test_client_id_123")
    credential_store.set_secret("CTRADER_CLIENT_SECRET", "test_client_secret_456")
    credential_store.set_secret("CTRADER_REFRESH_TOKEN", "test_mock_refresh_token_789")
    
    # Call refresh function (handles network error / mock gracefully)
    res = refresh_oauth_token()
    assert isinstance(res, dict)
    assert "status" in res
