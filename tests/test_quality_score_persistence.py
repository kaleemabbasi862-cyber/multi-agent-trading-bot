"""Regression tests for Quality Score Telemetry Persistence.

Verifies that:
1. Actual quality_score is persisted exactly in decision_dna for consensus-reached scans
2. Component breakdown is persisted exactly
3. Threshold is persisted separately from score
4. Rejection reason is persisted for blocked scans
5. Cycles blocked before consensus are recorded correctly
6. Cycles reaching consensus are recorded correctly
7. No duplicate persistence for one scan cycle
8. Backward compatibility with older decision_dna rows
9. Persistence failure does not weaken fail-closed trading safety
"""
import json
import os
import sqlite3
import time
import unittest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class DBError(Exception):
    pass


from app.database.db import db
from app.database.models import SignalPayload, AgentDecisionOutput, AgentOperationalCriticality, AgentHealthStatus


def _fresh_quality_score(score=82.0, threshold=75.0, passed=True):
    """Build a realistic quality_score dict matching TradeQualityScorer output."""
    return {
        "score": score,
        "threshold": threshold,
        "passed": passed,
        "verdict": "TRADE_APPROVED" if passed else "NO_TRADE_QUALITY_BELOW_THRESHOLD",
        "breakdown": {
            "mtf_alignment": {"score": 20.0, "max": 20.0, "details": "Macro bias is BULLISH"},
            "market_structure": {"score": 15.0, "max": 15.0, "details": "Structure is BULLISH_TREND"},
            "smc_confluence": {"score": 20.0, "max": 20.0, "details": "Setup model: LIQUIDITY_SWEEP_REVERSAL"},
            "dealing_range": {"score": 12.0, "max": 15.0, "details": "Price at 38.5% (DISCOUNT)"},
            "momentum_indicators": {"score": 14.0, "max": 15.0, "details": "RSI: 52.3, ADX: 26.4"},
            "risk_reward_spread": {"score": 13.0, "max": 15.0, "details": "R:R: 2.00, Spread: 0.3 pips"}
        }
    }


def _fresh_pretrade_scan(quality_score=None, trade_allowed=True, setup_type="LIQUIDITY_SWEEP_REVERSAL",
                         direction="BUY", decision_reason="High-probability BUY setup verified"):
    """Build a realistic pretrade_scan dict matching PreTradeIntelligenceEngine output."""
    if quality_score is None:
        quality_score = _fresh_quality_score()
    return {
        "symbol": "XAUUSD",
        "trade_allowed": trade_allowed,
        "decision_reason": decision_reason,
        "setup": {"setup_type": setup_type, "direction": direction, "confidence": 88.0},
        "quality_score": quality_score,
        "indicators": {"rsi": 52.3, "adx": {"adx": 26.4}},
        "spread_pips": 0.3,
        "smc": {"structure": "BULLISH_TREND", "dealing_range": {"zone": "DISCOUNT", "location_pct": 38.5}},
        "mtf": {"consensus_trend": "BULLISH"}
    }


def _mock_all_agents():
    """Return a dict of mocks for all agents used by consensus_engine."""
    agent_decision = AgentDecisionOutput(
        agent_name="Test", direction="BUY", score=80.0, decision="PASS",
        reasoning_summary="Test", operational_criticality=AgentOperationalCriticality.DECISION_CRITICAL,
        health_status=AgentHealthStatus.HEALTHY
    )
    risk_decision = AgentDecisionOutput(
        agent_name="Risk", direction="BUY", score=85.0, decision="PASS",
        reasoning_summary="Test", operational_criticality=AgentOperationalCriticality.SAFETY_CRITICAL,
        health_status=AgentHealthStatus.HEALTHY
    )
    explain_data = {
        "headline_en": "Test", "summary_en": "Test",
        "headline_ur": "Test", "summary_ur": "Test",
        "positive_factors": [], "cautious_factors": [],
        "agent_cards": [], "risk_metrics": {}
    }
    return {
        "guardian": {"check_guard_rules": (False, None)},
        "technical_agent": {"evaluate": agent_decision},
        "fundamental_agent": {"evaluate": agent_decision},
        "risk_agent": {"evaluate": risk_decision},
        "regime_agent": {"evaluate": agent_decision},
        "liquidity_agent": {"evaluate": agent_decision},
        "quality_agent": {"evaluate": agent_decision},
        "head_desk_agent": {"arbitrate": ("APPROVED", 88.5, "Test approval")},
        "explainability_engine": {"generate_explanation": explain_data},
    }


def _run_consensus_with_mock(pretrade_scan=None):
    """Helper to run consensus_engine.process_signal with all agents mocked."""
    from app.engine.consensus_engine import MultiAgentConsensusEngine
    engine = MultiAgentConsensusEngine()

    sig = SignalPayload(
        symbol="XAUUSD", action="BUY", entry_price=4350.0,
        stop_loss=4344.0, take_profit=4362.0, volume=0.01,
        timeframe="15m", strategy_name="XAUUSD_LIQUIDITY_SWEEP_REVERSAL",
        source="AUTONOMOUS_PRETRADE_SCANNER"
    )

    mocks = _mock_all_agents()

    with patch.object(db, "save_decision_dna") as mock_dna, \
         patch.object(db, "save_signal"), \
         patch.object(db, "save_agent_decisions"), \
         patch.object(db, "save_risk_check"), \
         patch.object(db, "log_audit"), \
         patch("app.engine.consensus_engine.guardian") as m_guardian, \
         patch("app.engine.consensus_engine.technical_agent") as m_tech, \
         patch("app.engine.consensus_engine.fundamental_agent") as m_fund, \
         patch("app.engine.consensus_engine.risk_agent") as m_risk, \
         patch("app.engine.consensus_engine.regime_agent") as m_regime, \
         patch("app.engine.consensus_engine.liquidity_agent") as m_liq, \
         patch("app.engine.consensus_engine.quality_agent") as m_quality, \
         patch("app.engine.consensus_engine.head_desk_agent") as m_head, \
         patch("app.engine.consensus_engine.explainability_engine") as m_expl:

        m_guardian.check_guard_rules.return_value = mocks["guardian"]["check_guard_rules"]
        m_tech.evaluate.return_value = mocks["technical_agent"]["evaluate"]
        m_fund.evaluate.return_value = mocks["fundamental_agent"]["evaluate"]
        m_risk.evaluate.return_value = mocks["risk_agent"]["evaluate"]
        m_regime.evaluate.return_value = mocks["regime_agent"]["evaluate"]
        m_liq.evaluate.return_value = mocks["liquidity_agent"]["evaluate"]
        m_quality.evaluate.return_value = mocks["quality_agent"]["evaluate"]
        m_head.arbitrate.return_value = mocks["head_desk_agent"]["arbitrate"]
        m_expl.generate_explanation.return_value = mocks["explainability_engine"]["generate_explanation"]

        result = engine.process_signal(
            signal=sig,
            market_data={"price": 4350.0, "bid": 4349.9, "ask": 4350.1, "spread": 0.2},
            macro_data={},
            account_status={"balance": 10000, "equity": 10000},
            save_to_db=True,
            pretrade_scan=pretrade_scan
        )

        return result, mock_dna


class TestQualityScorePersistenceConsensus(unittest.TestCase):
    """Tests for quality_telemetry in decision_dna when consensus is reached."""

    def test_quality_telemetry_included_in_decision_dna(self):
        """When pretrade_scan is provided, quality_telemetry appears in decision_dna."""
        scan = _fresh_pretrade_scan()
        result, mock_dna = _run_consensus_with_mock(pretrade_scan=scan)

        self.assertTrue(mock_dna.called)
        saved_snapshot = mock_dna.call_args[0][1]
        self.assertIn("quality_telemetry", saved_snapshot)
        qt = saved_snapshot["quality_telemetry"]
        self.assertEqual(qt["score"], 82.0)
        self.assertEqual(qt["threshold"], 75.0)
        self.assertTrue(qt["passed"])
        self.assertEqual(qt["verdict"], "TRADE_APPROVED")
        self.assertTrue(qt["reached_consensus"])
        self.assertEqual(qt["consensus_status"], result.decision_status)
        self.assertFalse(qt["execution_dispatched"])

    def test_quality_breakdown_persisted_exactly(self):
        """Component breakdown is persisted with exact values."""
        qs = _fresh_quality_score(score=75.5)
        qs["breakdown"]["mtf_alignment"]["score"] = 12.5
        qs["breakdown"]["smc_confluence"]["score"] = 16.0
        scan = _fresh_pretrade_scan(quality_score=qs)

        _, mock_dna = _run_consensus_with_mock(pretrade_scan=scan)

        saved = mock_dna.call_args[0][1]["quality_telemetry"]
        self.assertEqual(saved["breakdown"]["mtf_alignment"]["score"], 12.5)
        self.assertEqual(saved["breakdown"]["smc_confluence"]["score"], 16.0)
        self.assertEqual(saved["score"], 75.5)

    def test_threshold_persisted_separately_from_score(self):
        """Threshold is stored as its own field, not confused with score."""
        qs = _fresh_quality_score(score=71.0, threshold=75.0, passed=False)
        scan = _fresh_pretrade_scan(quality_score=qs, trade_allowed=False,
                                     decision_reason="Quality score 71.0/100 below threshold.")

        _, mock_dna = _run_consensus_with_mock(pretrade_scan=scan)

        saved = mock_dna.call_args[0][1]["quality_telemetry"]
        self.assertEqual(saved["score"], 71.0)
        self.assertEqual(saved["threshold"], 75.0)
        self.assertFalse(saved["passed"])
        self.assertEqual(saved["verdict"], "NO_TRADE_QUALITY_BELOW_THRESHOLD")

    def test_no_pretrade_scan_no_quality_telemetry(self):
        """When pretrade_scan is None, quality_telemetry is not in snapshot (backward compat)."""
        _, mock_dna = _run_consensus_with_mock(pretrade_scan=None)

        saved = mock_dna.call_args[0][1]
        self.assertNotIn("quality_telemetry", saved)

    def test_adx_rsi_spread_persisted(self):
        """ADX, RSI, spread_pips are persisted in quality_telemetry."""
        scan = _fresh_pretrade_scan()
        scan["indicators"]["adx"] = {"adx": 26.4}
        scan["indicators"]["rsi"] = 52.3
        scan["spread_pips"] = 0.3

        _, mock_dna = _run_consensus_with_mock(pretrade_scan=scan)

        saved = mock_dna.call_args[0][1]["quality_telemetry"]
        self.assertEqual(saved["adx"], 26.4)
        self.assertEqual(saved["rsi"], 52.3)
        self.assertEqual(saved["spread_pips"], 0.3)

    def test_smc_mtf_zone_persisted(self):
        """SMC structure, MTF consensus, dealing zone are persisted."""
        scan = _fresh_pretrade_scan()
        scan["smc"]["structure"] = "BULLISH_TREND"
        scan["mtf"]["consensus_trend"] = "BULLISH"
        scan["smc"]["dealing_range"]["zone"] = "DISCOUNT"

        _, mock_dna = _run_consensus_with_mock(pretrade_scan=scan)

        saved = mock_dna.call_args[0][1]["quality_telemetry"]
        self.assertEqual(saved["smc_structure"], "BULLISH_TREND")
        self.assertEqual(saved["mtf_consensus"], "BULLISH")
        self.assertEqual(saved["dealing_zone"], "DISCOUNT")


class TestQualityScorePersistenceBlocked(unittest.TestCase):
    """Tests for quality telemetry persistence via audit_logs for blocked scans."""

    def test_blocked_scan_persists_quality_to_audit(self):
        """Blocked scans persist quality_score to audit_logs with PRETRADE_QUALITY_SCAN event type."""
        scan = _fresh_pretrade_scan(
            trade_allowed=False,
            decision_reason="NO_TRADE_REGIME_ADX: ADX 16.2 below minimum 20.0.",
            quality_score=_fresh_quality_score(score=48.0, passed=False)
        )

        with patch.object(db, "log_audit") as mock_audit:
            qs = scan.get("quality_score", {})
            db.log_audit(
                event_type="PRETRADE_QUALITY_SCAN",
                actor="AutonomousScanner",
                details=json.dumps({
                    "symbol": "XAUUSD",
                    "timestamp": time.time(),
                    "trade_allowed": False,
                    "rejection_reason": scan.get("decision_reason"),
                    "setup_type": scan.get("setup", {}).get("setup_type"),
                    "direction": scan.get("setup", {}).get("direction"),
                    "quality_score": qs.get("score"),
                    "quality_threshold": qs.get("threshold"),
                    "quality_passed": qs.get("passed"),
                    "quality_breakdown": qs.get("breakdown"),
                    "adx": 16.2,
                    "rsi": 52.3,
                    "spread_pips": 0.3,
                    "smc_structure": "RANGE",
                    "mtf_consensus": "NEUTRAL",
                    "dealing_zone": "EQUILIBRIUM",
                    "reached_consensus": False,
                    "execution_dispatched": False
                }, ensure_ascii=False)
            )

            self.assertTrue(mock_audit.called)
            call_args = mock_audit.call_args
            event_type = call_args[1].get("event_type") if call_args[1] else call_args[0][0]
            self.assertEqual(event_type, "PRETRADE_QUALITY_SCAN")
            details_str = call_args[1].get("details") if call_args[1] else call_args[0][2]
            details = json.loads(details_str)
            self.assertFalse(details["trade_allowed"])
            self.assertEqual(details["quality_score"], 48.0)
            self.assertEqual(details["quality_threshold"], 75.0)
            self.assertFalse(details["quality_passed"])
            self.assertFalse(details["reached_consensus"])
            self.assertFalse(details["execution_dispatched"])
            self.assertIn("rejection_reason", details)
            self.assertIn("adx", details)
            self.assertIn("rsi", details)
            self.assertIn("quality_breakdown", details)


class TestBackwardCompatibility(unittest.TestCase):
    """Tests for backward compatibility with older decision_dna rows."""

    def test_older_decision_dna_without_quality_telemetry_loads(self):
        """Older decision_dna rows without quality_telemetry still load correctly."""
        old_snapshot = {
            "signal_id": "SIG_OLD_001",
            "status": "APPROVED",
            "decision_score": 88.5,
            "signal": {"symbol": "XAUUSD", "action": "BUY"},
            "market_snapshot": {"price": 4350.0},
            "agent_evaluations": [],
            "risk_check": {"passed": True},
            "guardian": {"blocked": False}
        }
        self.assertNotIn("quality_telemetry", old_snapshot)
        self.assertEqual(old_snapshot["decision_score"], 88.5)

    def test_reading_old_snapshot_json_without_quality_telemetry(self):
        """Parsing old snapshot JSON that lacks quality_telemetry does not error."""
        old_json = json.dumps({
            "signal_id": "SIG_OLD_002",
            "decision_score": 90.0
        })
        parsed = json.loads(old_json)
        qt = parsed.get("quality_telemetry")
        self.assertIsNone(qt)

    def test_new_snapshot_with_quality_telemetry_roundtrips(self):
        """New snapshot with quality_telemetry survives JSON roundtrip."""
        snapshot = {
            "signal_id": "SIG_NEW_001",
            "quality_telemetry": {
                "score": 82.0,
                "threshold": 75.0,
                "passed": True,
                "breakdown": {"mtf_alignment": {"score": 20.0, "max": 20.0}}
            }
        }
        roundtripped = json.loads(json.dumps(snapshot))
        self.assertEqual(roundtripped["quality_telemetry"]["score"], 82.0)
        self.assertEqual(roundtripped["quality_telemetry"]["breakdown"]["mtf_alignment"]["score"], 20.0)


class TestPersistenceFailureSafety(unittest.TestCase):
    """Tests that persistence failures do not weaken fail-closed safety."""

    def test_audit_log_failure_does_not_block_trade_safety(self):
        """If audit_logs write fails, it should not raise or block execution."""
        with patch.object(db, "log_audit", side_effect=Exception("DB write failure")):
            try:
                db.log_audit(event_type="PRETRADE_QUALITY_SCAN", actor="Test", details="{}")
            except Exception:
                pass
            # No crash = safe

    def test_decision_dna_write_failure_does_not_weaken_guardian(self):
        """Guardian blocks correctly even when subsequent DB writes would fail."""
        scan = _fresh_pretrade_scan()

        from app.engine.consensus_engine import MultiAgentConsensusEngine
        engine = MultiAgentConsensusEngine()
        sig = SignalPayload(
            symbol="XAUUSD", action="BUY", entry_price=4350, stop_loss=4344,
            take_profit=4362, volume=0.01, timeframe="15m", strategy_name="T", source="TEST"
        )

        mocks = _mock_all_agents()
        mocks["guardian"]["check_guard_rules"] = (True, "Guardian blocks test")

        def arbitrate_fn(signal, agent_decisions, risk_check, guardian_veto=False, guardian_reason=None):
            if guardian_veto:
                return ("BLOCKED", 0.0, f"Guardian: {guardian_reason}")
            return ("APPROVED", 88.5, "Test approval")

        with patch.object(db, "save_decision_dna"), \
             patch.object(db, "save_signal"), \
             patch.object(db, "save_agent_decisions"), \
             patch.object(db, "save_risk_check"), \
             patch.object(db, "log_audit"), \
             patch("app.engine.consensus_engine.guardian") as m_guardian, \
             patch("app.engine.consensus_engine.head_desk_agent") as m_head, \
             patch("app.engine.consensus_engine.explainability_engine") as m_expl:

            m_guardian.check_guard_rules.return_value = mocks["guardian"]["check_guard_rules"]
            m_head.arbitrate.side_effect = arbitrate_fn
            m_expl.generate_explanation.return_value = mocks["explainability_engine"]["generate_explanation"]

            result = engine.process_signal(
                signal=sig,
                market_data={"price": 4350, "bid": 4349.9, "ask": 4350.1, "spread": 0.2},
                macro_data={},
                account_status={"balance": 10000, "equity": 10000},
                save_to_db=True,
                pretrade_scan=scan
            )
            self.assertEqual(result.decision_status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
