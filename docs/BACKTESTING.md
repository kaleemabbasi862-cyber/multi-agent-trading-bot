# TradeTalk V2 — Strategy Lab & Quantitative Backtester

## Overview
The Strategy Lab engine (`app/engine/backtester.py`) runs realistic historical walk-forward simulations on XAUUSD Gold without look-ahead bias or data leakage.

---

## 1. Simulation Features
- **Spread Cost Modeling**: Simulates real broker bid/ask spreads (default 3.5 pips / \$0.35 on Gold).
- **Slippage Modeling**: Adds dynamic slippage on market entry and stop-loss fills.
- **Commission & Swap**: Deducts broker round-turn commissions (\$0.06 on 0.01 lot).
- **Overfitting Safeguards**: Rejects statistical claims if sample size $N < 20$.

---

## 2. Key Output Metrics
- **Total Trades**: Number of closed positions in simulation.
- **Win Rate (%)**: Percentage of profitable trades.
- **Profit Factor**: Gross Profit / Gross Loss.
- **Expectancy**: Expected dollar return per trade.
- **Max Drawdown (\$ / %)**: Peak-to-trough capital decline.
- **Equity Curve**: Time-series equity curve array.
