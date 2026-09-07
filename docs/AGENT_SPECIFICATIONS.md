# TradeTalk V2 — Agent Specifications

## Architecture Overview
TradeTalk V2 utilizes a 7-agent quantitative decision hierarchy governed by a weighted scoring arbiter and a non-negotiable Risk Veto gate.

---

## Agent Specifications

### 1. Technical Analyst Agent (`app/agents/technical_agent.py`)
- **Weight**: 20%
- **Timeframes**: Primary: M15 and H1.
- **Indicators**: EMA (20, 50, 200), RSI (14), Support/Resistance levels.
- **Rules**:
  - Requires 1H Multi-Timeframe Trend alignment ($15\text{m BUY} \implies \text{EMA 20} > \text{EMA 50}$ on 1H).
  - Momentum validation: RSI 14 must be in expansion zone (45–68 for BUY, 32–55 for SELL).

### 2. Fundamental & Sentiment Agent (`app/agents/fundamental_agent.py`)
- **Weight**: 15%
- **Data Source**: Economic calendar & macroeconomic events schedule.
- **Lockout Windows**:
  - `NEWS_PRE_BLOCK_MINUTES = 30`: Blocks all entries 30 mins prior to Tier-1 news (CPI, NFP, FOMC).
  - `NEWS_POST_COOLDOWN_MINUTES = 15`: 15-minute post-event cooldown.

### 3. Risk Management Agent (`app/agents/risk_agent.py`)
- **Weight**: 20%
- **Power**: **UNCONDITIONAL VETO POWER**
- **Rules**:
  - Sizing: Exactly 0.01 micro-lot fixed on micro equity.
  - Max Open Positions: $\le 1$ position across entire account.
  - Guaranteed Stop Loss: Distance must exceed $3.0\times \text{Spread}$ and at least 40 pips (\$0.40).
  - Risk-to-Reward: Minimum $1:2.0$ hardcoded.
  - Daily Loss Circuit Breaker: $-\$5.00$ daily net loss limit.

### 4. Market Regime Agent (`app/agents/regime_agent.py`)
- **Weight**: 15%
- **Classifications**: `STRONG_UPTREND`, `WEAK_UPTREND`, `STRONG_DOWNTREND`, `WEAK_DOWNTREND`, `RANGE`, `BREAKOUT`, `HIGH_VOLATILITY`.
- **Rules**: Rejects trend-following setups during tight ranging or chaotic chop.

### 5. Liquidity & Smart Money Concepts Agent (`app/agents/liquidity_agent.py`)
- **Weight**: 15%
- **Analysis**: Premium vs. Discount pricing, Order Block (OB) mitigation, Liquidity Sweeps of Day's High/Low (PDH/PDL), Fair Value Gaps (FVG).

### 6. Trade Quality Agent (`app/agents/quality_agent.py`)
- **Weight**: 15%
- **Statistical Safeguard**: Enforces minimum sample size threshold ($N \ge 20$) before heavily weighting historical expectancy.

### 7. Head Desk Manager (`app/agents/head_desk_agent.py`)
- **Weight**: Executive Arbiter (Weighted Consensus)
- **Scoring**:
  $$\text{Score} = 0.20(\text{Tech}) + 0.15(\text{Fund}) + 0.15(\text{Regime}) + 0.15(\text{SMC}) + 0.15(\text{Quality}) + 0.20(\text{Risk})$$
- **Decision Buckets**:
  - $\ge 90\% \implies \text{APPROVED — HIGH QUALITY}$
  - $85\% - 89.9\% \implies \text{APPROVED — STANDARD}$
  - $75\% - 84.9\% \implies \text{WATCHLIST / WAIT}$
  - $< 75\% \implies \text{REJECTED}$
  - Risk Failure or Guardian Trigger $\implies \mathbf{BLOCKED}$.
