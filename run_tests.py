import sys
import os
import tempfile
import atexit
import unittest

os.environ["TESTING"] = "1"
_test_runtime = tempfile.TemporaryDirectory(prefix="tradetalk_test_", ignore_cleanup_errors=True)
_test_db_fd, _test_db_path = tempfile.mkstemp(dir=_test_runtime.name, suffix=".db")
os.close(_test_db_fd)
os.environ["DATABASE_PATH"] = _test_db_path

def _cleanup_test_db():
    try:
        if os.path.exists(_test_db_path):
            os.remove(_test_db_path)
    except Exception:
        pass

atexit.register(_cleanup_test_db)
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from tests.test_risk_calculations import (
    test_risk_agent_passes_valid_gold_trade,
    test_risk_agent_vetoes_insufficient_rr,
    test_risk_agent_vetoes_circuit_breaker,
    test_dynamic_pair_settings_and_lot_controls
)
from tests.test_7_agents import test_all_6_agents_evaluate_valid_setup
from tests.test_guardian import test_guardian_blocks_high_spread, test_guardian_blocks_upcoming_news
from tests.test_webhook_security import test_webhook_security_valid_token, test_webhook_security_invalid_token
from tests.test_backtester import test_strategy_lab_backtest_execution
from tests.test_ctrader_cloud import test_ctrader_cloud_order_execution
from tests.test_ctrader_openapi import TestCTraderOpenAPI
from tests.test_phase1 import (
    test_dpapi_credential_store,
    test_secret_masking_logger,
    test_expanded_database_schema,
    test_emergency_kill_switch_blocks_trade
)
from tests.test_phase2 import (
    test_dynamic_symbol_resolver,
    test_ctrader_openapi_rate_limiter,
    test_ctrader_market_data_engine,
    test_token_refresh_lifecycle
)
from tests.test_phase3 import (
    test_technical_indicators_suite,
    test_smart_money_concepts_suite,
    test_multi_timeframe_confluence_engine
)
from tests.test_phase4 import (
    test_economic_calendar_and_lockout_windows,
    test_spread_normalization_guard,
    test_financial_nlp_news_sentiment_engine,
    test_phase4_api_endpoints
)
from tests.test_phase5 import (
    test_7_agents_weighted_consensus_approval,
    test_hard_risk_veto_overrides_consensus,
    test_decision_dna_persistence_and_retrieval,
    test_bilingual_explainability_synthesis
)
from tests.test_phase6 import (
    test_dynamic_position_sizing_standard_account,
    test_dynamic_position_sizing_micro_account,
    test_daily_drawdown_circuit_breaker,
    test_consecutive_losses_cooldown_and_reset,
    test_risk_api_endpoints
)
from tests.test_phase7 import TestPhase7PaperJournalPerformance
from tests.test_phase8 import TestPhase8BacktestingAndValidation
from tests.test_phase9 import TestPhase9CTraderExecution
from tests.test_phase10 import TestPhase10LiveSafetyAndAutonomousIntegration
from tests.test_pretrade_intelligence import (
    test_smart_money_engine_swing_points,
    test_smart_money_engine_fvg_detection,
    test_smart_money_engine_order_blocks,
    test_smart_money_engine_premium_discount,
    test_session_engine,
    test_setup_classifier,
    test_trade_quality_scorer,
    test_pretrade_intelligence_fail_closed_on_missing_feed
)
from tests.test_loss_investigation_remediation import (
    test_strict_sltp_geometry_buy_inverted,
    test_strict_sltp_geometry_sell_inverted,
    test_strict_sltp_minimum_buffer_too_tight,
    test_strict_sltp_valid_order_passes,
    test_position_sentinel_no_premature_reversal_close,
    test_state_reconciliation
)


def run_phase7_unit_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase7PaperJournalPerformance)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Phase 7 test failures"

def run_phase8_unit_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase8BacktestingAndValidation)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Phase 8 test failures"

def run_phase9_unit_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase9CTraderExecution)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Phase 9 test failures"

def run_phase10_unit_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase10LiveSafetyAndAutonomousIntegration)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Phase 10 test failures"

def run_ctrader_openapi_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCTraderOpenAPI)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "cTrader Open API Protobuf test failures"

from tests.test_production_hardening_and_integrity import ProductionHardeningAndIntegrityTests
from tests.test_phase2_hardening import TestPhase2CoreHardening
from tests.test_phase3_soak import TestPhase3DemoSoakValidation
from tests.test_broker_provenance_integrity import TestBrokerProvenanceIntegrity
from tests.test_phase6_source_integrity import TestPhase6SourceIntegrity
from tests.test_broker_reconciliation import TestBrokerReconciliation, TestAutoTradePersistence
from tests.test_broker_telemetry import TestBrokerTelemetry

def run_broker_reconciliation_tests():
    suite = unittest.TestSuite([
        unittest.TestLoader().loadTestsFromTestCase(TestBrokerReconciliation),
        unittest.TestLoader().loadTestsFromTestCase(TestAutoTradePersistence),
        unittest.TestLoader().loadTestsFromTestCase(TestBrokerTelemetry),
    ])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Broker reconciliation and settings regression failures"

def run_production_hardening_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(ProductionHardeningAndIntegrityTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Production hardening and integrity test failures"

def run_phase2_core_hardening_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase2CoreHardening)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Phase 2 core hardening and safety verification test failures"

def run_phase3_soak_validation_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase3DemoSoakValidation)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Phase 3 demo soak validation test failures"

def run_phase6_source_integrity_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPhase6SourceIntegrity)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Phase 6 source-integrity regression failures"

def run_broker_provenance_integrity_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBrokerProvenanceIntegrity)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), "Broker provenance and data integrity test failures"

def main():
    tests = [
        ("Broker snapshots, DEMO/LIVE reconciliation and auto-trade persistence", run_broker_reconciliation_tests),
        ("Phase 1: Windows DPAPI & Secure Credential Store", test_dpapi_credential_store),
        ("Phase 1: Structured Logger & Secret Masking Filter", test_secret_masking_logger),
        ("Phase 1: Expanded Database Schema & Auto-Migrations", test_expanded_database_schema),
        ("Phase 1: Emergency Kill Switch & Safety Block", test_emergency_kill_switch_blocks_trade),
        ("Phase 2 Core: Agent Criticality, Constants Provenance, Idempotency & Zero-Tolerance Matrix", run_phase2_core_hardening_tests),
        ("Phase 3 Soak: Demo Enforcement, Traceability, Evidence Chain, Reconciliation & Safety Counters", run_phase3_soak_validation_tests),
        ("Phase 6 Source Integrity: Candidate Gates, Demo Lock & Broker-Confirmed Execution", run_phase6_source_integrity_tests),
        ("Broker Provenance: Strict Provenance Isolation, Fail-Closed Queries & Formula Accuracy", run_broker_provenance_integrity_tests),
        ("Phase 2: Dynamic Symbol Resolver & Contract Specs", test_dynamic_symbol_resolver),


        ("Phase 2: Open API Token Bucket Rate Limiter", test_ctrader_openapi_rate_limiter),
        ("Phase 2: Real-Time Market Data Engine & Trendbars", test_ctrader_market_data_engine),
        ("Phase 2: OAuth Token Refresh Lifecycle & Vault", test_token_refresh_lifecycle),
        ("Phase 3: Technical Indicators Suite (RSI, MACD, BB, ATR, ADX, Pivots)", test_technical_indicators_suite),
        ("Phase 3: Smart Money Concepts (BOS, FVG, OB, Sweeps, Premium/Discount)", test_smart_money_concepts_suite),
        ("Phase 3: Multi-Timeframe Confluence Engine (D1/H4/H1/M15/M5)", test_multi_timeframe_confluence_engine),
        ("Phase 4: Economic Calendar & FOMC/CPI Lockout Windows", test_economic_calendar_and_lockout_windows),
        ("Phase 4: Post-News Volatility & Spread Normalization Guard", test_spread_normalization_guard),
        ("Phase 4: Financial NLP News & Polarity Sentiment Engine", test_financial_nlp_news_sentiment_engine),
        ("Phase 4: Calendar & News REST API Endpoints", test_phase4_api_endpoints),
        ("Phase 5: 6-Agent Weighted Consensus Decision Pipeline", test_7_agents_weighted_consensus_approval),
        ("Phase 5: Non-Negotiable Risk & Guardian Veto Overrides", test_hard_risk_veto_overrides_consensus),
        ("Phase 5: Decision DNA Snapshot Persistence & Query API", test_decision_dna_persistence_and_retrieval),
        ("Phase 5: Bilingual Urdu & English Explainability Engine", test_bilingual_explainability_synthesis),
        ("Phase 6: Dynamic Position Sizing & Contract Specifications", test_dynamic_position_sizing_standard_account),
        ("Phase 6: Micro-Account Position Sizing Floor & Clamp", test_dynamic_position_sizing_micro_account),
        ("Phase 6: Daily Drawdown Circuit Breaker & Safety Lock", test_daily_drawdown_circuit_breaker),
        ("Phase 6: Consecutive Loss Cooldown & Manual Breaker Reset", test_consecutive_losses_cooldown_and_reset),
        ("Phase 6: Risk Management Telemetry & Position Calc REST APIs", test_risk_api_endpoints),
        ("Phase 7: Paper Trading Engine & Real-Time Tick Matching", run_phase7_unit_tests),
        ("Phase 8: Strategy Backtest, Walk-Forward WFE & Monte Carlo Engine", run_phase8_unit_tests),
        ("Phase 9: cTrader Order Execution, Modify SL/TP & Partial Closes", run_phase9_unit_tests),
        ("Phase 10: Live Safety Gatekeeper, Emergency Kill Switch & Autonomous Loop", run_phase10_unit_tests),
        ("Production Hardening: Price Integrity, Dynamic 1R, Noise Regression & Anti-Flip", run_production_hardening_tests),
        ("Risk Agent: Passes Valid Gold Trade", test_risk_agent_passes_valid_gold_trade),
        ("Risk Agent: Vetoes Insufficient R:R", test_risk_agent_vetoes_insufficient_rr),
        ("Risk Agent: Vetoes Circuit Breaker", test_risk_agent_vetoes_circuit_breaker),
        ("Pair & Lot: Dynamic Selector & Lot Stepper", test_dynamic_pair_settings_and_lot_controls),
        ("6 Agents: Complete Consensus Pipeline", test_all_6_agents_evaluate_valid_setup),
        ("cTrader Cloud: Server-Side Open API Execution", test_ctrader_cloud_order_execution),
        ("cTrader Open API: Wire Protocol & Framing", run_ctrader_openapi_tests),
        ("No-Trade Guardian: High Spread Blocker", test_guardian_blocks_high_spread),
        ("No-Trade Guardian: High Impact News Blocker", test_guardian_blocks_upcoming_news),
        ("Webhook Security: Valid Token Authorization", test_webhook_security_valid_token),
        ("Webhook Security: Invalid Token Rejection", test_webhook_security_invalid_token),
        ("Strategy Lab: Backtesting Engine Execution", test_strategy_lab_backtest_execution),
        ("PreTrade Engine: Smart Money Swing Points & Structure", test_smart_money_engine_swing_points),
        ("PreTrade Engine: Fair Value Gap (FVG) Imbalance Detection", test_smart_money_engine_fvg_detection),
        ("PreTrade Engine: Order Block (OB) & Mitigation Status", test_smart_money_engine_order_blocks),
        ("PreTrade Engine: Premium vs Discount Dealing Range", test_smart_money_engine_premium_discount),
        ("PreTrade Engine: Session Engine (Asian/London/NY/Overlap)", test_session_engine),
        ("PreTrade Engine: Institutional Setup Classifier (8 Types)", test_setup_classifier),
        ("PreTrade Engine: Trade Quality Scorer (0-100 Scale)", test_trade_quality_scorer),
        ("PreTrade Engine: Fail-Closed Gate on Missing Market Data", test_pretrade_intelligence_fail_closed_on_missing_feed),
        ("Loss Remediation: Inverted BUY SL/TP Strictly VETOED", test_strict_sltp_geometry_buy_inverted),
        ("Loss Remediation: Inverted SELL SL/TP Strictly VETOED", test_strict_sltp_geometry_sell_inverted),
        ("Loss Remediation: Sub-Minimum SL Buffer (< $3.50) VETOED", test_strict_sltp_minimum_buffer_too_tight),
        ("Loss Remediation: Valid Order SL/TP Buffer Passed", test_strict_sltp_valid_order_passes),
        ("Loss Remediation: No Premature Loss Closes on AI Bias Change", test_position_sentinel_no_premature_reversal_close),
        ("Loss Remediation: Authoritative Broker State Reconciliation", test_state_reconciliation),
    ]



    print("==================================================")
    print("      TRADETALK V2 - AUTOMATED TEST RUNNER        ")
    print("==================================================")
    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            test_fn()
            print(f" [PASS] {name}")
            passed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f" [FAIL] {name} -> {e}")
            failed += 1

    print("==================================================")
    print(f" Total: {len(tests)} | Passed: {passed} | Failed: {failed}")
    print("==================================================")

    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
