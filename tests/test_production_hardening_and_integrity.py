import os
import sys
import unittest
import time

sys.path.insert(0, r"d:\Users\AL RAZZAQ\Desktop\Trade Talk")

from app.services.market_data_integrity_monitor import market_data_integrity_monitor
from app.services.volatility_engine import volatility_engine
from app.services.position_manager_v3 import position_manager_v3
from app.services.structural_exit_engine import structural_exit_engine
from app.services.position_sentinel import position_sentinel
from app.services.live_safety_gate import live_safety_gate
from app.services.ctrader_execution_service import ctrader_execution_service

class ProductionHardeningAndIntegrityTests(unittest.TestCase):

    def setUp(self):
        # Reset monitor and position manager state
        market_data_integrity_monitor.set_connection_state("CONNECTED", is_authenticated=True)
        market_data_integrity_monitor._latest_ticks.clear()
        position_manager_v3._managed_positions.clear()
        position_manager_v3._last_close_events.clear()

    # =========================================================================
    # 1. PRICE INTEGRITY & STALE CACHE REGRESSION TESTS (Section 3 & 34)
    # =========================================================================
    def test_01_valid_live_tick_recorded_and_validated(self):
        """Test that healthy live broker ticks pass integrity checks."""
        is_valid, reason, tick = market_data_integrity_monitor.record_and_validate_tick(
            symbol="XAUUSD",
            bid=4405.20,
            ask=4405.50,
            tick_timestamp=time.time()
        )
        self.assertTrue(is_valid)
        self.assertEqual(reason, "TICK_INTEGRITY_PASSED")
        self.assertEqual(tick["spread"], 0.30)
        self.assertEqual(tick["mid"], 4405.35)

    def test_02_impossible_price_inverted_book_rejected(self):
        """Test that Ask < Bid is rejected as IMPOSSIBLE_PRICE."""
        is_valid, reason, data = market_data_integrity_monitor.record_and_validate_tick(
            symbol="XAUUSD",
            bid=4405.50,
            ask=4404.00, # Inverted book
            tick_timestamp=time.time()
        )
        self.assertFalse(is_valid)
        self.assertIn("IMPOSSIBLE_PRICE", reason)

    def test_03_zero_and_negative_prices_rejected(self):
        """Test that zero or negative prices are strictly rejected."""
        is_valid, reason, _ = market_data_integrity_monitor.record_and_validate_tick(
            symbol="XAUUSD",
            bid=0.0,
            ask=4405.00,
            tick_timestamp=time.time()
        )
        self.assertFalse(is_valid)
        self.assertIn("ZERO_PRICE", reason)

        is_valid2, reason2, _ = market_data_integrity_monitor.record_and_validate_tick(
            symbol="XAUUSD",
            bid=-10.0,
            ask=4405.00,
            tick_timestamp=time.time()
        )
        self.assertFalse(is_valid2)
        self.assertIn("NEGATIVE_PRICE", reason2)

    def test_04_stale_cache_price_rejected_against_live_feed(self):
        """
        REGRESSION TEST (Section 34):
        Current live broker Gold ≈ 4405.35. An internal component attempts to
        propose an order at stale price 2884.00.
        EXPECTED: Stale price REJECTED by data integrity monitor.
        """
        # 1. Establish current live broker tick
        market_data_integrity_monitor.record_and_validate_tick(
            symbol="XAUUSD",
            bid=4405.20,
            ask=4405.50,
            tick_timestamp=time.time()
        )
        # 2. Test validation of stale 2884 price candidate
        is_valid, reason = market_data_integrity_monitor.validate_candidate_price_against_feed(
            symbol="XAUUSD",
            candidate_price=2884.00,
            max_allowed_deviation_pips=50.0
        )
        self.assertFalse(is_valid)
        self.assertIn("VETO_PRICE_DEVIATION", reason)

    def test_05_stale_market_feed_fails_closed(self):
        """Test that ticks older than max freshness limit (> 5.0s) fail closed."""
        old_time = time.time() - 15.0 # 15 seconds old
        is_valid, reason, _ = market_data_integrity_monitor.record_and_validate_tick(
            symbol="XAUUSD",
            bid=4405.00,
            ask=4405.30,
            tick_timestamp=old_time
        )
        self.assertFalse(is_valid)
        self.assertIn("STALE_PRICE", reason)

    # =========================================================================
    # 2. DYNAMIC VOLATILITY & TRUE 1R CALCULATION (Section 8, 9, 10)
    # =========================================================================
    def test_06_true_1r_stored_permanently(self):
        """
        Test that 1R is position-specific (|Entry - Initial_SL|) and stored permanently.
        Never universally fixed to $5.00.
        """
        # Position with $10.00 initial risk
        pos = position_manager_v3.register_new_position(
            position_id="POS_1R_TEST_01",
            symbol="XAUUSD",
            direction="BUY",
            volume=0.01,
            entry_price=4400.00,
            initial_sl=4390.00, # 1R = $10.00
            initial_tp=4425.00
        )
        self.assertEqual(pos["initial_risk_1r"], 10.00)

        # Position with $6.00 initial risk
        pos2 = position_manager_v3.register_new_position(
            position_id="POS_1R_TEST_02",
            symbol="XAUUSD",
            direction="BUY",
            volume=0.01,
            entry_price=4400.00,
            initial_sl=4394.00, # 1R = $6.00
            initial_tp=4415.00
        )
        self.assertEqual(pos2["initial_risk_1r"], 6.00)

    def test_07_volatility_engine_adaptive_regime(self):
        """Test that VolatilityEngine classifies volatility regimes and computes adaptive SL buffer."""
        vol = volatility_engine.compute_multi_timeframe_volatility("XAUUSD")
        self.assertIn(vol["regime"], ["LOW", "NORMAL", "HIGH", "EXTREME"])
        self.assertGreater(vol["min_structural_sl_distance"], 0.0)
        self.assertGreater(vol["recommended_sl_distance"], 0.0)

    # =========================================================================
    # 3. REGRESSION TEST — ORIGINAL POSITIONSENTINEL BUG (Section 33)
    # =========================================================================
    def test_08_position_sentinel_subsecond_spread_regression(self):
        """
        REGRESSION TEST (Section 33):
        Open position -> normal broker spread ($0.30) / minor tick noise ->
        PositionSentinel evaluates position.
        EXPECTED:
        - Position REMAINS OPEN (NO FORCE CLOSE)
        - NO AUTOMATIC REVERSE POSITION
        - Broker SL/TP remain active
        """
        # Fetch current snapshot price so entry is aligned with current market
        from app.services.market_feed_v2 import get_market_snapshot
        snap = get_market_snapshot("XAUUSD")
        curr_p = float(snap.get("price", 4400.0))

        fake_pos = {
            "id": "POS_NOISE_TEST",
            "symbol": "XAUUSD",
            "type": "BUY",
            "entry_price": curr_p,
            "sl_price": curr_p - 8.00,
            "tp_price": curr_p + 20.00,
            "net_profit": -0.30, # -30 cents spread drawdown
            "unrealized_pnl": -0.30
        }
        ctrader_execution_service._positions_cache["POS_NOISE_TEST"] = fake_pos

        actions = position_sentinel.evaluate_open_positions()
        
        # Verify ZERO force-close actions taken on noise
        close_actions = [a for a in actions if "CLOSE" in str(a.get("action")) or "REVERSAL" in str(a.get("action"))]
        self.assertEqual(len(close_actions), 0, "Position must NOT be closed on spread noise!")
        
        # Verify position is still in cache with original SL/TP
        pos_in_cache = ctrader_execution_service._positions_cache.get("POS_NOISE_TEST")
        self.assertIsNotNone(pos_in_cache)
        self.assertEqual(pos_in_cache["sl_price"], curr_p - 8.00)
        self.assertEqual(pos_in_cache["tp_price"], curr_p + 20.00)

        ctrader_execution_service._positions_cache.pop("POS_NOISE_TEST", None)

    # =========================================================================
    # 4. ANTI-FLIP SAFEGUARD & STRUCTURAL EXIT TESTS (Section 7, 19, 20)
    # =========================================================================
    def test_09_anti_flip_guard_blocks_immediate_reverse_trade(self):
        """Test that an immediate opposite trade is blocked by Anti-Flip guard."""
        # Record closed BUY position
        position_manager_v3._record_closed_position(
            pos={"position_id": "POS_FLIP_01", "symbol": "XAUUSD", "direction": "BUY"},
            exit_model="BROKER_STOP_LOSS"
        )
        
        # Attempt immediate SELL (opposite direction)
        is_clear, reason = position_manager_v3.check_anti_flip_guard("XAUUSD", "SELL")
        self.assertFalse(is_clear)
        self.assertIn("VETO_ANTI_FLIP_COOLDOWN", reason)

        # Same direction BUY is permitted
        is_clear_same, _ = position_manager_v3.check_anti_flip_guard("XAUUSD", "BUY")
        self.assertTrue(is_clear_same)

    def test_10_structural_exit_engine_requires_completed_candle(self):
        """Test that StructuralExitEngine does not exit on live noise and requires completed structure."""
        is_inv, reason, _ = structural_exit_engine.evaluate_structural_invalidation(
            symbol="XAUUSD",
            position_type="BUY",
            entry_price=4400.00,
            initial_sl=4390.00,
            timeframe="5m"
        )
        # In the absence of completed candle breakdown, structure remains intact
        self.assertIn(reason, ["STRUCTURE_INTACT", "INSUFFICIENT_CANDLE_DATA"])

if __name__ == "__main__":
    unittest.main()
