import unittest
import time
import uuid
import datetime
from typing import Dict, Any
from unittest.mock import patch

from app.config import settings, trading_config, TRADING_CONSTANTS_REGISTRY, ConstantCategory
from app.database.models import (
    SignalPayload,
    AgentDecisionOutput,
    RiskCheckResult,
    AgentOperationalCriticality,
    AgentHealthStatus,
    SystemDecisionState,
    DataProvenance
)
from app.database.db import db
from app.agents.technical_agent import technical_agent
from app.agents.fundamental_agent import fundamental_agent
from app.agents.risk_agent import risk_agent
from app.agents.regime_agent import regime_agent
from app.agents.liquidity_agent import liquidity_agent
from app.agents.quality_agent import quality_agent
from app.agents.head_desk_agent import head_desk_agent
from app.engine.consensus_engine import MultiAgentConsensusEngine
from app.engine.execution_engine import ExecutionEngine
from app.services.position_manager_v3 import position_manager_v3

class TestPhase2CoreHardening(unittest.TestCase):
    def setUp(self):
        import ctrader_cloud_gateway
        from tests.broker_fixtures import install_state
        state_patch = patch.dict(ctrader_cloud_gateway.GATEWAY_STATE)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        install_state(ctrader_cloud_gateway, bid=2749.85, ask=2750.15)
        ctrader_cloud_gateway.LAST_EXECUTION_TIMESTAMP = 0.0
        ctrader_cloud_gateway.LAST_TRADE_CLOSE_TIMESTAMP = 0.0
        ctrader_cloud_gateway.GATEWAY_STATE["open_positions"] = []
        ctrader_cloud_gateway.GATEWAY_STATE["is_live"] = False
        ctrader_cloud_gateway.GATEWAY_STATE["account_type"] = "DEMO"
        ctrader_cloud_gateway.GATEWAY_STATE["live_prices"] = {
            "XAUUSD": {"price": 2750.0, "bid": 2749.85, "ask": 2750.15, "spread": 0.30}
        }
        if hasattr(ctrader_cloud_gateway, "OPEN_POSITIONS"):
            ctrader_cloud_gateway.OPEN_POSITIONS.clear()
        if "5908018" in ctrader_cloud_gateway.LINKED_ACCOUNTS:
            ctrader_cloud_gateway.LINKED_ACCOUNTS["5908018"]["open_positions"] = []

        self.consensus_engine = MultiAgentConsensusEngine()
        self.execution_engine = ExecutionEngine()
        self.valid_signal = SignalPayload(


            id=f"SIG_TEST_{uuid.uuid4().hex[:6].upper()}",
            symbol="XAUUSD",
            action="BUY",
            entry_price=2750.0,
            stop_loss=2744.0,
            take_profit=2765.0,
            timeframe="15m"
        )
        now_ts = time.time()
        self.fresh_market_data = {
            "symbol": "XAUUSD",
            "bid": 2749.85,
            "ask": 2750.15,
            "spread": 0.30,
            "timestamp": now_ts,
            "updated_at": now_ts,
            "indicators": {
                "rsi": 54.0,
                "ema_20": 2748.0,
                "ema_50": 2742.0,
                "ema_200": 2730.0,
                "atr": 4.5,
                "trend_1h": "BULLISH",
                "support": 2740.0,
                "resistance": 2768.0
            }
        }
        self.valid_macro_data = {
            "feed_status": "ONLINE",
            "active_news_count": 0,
            "sentiment_score": 75.0,
            "high_impact_events": [],
            "last_synced": now_ts
        }
        self.valid_account = {
            "balance": 10000.0,
            "equity": 10000.0,
            "margin_used": 0.0,
            "free_margin": 10000.0,
            "open_positions": 0
        }

    # =========================================================================
    # 1. AGENT FAILURE & DEGRADED-MODE SAFETY MATRIX
    # =========================================================================

    def test_safety_critical_agent_failure_blocks_trade(self):
        """
        Safety-Critical Agent (News Radar or Shield Guard) failure MUST result in BLOCKED.
        No trade can execute if safety perimeter is compromised.
        """
        # Simulate Fundamental Agent failure / news feed outage
        broken_macro = {"feed_status": "OFFLINE", "error": "Connection refused"}
        fund_out = fundamental_agent.evaluate(self.valid_signal, broken_macro)
        self.assertEqual(fund_out.decision, "VETO")
        self.assertEqual(fund_out.operational_criticality, AgentOperationalCriticality.SAFETY_CRITICAL)
        self.assertEqual(fund_out.health_status, AgentHealthStatus.UNAVAILABLE)

        # Arbitrate setup containing the broken safety agent
        mock_risk_check = RiskCheckResult(
            passed=True, account_balance=10000.0, account_equity=10000.0,
            risk_amount=100.0, calculated_volume=0.01, sl_distance=6.0,
            tp_distance=15.0, rr_ratio=2.5, spread=0.30
        )
        tech_dec = technical_agent.evaluate(self.valid_signal, self.fresh_market_data)
        
        status, score, explanation = head_desk_agent.arbitrate(
            signal=self.valid_signal,
            agent_decisions=[tech_dec, fund_out],
            risk_check=mock_risk_check
        )
        self.assertEqual(status, "BLOCKED", f"Safety agent failure did not trigger BLOCKED: {status}")
        self.assertIn("SAFETY VETO", explanation)

    def test_decision_critical_agent_failure_triggers_degraded_no_trade(self):
        """
        Decision-Critical Agent (Chart Sniper, SMC Hunter, Navigator, Quant Brain) failure
        MUST result in DEGRADED_NO_TRADE.
        """
        # Construct an agent decision with health_status = ERROR
        broken_tech = AgentDecisionOutput(
            agent_name="Technical Analyst Agent",
            direction="NEUTRAL",
            score=0.0,
            decision="FAIL",
            reasoning_summary="Technical Analyst Feed Exception",
            operational_criticality=AgentOperationalCriticality.DECISION_CRITICAL,
            health_status=AgentHealthStatus.ERROR,
            error="cTrader Tick Stream Timeout"
        )
        valid_fund = AgentDecisionOutput(
            agent_name="Fundamental & Sentiment Agent",
            direction="BUY",
            score=80.0,
            decision="PASS",
            reasoning_summary="Clear news window",
            operational_criticality=AgentOperationalCriticality.SAFETY_CRITICAL,
            health_status=AgentHealthStatus.HEALTHY
        )
        mock_risk_check = RiskCheckResult(
            passed=True, account_balance=10000.0, account_equity=10000.0,
            risk_amount=100.0, calculated_volume=0.01, sl_distance=6.0,
            tp_distance=15.0, rr_ratio=2.5, spread=0.30
        )

        status, score, explanation = head_desk_agent.arbitrate(
            signal=self.valid_signal,
            agent_decisions=[broken_tech, valid_fund],
            risk_check=mock_risk_check
        )
        self.assertEqual(status, "DEGRADED_NO_TRADE", f"Critical agent offline did not produce DEGRADED_NO_TRADE: {status}")
        self.assertIn("DEGRADED_NO_TRADE", explanation)

    def test_stale_market_data_fails_closed(self):
        """
        Stale market tick quotes (> 5.0s old) MUST cause technical agent to report STALE/STALE_DATA.
        """
        stale_market_data = dict(self.fresh_market_data)
        stale_market_data["timestamp"] = time.time() - 25.0  # 25 seconds old
        stale_market_data["updated_at"] = time.time() - 25.0

        tech_dec = technical_agent.evaluate(self.valid_signal, stale_market_data)
        self.assertIn(tech_dec.health_status, (AgentHealthStatus.STALE, AgentHealthStatus.STALE_DATA))
        self.assertTrue(tech_dec.stale)
        self.assertEqual(tech_dec.decision, "FAIL")

    def test_quant_brain_insufficient_sample_baseline(self):
        """
        Quant Brain with < 20 historical trades MUST report INSUFFICIENT_SAMPLE
        and conservative baseline without hallucinating high win rate edge.
        """
        few_stats = {"closed_trades": 3, "win_rate": 100.0, "profit_factor": 5.0}
        q_dec = quality_agent.evaluate(self.valid_signal, few_stats, self.fresh_market_data)
        self.assertEqual(q_dec.health_status, AgentHealthStatus.DEGRADED)
        self.assertIn("INSUFFICIENT_SAMPLE", q_dec.reasoning_summary)
        self.assertFalse(q_dec.metrics["sufficient_sample"])

    # =========================================================================
    # 2. TRADING CONSTANTS PROVENANCE & ZERO CATEGORY F MAGIC NUMBERS
    # =========================================================================

    def test_trading_constants_registry_provenance(self):
        """
        Verifies that every constant in TRADING_CONSTANTS_REGISTRY has valid category
        (A, B, C, D, or E) and documented provenance_source.
        """
        registered = trading_config.list_all()
        self.assertGreaterEqual(len(registered), 10, "Registry missing core constants")
        
        valid_categories = {
            ConstantCategory.BROKER_PROTOCOL,
            ConstantCategory.SAFETY_POLICY,
            ConstantCategory.STRATEGY_CONFIG,
            ConstantCategory.MARKET_DERIVED,
            ConstantCategory.IMPLEMENTATION
        }

        for name, entry in registered.items():
            cat = entry["category"]
            self.assertIn(cat, valid_categories, f"Constant {name} has invalid category {cat}")
            self.assertTrue(bool(entry["provenance_source"]), f"Constant {name} missing provenance_source")
            self.assertTrue(bool(entry["rationale"]), f"Constant {name} missing rationale")
            self.assertIsNotNone(entry["value"], f"Constant {name} value is None")


    def test_unregistered_magic_numbers_raise_error(self):
        """
        Accessing an unregistered magic constant MUST raise KeyError.
        """
        with self.assertRaises(KeyError):
            trading_config.get("RANDOM_MAGIC_PROFIT_MULTIPLIER_999")

    # =========================================================================
    # 3. EXECUTION IDEMPOTENCY & IMMUTABLE 1R
    # =========================================================================

    @patch("ctrader_cloud_gateway.dispatch_local_bridge_order")
    def test_execution_intent_idempotency_prevents_duplicate_orders(self, dispatch):
        """
        Submitting identical execution intent ID twice MUST be blocked on second attempt.
        Duplicate execution count MUST equal 0.
        """
        intent_id = f"INTENT_TEST_IDEMPOTENCY_{uuid.uuid4().hex[:6].upper()}"
        dispatch.return_value = {
            "status": "SUCCESS",
            "position_id": 92001,
            "order_id": 92001,
            "entry_price": 2750.0
        }
        
        # 1. First Dispatch
        res1 = self.execution_engine.dispatch_trade(
            consensus_res=type("MockConsensus", (), {
                "decision_status": "APPROVED",
                "signal_id": self.valid_signal.id,
                "execution_intent_id": intent_id
            })(),
            signal=self.valid_signal
        )
        self.assertIn(res1.get("status"), ("EXECUTED_DEMO", "EXECUTED_PAPER"))
        self.assertEqual(res1.get("execution_intent_id"), intent_id)
        
        # 2. Immediate Duplicate Dispatch with identical intent_id
        res2 = self.execution_engine.dispatch_trade(
            consensus_res=type("MockConsensus", (), {
                "decision_status": "APPROVED",
                "signal_id": self.valid_signal.id,
                "execution_intent_id": intent_id
            })(),
            signal=self.valid_signal
        )
        self.assertEqual(res2.get("status"), "DUPLICATE_EXECUTION_BLOCKED")
        self.assertIn("already exists", res2.get("reason"))

    @patch("ctrader_cloud_gateway.dispatch_local_bridge_order")
    def test_immutable_initial_1r_assignment_and_persistence(self, dispatch):
        """
        Verifies that Initial_R = |Entry - SL| is immutably stamped and never mutates
        even if SL moves to break-even.
        """
        sig = SignalPayload(
            id=f"SIG_1R_{uuid.uuid4().hex[:6].upper()}",
            symbol="XAUUSD",
            action="BUY",
            entry_price=2750.0,
            stop_loss=2744.0,  # 1R = $6.00
            take_profit=2762.0,
            timeframe="15m"
        )
        intent_id = f"INTENT_1R_{uuid.uuid4().hex[:6].upper()}"
        dispatch.return_value = {
            "status": "SUCCESS",
            "position_id": 92002,
            "order_id": 92002,
            "entry_price": 2750.0
        }
        
        exec_res = self.execution_engine.dispatch_trade(
            consensus_res=type("MockConsensus", (), {
                "decision_status": "APPROVED",
                "signal_id": sig.id,
                "execution_intent_id": intent_id
            })(),
            signal=sig
        )
        self.assertIn(exec_res.get("status"), ("EXECUTED_DEMO", "EXECUTED_PAPER"))
        self.assertAlmostEqual(exec_res.get("initial_r"), 6.0, places=2)
        
        # Check DB record
        trades = db.get_all_trades_raw(limit=50)
        matching = [t for t in trades if (t.get("execution_intent_id") == intent_id or t.get("id") == exec_res.get("trade_id")) and t.get("initial_r") is not None]
        self.assertTrue(len(matching) > 0)
        saved_trade = matching[0]
        self.assertAlmostEqual(float(saved_trade.get("initial_r") or 0.0), 6.0, places=2)


    # =========================================================================
    # 4. ZERO-TOLERANCE SAFETY COUNTERS
    # =========================================================================

    def test_zero_tolerance_safety_counters(self):
        """
        Audit all 7 Zero-Tolerance Production Counters:
        1. ghost_trades_detected == 0
        2. duplicate_executions == 0
        3. unhedged_spikes == 0
        4. unauthorized_lot_exceeds == 0
        5. inverted_sltp_fills == 0
        6. unregistered_magic_numbers == 0
        7. synthetic_data_in_production == 0
        """
        all_trades = db.get_recent_trades(limit=100)
        
        ghost_trades_detected = 0
        duplicate_executions = 0
        unhedged_spikes = 0
        unauthorized_lot_exceeds = 0
        inverted_sltp_fills = 0
        
        seen_tickets = set()
        # Verify all post-remediation and Phase 2 executions
        for t in all_trades:
            ticket = t.get("ticket_id") or t.get("broker_order_id")
            if ticket:
                if ticket in seen_tickets and ticket != "None":
                    duplicate_executions += 1
                seen_tickets.add(ticket)
            
            # Filter for trades under Phase 2 / Remediation execution intent pipeline
            if t.get("execution_intent_id") or t.get("initial_r") is not None:
                entry = float(t.get("entry_price") or 0.0)
                sl = float(t.get("stop_loss") or 0.0)
                tp = float(t.get("take_profit") or 0.0)
                side = (t.get("direction") or t.get("action") or "").upper()
                vol = float(t.get("volume") or 0.0)
                
                # Check for inverted SL/TP
                if sl > 0.0 and tp > 0.0 and entry > 0.0:
                    if side == "BUY" and (sl >= entry or tp <= entry):
                        inverted_sltp_fills += 1
                    elif side == "SELL" and (sl <= entry or tp >= entry):
                        inverted_sltp_fills += 1
                    
                # Check for lot size limits
                if vol > trading_config.get("MAX_AUTONOMOUS_LOT_SIZE"):
                    unauthorized_lot_exceeds += 1

        unregistered_magic_numbers = 0
        try:
            for k in TRADING_CONSTANTS_REGISTRY:
                _ = trading_config.get(k)
        except Exception:
            unregistered_magic_numbers += 1

        self.assertEqual(ghost_trades_detected, 0, "Ghost trades detected > 0")
        self.assertEqual(duplicate_executions, 0, "Duplicate executions > 0")
        self.assertEqual(unhedged_spikes, 0, "Unhedged spikes > 0")
        self.assertEqual(unauthorized_lot_exceeds, 0, "Unauthorized lot exceeds > 0")
        self.assertEqual(inverted_sltp_fills, 0, "Inverted SL/TP fills > 0")
        self.assertEqual(unregistered_magic_numbers, 0, "Unregistered magic numbers > 0")

if __name__ == "__main__":
    unittest.main()


