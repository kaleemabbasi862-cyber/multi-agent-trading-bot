# TradeTalk V2 — Architecture & System Design Document

## Executive Summary
TradeTalk V2 transforms the existing prototype into an enterprise-grade, risk-first, quantitative multi-agent trading decision and execution platform optimized for XAUUSD (Gold). It is engineered around the core philosophy: **"Trade less, trade better."**

---

## 1. Existing System Audit (V1 Baseline)

### 1.1 Architecture & Stack
| Component | Existing V1 Implementation | V2 Target Architecture |
| :--- | :--- | :--- |
| **Frontend** | Single HTML template (`dashboard.html`) using TailwindCSS CDN, FontAwesome, Alpine.js | Enhanced responsive UI with 7-Agent visualizer, Decision DNA inspector, Strategy Lab (Backtesting), Why-Not-Trade panel, and Paper/Demo/Live safety guards |
| **Backend** | FastAPI (`main_native.py`) with Uvicorn, LangChain Google GenAI / Groq integrations | FastAPI modular architecture with decoupled routers, typed services, async execution pipeline |
| **Database** | In-Memory list `SIGNALS_HISTORY` + local JSON `user_settings.json` | Persistent SQLite database with WAL mode, structured relational schema (`signals`, `agent_decisions`, `risk_checks`, `trades`, `market_snapshots`, `performance_metrics`, `decision_dna`, `audit_logs`) and auto-migrations |
| **Execution Modes** | Implicit Demo/Live mixture | Explicit 3-State Model (`PAPER` [Default], `DEMO` [cTrader Demo], `LIVE` [Strict Confirmation & Safety Gate]) |
| **AI Consensus** | 4-agent heuristic / LLM prompt (Tech, News, Risk, Head Desk) | **7-Agent Quantitative Engine** + **No-Trade Guardian** + **Risk Veto Engine** |
| **cTrader Bridge** | Single C# file `TradeTalkBridge.cs` polling `/api/cbot/stream` every 2s | `TradeTalkBridge v2` with HMAC authentication, idempotency, duplicate prevention, state reconciliation, dynamic symbol pip/lot normalization, and fail-safe SL attachment |
| **TradingView Webhook** | Basic unauthenticated JSON POST to `/webhook/tradingview` | Cryptographically verified (HMAC-SHA256 signature / bearer secret), rate-limited, deduplicated, idempotency-keyed webhook gateway |
| **Market Data** | Yahoo Finance (`GC=F`), Binance (`PAXGUSDT`), cBot tick cache | Multi-tier resilient feed with cTrader real-time ticks, Yahoo Finance historical bars, Binance PAXG fallback, data freshness validation (`MAX_MARKET_DATA_AGE`) |
| **News / Macro** | Static rule-based mock in prompt | Economic Calendar provider (investing/forexfactory feed parser + structured high-impact event lockout windows) |
| **Backtesting / Lab**| None | **Strategy Lab** backtesting engine with walk-forward testing, realistic spread/slippage modeling, and overfitting detection |

### 1.2 Identified APIs in V1
- `GET /` (Dashboard HTML)
- `GET /api/market-prices`, `GET /api/live-prices`
- `GET /api/system-state`, `POST /api/auto-trade/toggle`, `GET /POST /api/pairs/settings`, `POST /api/scan-now`
- `GET /api/signals`
- `POST /webhook/tradingview`
- `POST /api/cbot/heartbeat`, `POST /GET /api/cbot/stream`, `GET /api/cbot/orders`, `POST /api/cbot/order-filled`, `POST /api/cbot/close-position`, `GET /api/cbot/status`, `GET /api/cbot/download`
- `GET /api/ctrader/status`, `GET /api/ctrader/auth-url`, `GET /api/ctrader/callback`, `POST /api/ctrader/connect`
- `POST /api/copilot/chat`
- `GET /health`

---

## 2. TradeTalk V2 System Architecture

```mermaid
flowchart TD
    subgraph INGESTION["1. Signal Ingestion & Gateway"]
        TV[TradingView Webhook] --> SEC[HMAC / Secret / Replay Check]
        SCAN[Auto Market Scanner] --> MDV[Market Data Validator]
        SIM[Signal Simulator] --> MDV
        SEC --> MDV
    end

    subgraph ENGINE["2. 7-Agent Quantitative Decision Engine"]
        MDV --> A1[Agent 1: Technical Analyst]
        MDV --> A2[Agent 2: Fundamental & Sentiment]
        MDV --> A3[Agent 3: Risk Management (VETO)]
        MDV --> A4[Agent 4: Market Regime]
        MDV --> A5[Agent 5: Liquidity / SMC]
        MDV --> A6[Agent 6: Trade Quality]
        
        A1 & A2 & A4 & A5 & A6 --> WCE[Weighted Consensus Engine]
        A3 --> RV[Risk Veto Gate]
        
        WCE --> A7[Agent 7: Head Desk Manager]
        RV --> A7
        A7 --> NTG[No-Trade Guardian]
    end

    subgraph PERSISTENCE["3. Persistence & Analytics"]
        NTG --> DNA[Decision DNA Recorder]
        DNA --> DB[(SQLite Database)]
        DB --> PERF[Performance & Calibration Engine]
    end

    subgraph EXECUTION["4. Safe Execution Engine"]
        NTG -->|APPROVED & Risk Pass| EXG{Trading Mode}
        EXG -->|PAPER| PM[Paper Trading Engine]
        EXG -->|DEMO / LIVE| EQ[Execution Queue]
        EQ --> CB[TradeTalkBridge v2 / cTrader]
        CB --> FB[Execution Callback / Reconciliation]
        FB --> DB
    end
```

---

## 3. The 7-Agent Multi-Agent Engine Specifications

### 3.1 Agent 1 — Technical Analyst
- **Timeframes**: Primary: M15 & H1. Secondary context: M5 & H4.
- **Indicators**: EMA (20, 50, 200), RSI (14), ATR (14), Support/Resistance, Market Structure (Higher Highs / Lower Lows).
- **Evaluation**: Trend alignment, pullback depth, breakout validation, momentum divergence.
- **Output**: Direction (`BUY|SELL|NEUTRAL`), Score (`0-100`), Trend, Momentum, Key Levels, Indicators payload.

### 3.2 Agent 2 — Fundamental & Sentiment Agent
- **Data Source**: Economic calendar data & high-impact news schedule (CPI, NFP, FOMC, Fed Rate Decisions, Geopolitical Risk).
- **Safety Window**: `NEWS_PRE_BLOCK_MINUTES = 30`, `NEWS_POST_COOLDOWN_MINUTES = 15`.
- **Classification**: `BULLISH_GOLD`, `BEARISH_GOLD`, `NEUTRAL`, `HIGH_RISK`. During high-risk windows: **NEW TRADES BLOCKED**.

### 3.3 Agent 3 — Risk Management Agent (VETO POWER)
- **Account Health**: Balance, Equity, Free Margin, Open Positions Count, Floating Drawdown.
- **Monetary Sizing**: Dynamic lot calculation based on true broker contract specifications, stop distance in pips/currency, and max risk percent (default $0.40 on micro balance, max 1.0% equity).
- **Mandatory Checks**:
  - Max Open Positions <= 1
  - R:R Ratio >= 2.0
  - Valid broker SL distance (>= 3.0x Spread)
  - Daily Circuit Breaker (-$5.00 limit) not active.
  - Consecutive Loss Limit (2 -> cooldown, 3 -> halt for day).
- **Veto Rule**: If Risk Agent fails, trade decision is unconditionally **`BLOCKED`** or **`REJECTED`**.

### 3.4 Agent 4 — Market Regime Agent
- **Regime Types**: `STRONG_UPTREND`, `WEAK_UPTREND`, `STRONG_DOWNTREND`, `WEAK_DOWNTREND`, `RANGE`, `BREAKOUT`, `HIGH_VOLATILITY`, `LOW_VOLATILITY`, `CHAOTIC`, `NEWS_MARKET`.
- **Suitability Filter**: Rejects trend setups in ranging or chaotic markets; rejects range mean-reversion in strong breakouts.

### 3.5 Agent 5 — Liquidity / Smart Money Agent (SMC)
- **Objective Rules**: Equal Highs/Lows (EQH/EQL), Liquidity Sweeps, Break of Structure (BOS), Change of Character (CHoCH), Order Blocks (OB), Fair Value Gaps (FVG), Premium vs. Discount pricing.
- **Output**: Evidence-based detection records with price coordinates and structural invalidation levels.

### 3.6 Agent 6 — Trade Quality Agent
- **Historical Comparison**: Matches current setup features (session, regime, RSI, EMA slope, R:R, spread) against stored historical trades.
- **Statistical Confidence**: Requires configurable minimum sample size (N >= 20) before heavily weighting historical expectancy.

### 3.7 Agent 7 — Head Desk Manager (Final Decision Arbiter)
- **Weighted Consensus**:
  $$\text{Score} = 0.20(\text{Tech}) + 0.15(\text{Fund}) + 0.15(\text{Regime}) + 0.15(\text{SMC}) + 0.15(\text{Quality}) + 0.20(\text{Risk})$$
- **Decision Hierarchy**:
  - Score >= 90: APPROVED — HIGH QUALITY
  - 85 <= Score < 90: APPROVED — STANDARD
  - 75 <= Score < 85: WATCHLIST / WAIT
  - Score < 75: REJECTED
  - If Risk Veto or No-Trade Guardian triggers: BLOCKED.

---

## 4. No-Trade Guardian (Defense-in-Depth)
Checks 16 critical fail-safe rules prior to execution queue:
1. Spread excessive (> 2.5x normal)
2. Low liquidity / market closed
3. Upcoming high-impact news (< 30 mins)
4. Post-news volatility window (< 15 mins)
5. Timeframe conflict (M15 vs H1)
6. Incompatible market regime
7. Insufficient Risk:Reward (< 2.0)
8. Invalid or missing Stop Loss
9. Daily drawdown / circuit breaker tripped
10. Consecutive loss limit reached
11. Existing open position active
12. Opposing/hedging trade conflict
13. Stale market data (> MAX_MARKET_DATA_AGE)
14. Missing or corrupted market quotes
15. cTrader bridge disconnected (if live/demo mode)
16. Duplicate / replayed signal ID

---

## 5. Database Architecture & Schema (SQLite with WAL)

```sql
-- Signals Table
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    source TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    rr_ratio REAL NOT NULL,
    timeframe TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_score REAL NOT NULL,
    rejection_reason TEXT
);

-- Agent Decisions Table
CREATE TABLE IF NOT EXISTS agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    score REAL NOT NULL,
    direction TEXT NOT NULL,
    decision TEXT NOT NULL,
    reasoning_summary TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);

-- Risk Checks Table
CREATE TABLE IF NOT EXISTS risk_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL,
    account_balance REAL NOT NULL,
    account_equity REAL NOT NULL,
    risk_amount REAL NOT NULL,
    calculated_volume REAL NOT NULL,
    sl_distance REAL NOT NULL,
    tp_distance REAL NOT NULL,
    rr_ratio REAL NOT NULL,
    spread REAL NOT NULL,
    passed INTEGER NOT NULL,
    veto_reason TEXT,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);

-- Trades Table (Live & Paper)
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    mode TEXT NOT NULL, -- 'PAPER', 'DEMO', 'LIVE'
    broker_order_id TEXT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    volume REAL NOT NULL,
    profit_loss REAL,
    pips REAL,
    commission REAL DEFAULT 0.0,
    swap REAL DEFAULT 0.0,
    status TEXT NOT NULL, -- 'OPEN', 'BREAKEVEN', 'CLOSED', 'CANCELLED'
    close_reason TEXT,
    opened_at DATETIME NOT NULL,
    closed_at DATETIME,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);

-- Decision DNA Table (Immutable Record)
CREATE TABLE IF NOT EXISTS decision_dna (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT UNIQUE NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);

-- Strategy Experiments / Backtest Runs
CREATE TABLE IF NOT EXISTS strategy_backtests (
    id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    start_date DATETIME NOT NULL,
    end_date DATETIME NOT NULL,
    initial_balance REAL NOT NULL,
    final_balance REAL NOT NULL,
    total_trades INTEGER NOT NULL,
    win_rate REAL NOT NULL,
    profit_factor REAL NOT NULL,
    max_drawdown REAL NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at DATETIME NOT NULL
);

-- Audit Logs Table
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    details TEXT NOT NULL
);
```

---

## 6. Execution Lifecycle State Machine

```
SIGNAL_RECEIVED -> VALIDATING -> ANALYZING (7 Agents)
               -> RISK_CHECK (Veto Gate) -> APPROVED / REJECTED / BLOCKED
               -> QUEUED -> SENT_TO_CTRADER -> EXECUTED
               -> MONITORING (Auto BE Guard) -> BREAKEVEN -> CLOSED
```

---

## 7. Security & Risk Gates
- **Trading Modes**: Default `PAPER`. Activating `LIVE` requires explicit user confirmation via dialog and valid API secret.
- **Fail-Safe Circuit Breaker**: Auto-halts if daily net loss hits -$5.00 or 3 consecutive losses occur.
- **HMAC Webhook Auth**: Uses `X-TradeTalk-Signature` (HMAC-SHA256) + timestamp header to prevent replay attacks.
- **cBot Dual Handshake**: Tokenized authentication on `/api/cbot/*` endpoints.
