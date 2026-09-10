from app.engine.technical_indicators import technical_indicators
from app.engine.smart_money_engine import smart_money_engine
from app.engine.multi_timeframe_engine import multi_timeframe_engine

def generate_mock_candles(start_price: float = 2700.0, count: int = 40, trend: str = "UP"):
    candles = []
    p = start_price
    for i in range(count):
        delta = 1.5 if trend == "UP" else (-1.5 if trend == "DOWN" else (0.5 if i % 2 == 0 else -0.5))
        o = p
        h = o + 2.0
        l = o - 1.0
        c = o + delta
        p = c
        candles.append({
            "timestamp": i * 900000,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": 100 + (i * 5)
        })
    return candles

def test_technical_indicators_suite():
    """Test full mathematical technical indicator calculations."""
    up_candles = generate_mock_candles(2700.0, count=40, trend="UP")
    closes = [c["close"] for c in up_candles]

    # 1. RSI
    rsi = technical_indicators.calculate_rsi(closes, 14)
    assert 50.0 <= rsi <= 100.0, f"Expected bullish RSI >= 50, got {rsi}"

    # 2. MACD
    macd = technical_indicators.calculate_macd(closes)
    assert "macd" in macd and "signal" in macd and "histogram" in macd

    # 3. Bollinger Bands
    bb = technical_indicators.calculate_bollinger_bands(closes, 20)
    assert bb["upper"] >= bb["middle"] >= bb["lower"], f"Invalid BB order: {bb}"

    # 4. ATR
    atr = technical_indicators.calculate_atr(up_candles, 14)
    assert atr > 0, f"ATR must be positive, got {atr}"

    # 5. Stochastic
    stoch = technical_indicators.calculate_stochastic(up_candles, 14, 3)
    assert 0.0 <= stoch["k"] <= 100.0 and 0.0 <= stoch["d"] <= 100.0

    # 6. ADX
    adx = technical_indicators.calculate_adx(up_candles, 14)
    assert "adx" in adx and "plus_di" in adx and "minus_di" in adx

    # 7. VWAP
    vwap = technical_indicators.calculate_vwap(up_candles)
    assert vwap > 0, f"VWAP must be positive, got {vwap}"

    # 8. Pivot Points
    pivots = technical_indicators.calculate_pivot_points(2760.0, 2740.0, 2755.0)
    assert pivots["r1"] > pivots["pivot"] > pivots["s1"]

def test_smart_money_concepts_suite():
    """Test Fair Value Gaps, Order Blocks, Liquidity Sweeps, and Premium/Discount."""
    candles = [
        {"open": 2700.0, "high": 2705.0, "low": 2698.0, "close": 2704.0, "volume": 100}, # C1
        {"open": 2704.0, "high": 2720.0, "low": 2703.0, "close": 2718.0, "volume": 300}, # C2 Displacement
        {"open": 2718.0, "high": 2725.0, "low": 2710.0, "close": 2722.0, "volume": 150}, # C3 (Low 2710 > C1 High 2705 -> Bullish FVG)
    ]
    
    # 1. Fair Value Gap Check
    fvgs = smart_money_engine.detect_fair_value_gaps(candles, min_gap_pips=1.0)
    assert len(fvgs) > 0, "Failed to detect Bullish FVG"
    assert fvgs[0]["type"] == "BULLISH_FVG"
    assert fvgs[0]["bottom"] == 2705.0
    assert fvgs[0]["top"] == 2710.0

    # 2. Premium / Discount Check
    up_candles = generate_mock_candles(2700.0, count=30, trend="UP")
    pd_result = smart_money_engine.calculate_premium_discount(up_candles)
    assert pd_result["equilibrium"] > 0
    assert "zone" in pd_result

    # 3. Liquidity Sweep Check
    sweep_candles = [
        {"open": 2750.0, "high": 2755.0, "low": 2745.0, "close": 2750.0},
        {"open": 2750.0, "high": 2753.0, "low": 2746.0, "close": 2751.0},
        {"open": 2751.0, "high": 2754.0, "low": 2747.0, "close": 2752.0},
        {"open": 2752.0, "high": 2755.0, "low": 2748.0, "close": 2753.0},
        {"open": 2753.0, "high": 2756.0, "low": 2749.0, "close": 2754.0},
        {"open": 2754.0, "high": 2760.0, "low": 2740.0, "close": 2758.0} # Swept min low (2745) and closed at 2758
    ]
    sweeps = smart_money_engine.detect_liquidity_sweeps(sweep_candles, lookback=4)
    assert len(sweeps) > 0, "Failed to detect bullish liquidity sweep"
    assert sweeps[0]["type"] == "BULLISH_LIQUIDITY_SWEEP"

def test_multi_timeframe_confluence_engine():
    """Test Multi-Timeframe Confluence evaluation across D1, H4, H1, M15, M5."""
    bull_candles = generate_mock_candles(2700.0, count=40, trend="UP")
    bear_candles = generate_mock_candles(2700.0, count=40, trend="DOWN")

    # 1. Aligned Bullish Context
    tf_data = {
        "D1": bull_candles,
        "H4": bull_candles,
        "H1": bull_candles,
        "M15": bull_candles,
        "M5": bull_candles
    }
    mtf_res = multi_timeframe_engine.evaluate_multi_timeframe(tf_data)
    assert mtf_res["consensus_trend"] == "BULLISH"
    assert mtf_res["confluence_score"] >= 70.0
    assert mtf_res["is_aligned"] is True

    # 2. Conflicting Context -> NO_TRADE_CONFLICT
    conflict_data = {
        "D1": bull_candles,
        "H4": bull_candles,
        "H1": bear_candles,
        "M15": bear_candles,
        "M5": bear_candles
    }
    conflict_res = multi_timeframe_engine.evaluate_multi_timeframe(conflict_data)
    assert conflict_res["consensus_trend"] in ("NO_TRADE_CONFLICT", "NEUTRAL") or conflict_res["is_aligned"] is False
