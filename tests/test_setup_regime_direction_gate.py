from app.services.setup_classifier import SetupClassifier


def base_smc(**overrides):
    data = {
        "trend": "BULLISH",
        "structure": "BULLISH_TREND",
        "latest_event": "BULLISH_CHOCH",
        "unmitigated_obs": [],
        "unmitigated_fvgs": [],
        "recent_sweeps": [],
        "dealing_range": {"zone": "PREMIUM"},
    }
    data.update(overrides)
    return data


def test_bull_regime_blocks_bearish_liquidity_reversal():
    smc = base_smc(recent_sweeps=[{"type": "BEARISH_LIQUIDITY_SWEEP", "description": "old high swept"}])
    result = SetupClassifier.classify_setup({"consensus_trend": "BULLISH"}, smc, 4312.0)
    assert result["regime"] == "BULL_TREND"
    assert result["allowed_direction"] == "BUY"
    assert result["direction"] != "SELL"


def test_bear_regime_blocks_bullish_liquidity_reversal():
    smc = base_smc(trend="BEARISH", structure="BEARISH_TREND", latest_event="BEARISH_CHOCH",
                   dealing_range={"zone": "DISCOUNT"}, recent_sweeps=[{"type": "BULLISH_LIQUIDITY_SWEEP", "description": "old low swept"}])
    result = SetupClassifier.classify_setup({"consensus_trend": "BEARISH"}, smc, 4280.0)
    assert result["regime"] == "BEAR_TREND"
    assert result["allowed_direction"] == "SELL"
    assert result["direction"] != "BUY"


def test_conflicting_mtf_is_no_trade():
    smc = base_smc(dealing_range={"zone": "DISCOUNT"}, recent_sweeps=[{"type": "BULLISH_LIQUIDITY_SWEEP", "description": "low swept"}])
    result = SetupClassifier.classify_setup({"consensus_trend": "NO_TRADE_CONFLICT"}, smc, 4280.0)
    assert result["regime"] == "NO_TRADE"
    assert result["direction"] == "FLAT"
    assert result["is_actionable"] is False
