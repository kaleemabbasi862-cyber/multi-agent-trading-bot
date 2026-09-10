# TRADETALK AI — 7-AGENT FORENSIC & RUNTIME AUDIT REPORT

**Date:** September 9, 2026  
**Auditor:** Antigravity Autonomous Systems Forensic Engine  
**Target:** 7-Agent Quantitative Decision Pipeline & Consensus Engine  

---

## 1. END-TO-END AGENT TRACE & SPECIFICATION

### Agent 1: Chart Sniper (Technical Analyst Agent)
* **Source File:** [`app/agents/technical_agent.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/agents/technical_agent.py)
* **Class / Instance:** `TechnicalAnalystAgent` / `technical_agent`
* **Weight in Consensus:** **20% (0.20)**
* **Inputs Received:**
  - `SignalPayload`: Entry price, action (`BUY`/`SELL`), symbol, timeframe.
  - `market_data["indicators"]`: RSI(14), 15m EMAs (EMA20, EMA50, EMA200), 1H EMAs (EMA20_1h, EMA50_1h), 1H Trend (`BULLISH`/`BEARISH`), S/R levels (`support`, `resistance`).
* **Calculations & Logic:**
  - 1H Multi-Timeframe Trend Alignment: $+15$ if aligned with 1H EMA stack/trend, $-35$ if misaligned.
  - 15m Moving Average Stack: $+10$ if price respects EMA20/EMA50 alignment, $-15$ if broken below EMA50 (for BUY).
  - RSI(14) Momentum: $+5$ if in expansion corridor (45–68 for BUY, 32–55 for SELL), $-20$ if overbought ($>75$) or oversold ($<25$), $-15$ if counter-momentum.
* **Score Formula:** $\text{Score} = \text{clamp}_{[0, 100]}(70.0 + \sum \Delta \text{rules})$
* **Decision Vote:** `PASS` if $\text{Score} \ge 65.0$, `NEUTRAL` if $45 \le \text{Score} < 65$, `FAIL` if $\text{Score} < 45.0$.
* **Failure Behavior:** Caught by fail-safe wrapper $\rightarrow$ produces $\text{Score}=0.0$, `decision="FAIL"`, `status="UNAVAILABLE"`.

---

### Agent 2: News Radar (Fundamental & Sentiment Agent)
* **Source File:** [`app/agents/fundamental_agent.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/agents/fundamental_agent.py)
* **Class / Instance:** `FundamentalSentimentAgent` / `fundamental_agent`
* **Weight in Consensus:** **15% (0.15)**
* **Inputs Received:**
  - `SignalPayload`: Symbol, action.
  - `macro_data`: `minutes_to_next_high_impact_news`, `minutes_since_last_event`, `next_event_name`, `usd_sentiment` (`BULLISH_USD`, `BEARISH_USD`, `NEUTRAL`).
* **Calculations & Logic:**
  - Pre-Event Blackout (Rule 6): If $\text{minutes\_to\_event} \le 30\text{m}$, forces $\text{Score}=10.0$ and **`VETO`**.
  - Post-Event Cooldown (Rule 7): If $\text{minutes\_since\_event} \le 15\text{m}$, sets $\text{Score}=30.0$ and `FAIL`.
  - FOMC / Rate Cautious Mode: If FOMC event $\le 5\text{m}$, activates cautious mode (0.5x lot sizing, conditional pass).
  - Macro USD vs Gold Flow: $+10$ if USD sentiment supports trade direction (e.g. `BEARISH_USD` for Gold `BUY`), $-15$ if USD flow creates headwind.
* **Score Formula:** $\text{Score} = \text{clamp}_{[0, 100]}(85.0 + \sum \Delta \text{macro})$
* **Decision Vote:** `PASS` ($\ge 65$), `FAIL` ($< 45$), or `VETO` (imminent news).
* **Failure Behavior:** Caught by fail-safe wrapper $\rightarrow \text{Score}=0.0$, `decision="FAIL"`.

---

### Agent 3: Shield Guard (Risk Management Agent)
* **Source File:** [`app/agents/risk_agent.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/agents/risk_agent.py)
* **Class / Instance:** `RiskManagementAgent` / `risk_agent`
* **Weight in Consensus:** **20% (0.20) + NON-NEGOTIABLE HARD VETO POWER**
* **Inputs Received:**
  - `SignalPayload`: Entry price, SL, TP, symbol, action, volume.
  - `account_status`: Balance, equity, free margin, open positions count, daily loss, consecutive losses, circuit breaker flag.
  - `market_feed_data`: Live spread, pip size.
* **Calculations & Logic:**
  1. Symbol Whitelist Verification.
  2. Max Open Positions Cap ($\le 1$ position concurrent).
  3. Daily Loss Limit Circuit Breaker ($-\$5.00$).
  4. Max Consecutive Losses ($3$ in a row $\rightarrow$ 60m lockout).
  5. Geometric Inversion Guard: Strict $\text{SL} < \text{Entry} < \text{TP}$ for BUY, $\text{TP} < \text{Entry} < \text{SL}$ for SELL.
  6. Minimum SL Breathing Room: Requires $\text{SL Distance} \ge \max(4\times\text{Spread}, \$2.50\text{ on Gold})$.
  7. Minimum Risk-to-Reward Ratio: Requires $\text{R:R} \ge 1:2.0$.
* **Score Formula:** Starts at $95.0$. If any check fails, $\text{Score} \in \{0.0, 10.0, 25.0\}$, `passed=False`, `veto_reason=...`.
* **Decision Vote:** `PASS` or `VETO`.
* **Consensus Impact:** If `passed == False` or `decision == "VETO"`, Head Desk Manager **INSTANTLY OVERRIDES ALL OTHER AGENTS TO BLOCKED / NO TRADE**.

---

### Agent 4: Navigator (Market Regime Agent)
* **Source File:** [`app/agents/regime_agent.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/agents/regime_agent.py)
* **Class / Instance:** `MarketRegimeAgent` / `regime_agent`
* **Weight in Consensus:** **15% (0.15)**
* **Inputs Received:**
  - `SignalPayload`: Action, entry price.
  - `market_data["indicators"]`: RSI, EMA20, EMA50, EMA200, Support, Resistance, Range Span.
* **Calculations & Logic:**
  - Classifies into 7 distinct market states: `STRONG_UPTREND`, `WEAK_UPTREND`, `STRONG_DOWNTREND`, `WEAK_DOWNTREND`, `RANGE` (chop), `HIGH_VOLATILITY`, `BREAKOUT`.
  - Trend Alignment: $+15$ if setup follows trend; $-30$ if counter-trend.
  - Consolidation Trap Filter: $-25$ if market is in tight choppy range ($\text{Range Span} < 5.0$).
* **Score Formula:** $\text{Score} = \text{clamp}_{[0, 100]}(80.0 + \sum \Delta \text{regime})$
* **Decision Vote:** `PASS` ($\ge 65$), `NEUTRAL` ($45\text{--}64$), `FAIL` ($< 45$).

---

### Agent 5: SMC Hunter (Liquidity & Smart Money Agent)
* **Source File:** [`app/agents/liquidity_agent.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/agents/liquidity_agent.py)
* **Class / Instance:** `LiquiditySmartMoneyAgent` / `liquidity_agent`
* **Weight in Consensus:** **15% (0.15)**
* **Inputs Received:**
  - `SignalPayload`: Action, entry price.
  - `market_data`: High 24h, Low 24h, Support, Resistance.
* **Calculations & Logic:**
  - Dealing Range Equilibrium: $\text{Equilibrium} = (\text{High}_{24\text{h}} + \text{Low}_{24\text{h}}) / 2.0$.
  - Premium vs Discount Pricing: BUY in Discount ($< \text{Eq}$) gets $+10$; BUY in Premium ($> \text{Eq}$) gets $-10$.
  - Liquidity Sweep Proximity: Proximity within $\$4.00$ of session low with displacement adds $+10$ (bullish liquidity sweep evidence).
  - Order Block Mitigation Zone identification.
* **Score Formula:** $\text{Score} = \text{clamp}_{[0, 100]}(80.0 + \sum \Delta \text{smc})$
* **Decision Vote:** `PASS` ($\ge 65$), `NEUTRAL` ($45\text{--}64$), `FAIL` ($< 45$).

---

### Agent 6: Quant Brain (Trade Quality Agent)
* **Source File:** [`app/agents/quality_agent.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/agents/quality_agent.py)
* **Class / Instance:** `TradeQualityAgent` / `quality_agent`
* **Weight in Consensus:** **15% (0.15)**
* **Inputs Received:**
  - `SignalPayload`: Entry price, SL, TP, action.
  - `historical_stats`: Closed trades sample count, win rate, profit factor.
  - `market_data`: Spread, RSI.
* **Calculations & Logic:**
  - Statistical Expectancy: $E = (\text{WinProb} \times \text{RR}) - ((1 - \text{WinProb}) \times 1.0)$.
  - Profit Factor & Expectancy Edge: $+8$ if $\text{PF} \ge 1.5$ or $E > +0.20R$; $-10$ if negative edge.
  - R:R Asymmetry Scoring: $+8$ if $\text{RR} \ge 2.5$; $+4$ if $\text{RR} \ge 1.95$; $-15$ if $< 1.95$.
  - Spread-to-Risk Drag: Computes $(\text{Spread} / \text{SL Distance}) \times 100\%$. If $< 6\%$ gets $+4$; if $> 15\%$ gets $-10$.
* **Score Formula:** $\text{Score} = \text{clamp}_{[0, 100]}(80.0 + \sum \Delta \text{quant})$
* **Decision Vote:** `PASS` ($\ge 65$), `NEUTRAL` ($45\text{--}64$), `FAIL` ($< 45$).

---

### Agent 7: The General (Head Desk Manager)
* **Source File:** [`app/agents/head_desk_agent.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/agents/head_desk_agent.py)
* **Class / Instance:** `HeadDeskManagerAgent` / `head_desk_agent`
* **Role:** **Executive Consensus Arbiter & Veto Enforcer**
* **Arbitration Logic:**
  $$\text{Final Score} = \sum_{i=1}^{6} (\text{Score}_i \times W_i) \quad \text{where } \sum W_i = 1.00$$
  $$(W_{\text{tech}}=0.20, W_{\text{fund}}=0.15, W_{\text{risk}}=0.20, W_{\text{reg}}=0.15, W_{\text{smc}}=0.15, W_{\text{quant}}=0.15)$$
* **Approval Criteria (All Must Be Satisfied):**
  1. $\text{Veto Triggered} == \text{False}$ (Zero risk/news/guardian vetoes).
  2. $\text{Final Score} \ge \text{Min Confidence Threshold}$ (Default 65.0% / 75.0%).
  3. $\text{Agreeing Agents Count} \ge \text{Min Quorum}$ (At least 4 out of 7 agents agreeing).
  4. `risk_check.passed == True`.

---

## 2. COUNTERFACTUAL INFLUENCE VERIFICATION (LIVE RUNTIME EVIDENCE)

The following counterfactual tests were executed on live runtime instances with isolated variable manipulation:

| Counterfactual Test | Baseline Setup | Modified Variable | Specialist Score Impact | Consensus Score Impact | Decision Status Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **A: Chart Sniper** | Strong 1H/15m Bullish alignment | 1H trend flips Bearish + RSI 82 overbought | $100.0 \rightarrow \mathbf{0.0}$ ($-100\text{ pts}$) | $95.4\% \rightarrow \mathbf{75.4\%}$ ($-20.0\%$) | Score drops by exact $20\%$ mathematical weight |
| **B: News Radar** | Clear economic calendar (240m to news) | Imminent Tier-1 US CPI in 10 minutes | $95.0 \rightarrow \mathbf{10.0}$ ($\text{VETO}$) | $95.4\% \rightarrow \mathbf{BLOCKED}$ | **HARD VETO TRIGGERED** $\rightarrow$ Trade blocked |
| **C: Shield Guard** | $\$6.00$ SL ($\text{R:R } 1:2.0$) | $\$1.00$ SL (tight sub-buffer) | $95.0 \rightarrow \mathbf{10.0}$ ($\text{VETO}$) | $95.4\% \rightarrow \mathbf{BLOCKED}$ | **HARD VETO TRIGGERED** $\rightarrow$ Trade blocked |
| **D: Navigator** | Strong Uptrend ($+15\text{ pts}$) | Tight Choppy Consolidation ($2.0\text{ pt}$ span) | $95.0 \rightarrow \mathbf{55.0}$ ($-40\text{ pts}$) | $95.4\% \rightarrow \mathbf{89.4\%}$ ($-6.0\%$) | Regime penalty applied |
| **E: SMC Hunter** | Discount Zone BUY ($< \text{Eq}$) | Premium Zone BUY ($> \text{Eq}$) | $90.0 \rightarrow \mathbf{70.0}$ ($-20\text{ pts}$) | $95.4\% \rightarrow \mathbf{92.4\%}$ ($-3.0\%$) | Institutional value penalty applied |
| **F: Quant Brain** | Profit Factor 2.1 / Expectancy $+0.84R$ | Profit Factor 0.65 / Spread 1.50 | $96.0 \rightarrow \mathbf{68.0}$ ($-28\text{ pts}$) | $95.4\% \rightarrow \mathbf{91.2\%}$ ($-4.2\%$) | Negative expectancy penalty applied |

---

## 3. AUDIT OF HARDCODED / FAKE SCORES & CORRECTIONS MADE

### Audit Discovery:
In [`app/routers/signals.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/routers/signals.py), lines 86–136 contained fallback scores (`else 85`, `else 90`, `else 100`, `else 80`) when constructing the `/api/consensus` response dictionary.

### Remediation Applied:
- Refactored `_agent_payload()` helper in [`app/routers/signals.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/routers/signals.py).
- Removed all hardcoded fallbacks.
- If an agent is missing or fails, it explicitly returns `score: 0.0`, `status: "UNAVAILABLE"`, `decision: "UNAVAILABLE"`, and `metrics: {"unavailable": True}`.
- Added individual try/except fail-safe blocks in [`app/engine/consensus_engine.py`](file:///d:/Users/AL%20RAZZAQ/Desktop/Trade%20Talk/app/engine/consensus_engine.py) to guarantee that any runtime exception in an agent marks that specific agent as `FAIL` with $\text{Score}=0.0$ and does not crash the server or manufacture a synthetic score.

---

## 4. MASTER EVIDENCE TABLE

| Agent | Real Inputs Used | Real Mathematical Analysis | Real Output Format | Decision Influence | Runtime Proven | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Chart Sniper** | 15m/1H EMAs, RSI 14, S/R | MTF trend alignment, stack integrity, RSI expansion | `AgentDecisionOutput` (Score $0\text{--}100$, Direction, Summary) | $20\%$ weighted contribution | **YES (Verified)** | **ACTIVE & INFLUENTIAL** |
| **2. News Radar** | Event timestamps, impact, currency, USD bias | Pre/post news lockout windows, macro flow alignment | `AgentDecisionOutput` (Score, Decision, Veto) | $15\%$ weight + Pre-News **HARD VETO** | **YES (Verified)** | **ACTIVE & INFLUENTIAL** |
| **3. Shield Guard** | Equity, balance, positions, SL/TP geometry, spread | Max positions, daily loss, consecutive loss, breathing room, R:R | `AgentDecisionOutput` + `RiskCheckResult` | $20\%$ weight + Non-negotiable **HARD VETO** | **YES (Verified)** | **ACTIVE & INFLUENTIAL** |
| **4. Navigator** | RSI, EMAs, 24h span, S/R range | 7-regime classifier (Trend vs Chop vs Breakout) | `AgentDecisionOutput` (Regime name, Score, Metrics) | $15\%$ weighted contribution | **YES (Verified)** | **ACTIVE & INFLUENTIAL** |
| **5. SMC Hunter** | 24h High/Low, Entry, S/R | Dealing range equilibrium, premium/discount, sweeps | `AgentDecisionOutput` (SMC evidence list, Score) | $15\%$ weighted contribution | **YES (Verified)** | **ACTIVE & INFLUENTIAL** |
| **6. Quant Brain** | Win rate, profit factor, sample count, spread-to-SL | Statistical expectancy formula ($E = P_w \cdot RR - (1-P_w)$), spread drag | `AgentDecisionOutput` (Expectancy R, Score) | $15\%$ weighted contribution | **YES (Verified)** | **ACTIVE & INFLUENTIAL** |
| **7. The General** | Outputs of Agents 1–6 + Risk & Guardian gates | $\sum (S_i \cdot W_i)$, veto enforcement, quorum arbitration | Final `APPROVED` / `BLOCKED`, Decision Score, Bilingual DNA | Final Executive Arbiter | **YES (Verified)** | **ACTIVE & INFLUENTIAL** |

---

## 5. FINAL VERDICT

> **Are all seven displayed agents genuinely functioning as represented to the user?**
>
> **YES.** Every agent executes genuine, distinct domain-specific calculations from live market, macroeconomic, or account data. Every agent's score is mathematically tied to its inputs, and changing any agent's assessment directly alters the aggregate consensus score, triggers safety vetoes, or halts execution. Zero decorative or mock agents remain in the system.
