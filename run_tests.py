import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from tests.test_risk_calculations import (
    test_risk_agent_passes_valid_gold_trade,
    test_risk_agent_vetoes_insufficient_rr,
    test_risk_agent_vetoes_circuit_breaker
)
from tests.test_7_agents import test_all_7_agents_evaluate_valid_setup
from tests.test_guardian import test_guardian_blocks_high_spread, test_guardian_blocks_upcoming_news
from tests.test_webhook_security import test_webhook_security_valid_token, test_webhook_security_invalid_token
from tests.test_backtester import test_strategy_lab_backtest_execution

def main():
    tests = [
        ("Risk Agent: Passes Valid Gold Trade", test_risk_agent_passes_valid_gold_trade),
        ("Risk Agent: Vetoes Insufficient R:R", test_risk_agent_vetoes_insufficient_rr),
        ("Risk Agent: Vetoes Circuit Breaker", test_risk_agent_vetoes_circuit_breaker),
        ("7 Agents: Complete Consensus Pipeline", test_all_7_agents_evaluate_valid_setup),
        ("No-Trade Guardian: High Spread Blocker", test_guardian_blocks_high_spread),
        ("No-Trade Guardian: High Impact News Blocker", test_guardian_blocks_upcoming_news),
        ("Webhook Security: Valid Token Authorization", test_webhook_security_valid_token),
        ("Webhook Security: Invalid Token Rejection", test_webhook_security_invalid_token),
        ("Strategy Lab: Backtesting Engine Execution", test_strategy_lab_backtest_execution),
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
            print(f" [FAIL] {name} -> {e}")
            failed += 1

    print("==================================================")
    print(f" Total: {len(tests)} | Passed: {passed} | Failed: {failed}")
    print("==================================================")

    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
