# TradeTalk V2 — Testing & QA Guide

## Test Suite Execution
Execute the automated test runner:
```bash
python run_tests.py
```

## Coverage
1. **Risk Calculations & Veto**: Validates monetary risk formulas, mandatory SL/TP bounds, $1:2.0$ R:R limits, and circuit breakers.
2. **7-Agent Quantitative Pipeline**: Tests all 7 agents and Head Desk arbitration.
3. **No-Trade Guardian**: Tests spread surges, economic calendar lockout windows, and duplicate signal rejections.
4. **Webhook Security**: Tests token authorization, HMAC signatures, and expired timestamps.
5. **Strategy Lab Backtester**: Validates simulation execution, slippage deduction, and metrics calculation.
