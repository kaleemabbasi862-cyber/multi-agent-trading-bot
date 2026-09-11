"""
Consolidation/Reversal conflict behavioral regression tests.

Pins the authorized exception: STRUCTURE_REVERSAL must not be blocked
solely by the consolidation veto when the setup classifier has already
produced that actionable setup. All other gates remain enforced.

Tests use mock-controlled engine inputs to isolate gate behavior.
"""
import os
import unittest
from unittest.mock import patch, MagicMock

os.environ["TESTING"] = "1"

from app.services.pretrade_intelligence_engine import pretrade_intelligence_engine


def _base_indicators(adx_value=25.0, rsi_value=45.0):
    return {"rsi": rsi_value, "atr": 1.5, "adx": {"adx": adx_value}}


def _make_setup(setup_type, direction="SELL", confidence=80.0, is_actionable=True):
    return {
        "setup_type": setup_type,
        "direction": direction,
        "confidence": confidence,
        "reasons": [f"Test: {setup_type}"],
        "is_actionable": is_actionable,
    }


def _make_quality(score=80.0, passed=True):
    return {
        "score": score,
        "threshold": 75.0,
        "passed": passed,
        "verdict": "TRADE_APPROVED" if passed else "NO_TRADE_QUALITY_BELOW_THRESHOLD",
        "breakdown": {},
    }


def _smc(structure="RANGE", latest_event="NONE"):
    return {
        "trend": "NEUTRAL",
        "structure": structure,
        "latest_event": latest_event,
        "unmitigated_obs": [],
        "unmitigated_fvgs": [],
        "recent_sweeps": [],
        "dealing_range": {"zone": "PREMIUM", "location_pct": 75.0, "range_high": 2750.0, "range_low": 2700.0, "equilibrium": 2725.0},
    }


_MOD = "app.services.pretrade_intelligence_engine"


def _run_scan(smc_result, setup_result, quality_result, indicators,
              adx_minimum=20.0, disallow_consolidation=True, news_events=None):
    """Patch all engine dependencies, run scan_market, return result."""
    smc_mock = MagicMock()
    smc_mock.analyze_market_structure.return_value = smc_result

    mtf_mock = MagicMock()
    mtf_mock.evaluate_multi_timeframe.return_value = {"consensus_trend": "BEARISH", "confluence_score": 70.0}

    ind_mock = MagicMock()
    ind_mock.calculate_rsi.return_value = indicators.get("rsi", 45.0)
    ind_mock.calculate_atr.return_value = indicators.get("atr", 1.5)
    ind_mock.calculate_adx.return_value = indicators.get("adx", {"adx": 25.0})

    session_mock = MagicMock()
    session_mock.get_current_session_info.return_value = {"primary_session": "LONDON", "utc_time": "2026-09-11T12:00:00Z", "is_high_volume_window": True}
    session_mock.calculate_session_levels.return_value = {}

    setup_mock = MagicMock()
    setup_mock.classify_setup.return_value = setup_result

    quality_mock = MagicMock()
    quality_mock.score_trade_setup.return_value = quality_result

    config_mock = MagicMock()
    config_mock.get.side_effect = lambda name: {
        "REGIME_ADX_MINIMUM": adx_minimum,
        "DISALLOW_CONSOLIDATION_ENTRIES": disallow_consolidation,
    }.get(name, 0)

    tick = {"bid": 2730.0, "ask": 2731.0, "spread": 1.0}
    candles = {"M15": [{"open": 2730, "high": 2735, "low": 2728, "close": 2732, "timestamp": "2026-09-11T12:00:00Z"}]}

    with patch(f"{_MOD}.smart_money_engine", smc_mock), \
         patch(f"{_MOD}.multi_timeframe_engine", mtf_mock), \
         patch(f"{_MOD}.technical_indicators", ind_mock), \
         patch(f"{_MOD}.session_engine", session_mock), \
         patch(f"{_MOD}.setup_classifier", setup_mock), \
         patch(f"{_MOD}.trade_quality_scorer", quality_mock), \
         patch(f"{_MOD}.trading_config", config_mock):
        return pretrade_intelligence_engine.scan_market("XAUUSD", tick, candles, news_events=news_events)


class TestConsolidationReversalConflict(unittest.TestCase):

    # --- 1. RANGE + NO_VALID_SETUP -> BLOCKED ---
    def test_01_range_no_valid_setup_blocked(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE"),
            setup_result=_make_setup("NO_VALID_SETUP", direction="FLAT", confidence=35.0, is_actionable=False),
            quality_result=_make_quality(score=0.0, passed=False),
            indicators=_base_indicators(),
        )
        self.assertFalse(res["trade_allowed"], "RANGE + NO_VALID_SETUP must be BLOCKED")
        self.assertIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])

    # --- 2. RANGE + TREND_CONTINUATION -> BLOCKED ---
    def test_02_range_trend_continuation_blocked(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE"),
            setup_result=_make_setup("TREND_CONTINUATION", direction="SELL", confidence=75.0, is_actionable=True),
            quality_result=_make_quality(score=80.0, passed=True),
            indicators=_base_indicators(),
        )
        self.assertFalse(res["trade_allowed"], "RANGE + TREND_CONTINUATION must be BLOCKED by consolidation")
        self.assertIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])

    # --- 3. RANGE + OB_REACTION -> BLOCKED ---
    def test_03_range_ob_reaction_blocked(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE"),
            setup_result=_make_setup("OB_REACTION", direction="SELL", confidence=82.0, is_actionable=True),
            quality_result=_make_quality(score=80.0, passed=True),
            indicators=_base_indicators(),
        )
        self.assertFalse(res["trade_allowed"], "RANGE + OB_REACTION must be BLOCKED by consolidation")
        self.assertIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])

    # --- 4. RANGE + STRUCTURE_REVERSAL -> NOT blocked by consolidation ---
    def test_04_range_structure_reversal_passes_consolidation_gate(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE", latest_event="BEARISH_CHOCH"),
            setup_result=_make_setup("STRUCTURE_REVERSAL", direction="SELL", confidence=80.0, is_actionable=True),
            quality_result=_make_quality(score=85.0, passed=True),
            indicators=_base_indicators(adx_value=25.0),
        )
        self.assertTrue(res["trade_allowed"], "RANGE + STRUCTURE_REVERSAL must pass consolidation gate")
        self.assertNotIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])
        self.assertIn("High-probability", res["decision_reason"])

    # --- 5. CONSOLIDATION + STRUCTURE_REVERSAL -> same exception ---
    def test_05_consolidation_structure_reversal_passes(self):
        res = _run_scan(
            smc_result=_smc(structure="CONSOLIDATION", latest_event="BEARISH_CHOCH"),
            setup_result=_make_setup("STRUCTURE_REVERSAL", direction="SELL", confidence=80.0, is_actionable=True),
            quality_result=_make_quality(score=85.0, passed=True),
            indicators=_base_indicators(adx_value=25.0),
        )
        self.assertTrue(res["trade_allowed"], "CONSOLIDATION + STRUCTURE_REVERSAL must pass consolidation gate")
        self.assertNotIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])

    # --- 6. CONSOLIDATING + STRUCTURE_REVERSAL -> same exception ---
    def test_06_consolidating_structure_reversal_passes(self):
        res = _run_scan(
            smc_result=_smc(structure="CONSOLIDATING", latest_event="BULLISH_CHOCH"),
            setup_result=_make_setup("STRUCTURE_REVERSAL", direction="BUY", confidence=80.0, is_actionable=True),
            quality_result=_make_quality(score=85.0, passed=True),
            indicators=_base_indicators(adx_value=25.0),
        )
        self.assertTrue(res["trade_allowed"], "CONSOLIDATING + STRUCTURE_REVERSAL must pass consolidation gate")
        self.assertNotIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])

    # --- 7. STRUCTURE_REVERSAL + ADX below minimum -> BLOCKED ---
    def test_07_structure_reversal_low_adx_blocked(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE", latest_event="BEARISH_CHOCH"),
            setup_result=_make_setup("STRUCTURE_REVERSAL", direction="SELL", confidence=80.0, is_actionable=True),
            quality_result=_make_quality(score=85.0, passed=True),
            indicators=_base_indicators(adx_value=15.0),
        )
        self.assertFalse(res["trade_allowed"], "STRUCTURE_REVERSAL with low ADX must be BLOCKED")
        self.assertIn("NO_TRADE_REGIME_ADX", res["decision_reason"])
        self.assertNotIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])

    # --- 8. STRUCTURE_REVERSAL + Quality <75 -> BLOCKED ---
    def test_08_structure_reversal_low_quality_blocked(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE", latest_event="BEARISH_CHOCH"),
            setup_result=_make_setup("STRUCTURE_REVERSAL", direction="SELL", confidence=80.0, is_actionable=True),
            quality_result=_make_quality(score=60.0, passed=False),
            indicators=_base_indicators(adx_value=25.0),
        )
        self.assertFalse(res["trade_allowed"], "STRUCTURE_REVERSAL with quality <75 must be BLOCKED")
        self.assertIn("Quality score", res["decision_reason"])
        self.assertNotIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])

    # --- 9. STRUCTURE_REVERSAL + non-actionable -> BLOCKED ---
    def test_09_structure_reversal_non_actionable_blocked(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE", latest_event="BEARISH_CHOCH"),
            setup_result=_make_setup("STRUCTURE_REVERSAL", direction="SELL", confidence=50.0, is_actionable=False),
            quality_result=_make_quality(score=85.0, passed=True),
            indicators=_base_indicators(adx_value=25.0),
        )
        self.assertFalse(res["trade_allowed"], "STRUCTURE_REVERSAL non-actionable must be BLOCKED")
        self.assertIn("No actionable setup", res["decision_reason"])
        self.assertNotIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])

    # --- 10. STRUCTURE_REVERSAL + excessive XAU spread -> BLOCKED ---
    def test_10_structure_reversal_excessive_spread_blocked(self):
        smc_result = _smc(structure="RANGE", latest_event="BEARISH_CHOCH")
        setup_result = _make_setup("STRUCTURE_REVERSAL", direction="SELL", confidence=80.0, is_actionable=True)
        quality_result = _make_quality(score=85.0, passed=True)
        indicators = _base_indicators(adx_value=25.0)

        config_mock = MagicMock()
        config_mock.get.side_effect = lambda name: {
            "REGIME_ADX_MINIMUM": 25.0,
            "DISALLOW_CONSOLIDATION_ENTRIES": True,
        }.get(name, 0)

        wide_tick = {"bid": 2730.0, "ask": 2736.0, "spread": 6.0}
        candles = {"M15": [{"open": 2730, "high": 2735, "low": 2728, "close": 2732, "timestamp": "2026-09-11T12:00:00Z"}]}

        smc_mock = MagicMock()
        smc_mock.analyze_market_structure.return_value = smc_result
        mtf_mock = MagicMock()
        mtf_mock.evaluate_multi_timeframe.return_value = {"consensus_trend": "BEARISH", "confluence_score": 70.0}
        ind_mock = MagicMock()
        ind_mock.calculate_rsi.return_value = indicators["rsi"]
        ind_mock.calculate_atr.return_value = indicators["atr"]
        ind_mock.calculate_adx.return_value = indicators["adx"]
        session_mock = MagicMock()
        session_mock.get_current_session_info.return_value = {"primary_session": "LONDON", "utc_time": "2026-09-11T12:00:00Z", "is_high_volume_window": True}
        session_mock.calculate_session_levels.return_value = {}
        setup_mock = MagicMock()
        setup_mock.classify_setup.return_value = setup_result
        quality_mock = MagicMock()
        quality_mock.score_trade_setup.return_value = quality_result

        with patch(f"{_MOD}.smart_money_engine", smc_mock), \
             patch(f"{_MOD}.multi_timeframe_engine", mtf_mock), \
             patch(f"{_MOD}.technical_indicators", ind_mock), \
             patch(f"{_MOD}.session_engine", session_mock), \
             patch(f"{_MOD}.setup_classifier", setup_mock), \
             patch(f"{_MOD}.trade_quality_scorer", quality_mock), \
             patch(f"{_MOD}.trading_config", config_mock):
            res = pretrade_intelligence_engine.scan_market("XAUUSD", wide_tick, candles)

        self.assertFalse(res["trade_allowed"], "STRUCTURE_REVERSAL with excessive spread must be BLOCKED")
        self.assertIn("spread", res["decision_reason"].lower())

    # --- 11. STRUCTURE_REVERSAL + news blackout -> BLOCKED ---
    def test_11_structure_reversal_news_blackout_blocked(self):
        news = [{"impact": "HIGH", "is_blackout": True, "title": "NFP Release"}]
        res = _run_scan(
            smc_result=_smc(structure="RANGE", latest_event="BEARISH_CHOCH"),
            setup_result=_make_setup("STRUCTURE_REVERSAL", direction="SELL", confidence=80.0, is_actionable=True),
            quality_result=_make_quality(score=85.0, passed=True),
            indicators=_base_indicators(adx_value=25.0),
            news_events=news,
        )
        self.assertFalse(res["trade_allowed"], "STRUCTURE_REVERSAL + news blackout must be BLOCKED")
        self.assertIn("news", res["decision_reason"].lower())

    # --- 12. Missing/invalid feed -> FAIL CLOSED ---
    def test_12_missing_feed_fail_closed(self):
        res = pretrade_intelligence_engine.scan_market(
            "XAUUSD", {"bid": 0.0, "ask": 0.0, "spread": 0.0}, {}
        )
        self.assertFalse(res["trade_allowed"])
        self.assertEqual(res["status"], "FAIL_CLOSED_NO_MARKET_DATA")

    # --- 13. RANGE + STRUCTURE_REVERSAL + low quality -> passes consolidation, blocked by quality ---
    def test_13_structure_reversal_passes_consolidation_but_blocked_by_quality(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE", latest_event="BEARISH_CHOCH"),
            setup_result=_make_setup("STRUCTURE_REVERSAL", direction="SELL", confidence=80.0, is_actionable=True),
            quality_result=_make_quality(score=55.0, passed=False),
            indicators=_base_indicators(adx_value=25.0),
        )
        self.assertFalse(res["trade_allowed"], "Must be blocked by quality score")
        self.assertNotIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])
        self.assertIn("Quality score", res["decision_reason"])

    # --- 14. RANGE + STRUCTURE_REVERSAL + low ADX -> passes consolidation, blocked by ADX ---
    def test_14_structure_reversal_passes_consolidation_but_blocked_by_adx(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE", latest_event="BEARISH_CHOCH"),
            setup_result=_make_setup("STRUCTURE_REVERSAL", direction="SELL", confidence=80.0, is_actionable=True),
            quality_result=_make_quality(score=85.0, passed=True),
            indicators=_base_indicators(adx_value=12.0),
        )
        self.assertFalse(res["trade_allowed"], "Must be blocked by ADX minimum")
        self.assertIn("NO_TRADE_REGIME_ADX", res["decision_reason"])
        self.assertNotIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])

    # --- 15. Disallow consolidation disabled -> all setups pass consolidation gate ---
    def test_15_disallow_consolidation_disabled_all_passes(self):
        res = _run_scan(
            smc_result=_smc(structure="RANGE"),
            setup_result=_make_setup("TREND_CONTINUATION", direction="SELL", confidence=75.0, is_actionable=True),
            quality_result=_make_quality(score=80.0, passed=True),
            indicators=_base_indicators(adx_value=25.0),
            disallow_consolidation=False,
        )
        self.assertTrue(res["trade_allowed"], "With disallow_consolidation=False, consolidation gate is skipped")
        self.assertNotIn("NO_TRADE_CONSOLIDATION", res["decision_reason"])


if __name__ == "__main__":
    unittest.main()
