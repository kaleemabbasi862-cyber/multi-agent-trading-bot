from app.engine.smart_money_engine import smart_money_engine
from app.engine.multi_timeframe_engine import multi_timeframe_engine
from app.services.session_engine import session_engine
from app.services.setup_classifier import setup_classifier
from app.services.trade_quality_scorer import trade_quality_scorer
from app.services.pretrade_intelligence_engine import pretrade_intelligence_engine

def generate_sample_candles(count=30, start_price=2700.0, trend="BULLISH"):
    candles = []
    p = start_price
    for i in range(count):
        if trend == "BULLISH":
            o = p
            c = p + 2.0
            h = c + 1.0
            l = o - 0.5
            p = c
        elif trend == "BEARISH":
            o = p
            c = p - 2.0
            h = o + 0.5
            l = c - 1.0
            p = c
        else:
            o = p
            c = p + (1.0 if i % 2 == 0 else -1.0)
            h = max(o, c) + 0.5
            l = min(o, c) - 0.5
            p = c
        candles.append({
            "timestamp": f"2026-09-09T{10 + (i // 4):02d}:{(i % 4) * 15:02d}:00Z",
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": 100.0
        })
    return candles

def test_smart_money_engine_swing_points():
    candles = generate_sample_candles(30, start_price=2700.0, trend="BULLISH")
    res = smart_money_engine.detect_swing_points(candles, lookback=2)
    assert "swing_highs" in res
    assert "swing_lows" in res
    assert "structure" in res

def test_smart_money_engine_fvg_detection():
    # Construct 3 candles with bullish FVG (C3 low > C1 high)
    candles = [
        {"open": 2700.0, "high": 2702.0, "low": 2699.0, "close": 2701.0, "timestamp": "2026-09-09T10:00:00Z"},
        {"open": 2701.0, "high": 2715.0, "low": 2701.0, "close": 2714.0, "timestamp": "2026-09-09T10:15:00Z"}, # Big displacement
        {"open": 2714.0, "high": 2720.0, "low": 2708.0, "close": 2718.0, "timestamp": "2026-09-09T10:30:00Z"}, # Low (2708) > C1 High (2702)
    ]
    fvgs = smart_money_engine.detect_fair_value_gaps(candles, min_gap_pips=1.0)
    assert len(fvgs) >= 1
    assert fvgs[0]["type"] == "BULLISH_FVG"
    assert fvgs[0]["top"] == 2708.0
    assert fvgs[0]["bottom"] == 2702.0
    assert fvgs[0]["status"] == "UNMITIGATED"

def test_smart_money_engine_order_blocks():
    # Down candle followed by aggressive expansion
    candles = [
        {"open": 2710.0, "high": 2712.0, "low": 2705.0, "close": 2706.0, "timestamp": "2026-09-09T10:00:00Z"},
        {"open": 2706.0, "high": 2725.0, "low": 2705.0, "close": 2724.0, "timestamp": "2026-09-09T10:15:00Z"},
        {"open": 2724.0, "high": 2735.0, "low": 2723.0, "close": 2734.0, "timestamp": "2026-09-09T10:30:00Z"},
        {"open": 2734.0, "high": 2740.0, "low": 2733.0, "close": 2738.0, "timestamp": "2026-09-09T10:45:00Z"},
    ]
    obs = smart_money_engine.detect_order_blocks(candles)
    assert len(obs) >= 1
    assert obs[0]["type"] == "BULLISH_ORDER_BLOCK"
    assert obs[0]["status"] in ("UNMITIGATED", "TESTED")

def test_smart_money_engine_premium_discount():
    candles = generate_sample_candles(20, start_price=2700.0, trend="BULLISH")
    pd_range = smart_money_engine.calculate_premium_discount(candles)
    assert "range_high" in pd_range
    assert "range_low" in pd_range
    assert "equilibrium" in pd_range
    assert "zone" in pd_range
    assert pd_range["range_high"] > pd_range["range_low"]

def test_session_engine():
    info = session_engine.get_current_session_info()
    assert "primary_session" in info
    assert "utc_time" in info
    assert "is_high_volume_window" in info

def test_setup_classifier():
    mtf_data = {"consensus_trend": "BULLISH", "confluence_score": 85.0}
    smc_data = {
        "trend": "BULLISH",
        "structure": "BULLISH_TREND",
        "latest_event": "BULLISH_BOS",
        "unmitigated_obs": [],
        "unmitigated_fvgs": [],
        "recent_sweeps": [{
            "type": "BULLISH_LIQUIDITY_SWEEP",
            "description": "Swept sell-side liquidity at $2700.00",
            "strength": 90
        }],
        "dealing_range": {"zone": "DISCOUNT", "location_pct": 35.0}
    }
    setup = setup_classifier.classify_setup(mtf_data, smc_data, current_price=2705.0)
    assert setup["setup_type"] == "LIQUIDITY_SWEEP_REVERSAL"
    assert setup["direction"] == "BUY"
    assert setup["confidence"] >= 75.0

def test_trade_quality_scorer():
    setup = {"setup_type": "LIQUIDITY_SWEEP_REVERSAL", "direction": "BUY"}
    mtf_data = {"consensus_trend": "BULLISH"}
    smc_data = {
        "structure": "BULLISH_TREND",
        "latest_event": "BULLISH_BOS",
        "dealing_range": {"zone": "DEEP_DISCOUNT", "location_pct": 20.0}
    }
    indicators = {"rsi": 45.0, "adx": {"adx": 28.0}}
    score_res = trade_quality_scorer.score_trade_setup(
        setup=setup,
        mtf_data=mtf_data,
        smc_data=smc_data,
        indicators=indicators,
        live_spread_pips=1.2,
        target_rr_ratio=2.2
    )
    assert score_res["score"] >= 75.0
    assert score_res["passed"] is True
    assert score_res["verdict"] == "TRADE_APPROVED"
    assert "breakdown" in score_res

def test_pretrade_intelligence_fail_closed_on_missing_feed():
    res = pretrade_intelligence_engine.scan_market(
        symbol="XAUUSD",
        live_tick={"bid": 0.0, "ask": 0.0, "spread": 0.0},
        timeframe_candles={}
    )
    assert res["trade_allowed"] is False
    assert res["status"] == "FAIL_CLOSED_NO_MARKET_DATA"
