# TRADETALK AI — PHASE 3 SOAK BASELINE MANIFEST

**Manifest ID:** `SOAK_BASELINE_MANIFEST_V2_20260909`  
**Creation Date:** `2026-09-09T22:25:30+03:00`  
**Git Commit:** `6cc3ac38551d10a90f5308f966936ba8f1dc9d14`  
**Application Version:** `2.0.0-PROD-HARDENED`  
**Strategy Version:** `Gold_Sniper_SMC_v2.0`  
**Configuration Version:** `2.0.0-PROD-HARDENED`  
**Database Schema Version:** `2.0.0-WAL-MIGRATED`  

---

## 1. BROKER & ACCOUNT SPECIFICATION

* **Trading Mode:** `DEMO` (Real money execution strictly blocked)
* **Broker:** Spotware cTrader Open API / Local Bridge
* **Broker Account ID:** `#5908018`
* **Account Environment:** `Demo`
* **Currency:** `USD`
* **Starting Balance:** `$1018.96`
* **Starting Equity:** `$1018.96`

---

## 2. INSTRUMENT & TIMEFRAME CONFIGURATION

* **Primary Symbol:** `XAUUSD` (Spot Gold / USD)
* **Execution Timeframe:** `15m`
* **Macro Confluence Timeframes:** `H1`, `D1`
* **Price Decimals:** `2` ($0.01 precision)
* **Minimum Order Increment:** `0.01 Lots` (1 oz)

---

## 3. MULTI-AGENT QUANTITATIVE WEIGHTS

| Agent Name | Operational Role | Criticality Tier | Quantitative Weight | Conviction Threshold |
| :--- | :--- | :--- | :---: | :---: |
| **Shield Guard** (`RiskManagementAgent`) | Capital Preservation, SL/TP Geometry, 1R | `SAFETY_CRITICAL` | `0.20` | Veto Gatekeeper |
| **News Radar** (`FundamentalSentimentAgent`)| Macro Calendar, CPI/FOMC/NFP Blackout | `SAFETY_CRITICAL` | `0.15` | $\ge 65.0\%$ |
| **The General** (`HeadDeskManagerAgent`) | Consensus Arbitration & Quorum Arbiter | `SAFETY_CRITICAL` | `Arbiter` | Supermajority $\ge 4/7$ |
| **Chart Sniper** (`TechnicalAnalystAgent`) | MTF Moving Averages, Momentum Corridors | `DECISION_CRITICAL` | `0.20` | $\ge 65.0\%$ |
| **SMC Hunter** (`LiquiditySmartMoneyAgent`) | FVG Imbalance, Dealing Ranges, Order Blocks | `DECISION_CRITICAL` | `0.15` | $\ge 65.0\%$ |
| **Navigator** (`MarketRegimeAgent`) | 7-State Regime Classifier, Volatility State | `DECISION_CRITICAL` | `0.15` | $\ge 65.0\%$ |
| **Quant Brain** (`TradeQualityAgent`) | Mathematical Expectancy, Friction Ratio | `DECISION_CRITICAL` | `0.15` | $\ge 65.0\%$ |

---

## 4. NON-NEGOTIABLE SAFETY POLICIES

* **Max Risk per Trade:** `1.0%` of account equity
* **Daily Drawdown Limit:** `$5.00`
* **Max Consecutive Losses:** `3` (triggers 60m cooldown)
* **Max Concurrent Positions:** `1` (Single-position allocation)
* **Max Autonomous Lot Size:** `0.05 Lots`
* **Minimum Stop-Loss Buffer:** `$2.50` ($25\text{ pips}$)
* **Minimum Reward-to-Risk:** `1:2.0`
* **Pre-News Blackout Window:** `30 Minutes` before high-impact event
* **Post-News Cooldown Window:** `15 Minutes` post-event
* **Anti-Flip Cooldown Window:** `60 Seconds` post-trade close
* **Market Tick Freshness Threshold:** `5.0 Seconds`

---

## 5. VALIDATION CONSTRAINTS

1. **Frozen Parameters:** No trading constants, weights, or safety thresholds may be modified during an active soak segment.
2. **Fail-Closed Rule:** If broker state, tick feed freshness, or critical agent status is uncertain $\rightarrow$ `DO NOT TRADE`.
3. **Evidence Integrity:** Every evaluation must generate a unique `decision_id` and complete decision trace in SQLite `decision_dna`.
