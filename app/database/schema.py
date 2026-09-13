import sqlite3
import logging

logger = logging.getLogger("TradeTalk.DB.Schema")

SCHEMA_STATEMENTS = [
    # 1. Users / Profile
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'TRADER',
        created_at TEXT NOT NULL
    );
    """,

    # 2. System Settings
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'GENERAL',
        updated_at TEXT NOT NULL
    );
    """,

    # 3. Broker Accounts
    """
    CREATE TABLE IF NOT EXISTS broker_accounts (
        account_id TEXT PRIMARY KEY,
        broker_name TEXT NOT NULL,
        account_type TEXT NOT NULL, -- 'DEMO' or 'LIVE'
        environment TEXT NOT NULL,   -- 'Demo' or 'Live'
        currency TEXT NOT NULL DEFAULT 'USD',
        balance REAL NOT NULL DEFAULT 0.0,
        equity REAL NOT NULL DEFAULT 0.0,
        margin REAL NOT NULL DEFAULT 0.0,
        free_margin REAL NOT NULL DEFAULT 0.0,
        is_active INTEGER NOT NULL DEFAULT 0,
        last_synced_at TEXT
    );
    """,

    # 4. Symbols & Contract Specs
    """
    CREATE TABLE IF NOT EXISTS symbols (
        symbol_id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        base_asset TEXT NOT NULL,
        quote_asset TEXT NOT NULL,
        digits INTEGER NOT NULL DEFAULT 2,
        pip_size REAL NOT NULL DEFAULT 0.01,
        min_volume REAL NOT NULL DEFAULT 0.01,
        max_volume REAL NOT NULL DEFAULT 100.0,
        volume_step REAL NOT NULL DEFAULT 0.01,
        lot_size REAL NOT NULL DEFAULT 100.0,
        is_trading_enabled INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    );
    """,

    # 5. Candles
    """
    CREATE TABLE IF NOT EXISTS candles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL DEFAULT 0.0,
        UNIQUE(symbol, timeframe, timestamp)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_candles_lookup ON candles(symbol, timeframe, timestamp);",

    # 6. Indicators Cache
    """
    CREATE TABLE IF NOT EXISTS indicators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        name TEXT NOT NULL,
        value REAL NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_indicators_lookup ON indicators(symbol, timeframe, name);",

    # 7. Signals (Original & Extended)
    """
    CREATE TABLE IF NOT EXISTS signals (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
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
        rejection_reason TEXT,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);",
    "CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);",

    # 8. Market Signals & AI Signals
    """
    CREATE TABLE IF NOT EXISTS market_signals (
        id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        price REAL NOT NULL,
        indicators_json TEXT,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_signals (
        id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        consensus_direction TEXT NOT NULL,
        confidence REAL NOT NULL,
        agent_scores_json TEXT NOT NULL,
        risk_score REAL NOT NULL,
        reasoning TEXT NOT NULL,
        invalidation_level REAL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(signal_id) REFERENCES signals(id)
    );
    """,

    # 9. Agent Decisions (5 Specialist Agents + Head Desk)
    """
    CREATE TABLE IF NOT EXISTS agent_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT NOT NULL,
        agent_name TEXT NOT NULL,
        score REAL NOT NULL,
        direction TEXT NOT NULL,
        decision TEXT NOT NULL,
        reasoning_summary TEXT NOT NULL,
        metrics_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(signal_id) REFERENCES signals(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_decisions_signal ON agent_decisions(signal_id);",
    "CREATE INDEX IF NOT EXISTS idx_agent_decisions_name ON agent_decisions(agent_name);",

    # 10. Risk Checks & Risk Events
    """
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
        created_at TEXT NOT NULL,
        FOREIGN KEY(signal_id) REFERENCES signals(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_risk_checks_signal ON risk_checks(signal_id);",
    """
    CREATE TABLE IF NOT EXISTS risk_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        event_type TEXT NOT NULL, -- 'CIRCUIT_BREAKER', 'MAX_DRAWDOWN', 'HIGH_SPREAD', 'NEWS_LOCKOUT'
        account_id TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'WARNING',
        details TEXT NOT NULL
    );
    """,

    # 11. Economic Events
    """
    CREATE TABLE IF NOT EXISTS economic_events (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        currency TEXT NOT NULL,
        country TEXT NOT NULL,
        event_name TEXT NOT NULL,
        impact TEXT NOT NULL, -- 'LOW', 'MEDIUM', 'HIGH', 'EXTREME'
        actual TEXT,
        forecast TEXT,
        previous TEXT,
        affected_symbols TEXT,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_economic_events_time ON economic_events(timestamp);",

    # 12. News & Sentiment
    """
    CREATE TABLE IF NOT EXISTS news (
        id TEXT PRIMARY KEY,
        headline TEXT NOT NULL,
        source TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'FOREX',
        sentiment TEXT NOT NULL DEFAULT 'NEUTRAL', -- 'STRONG_BULLISH', 'BULLISH', 'NEUTRAL', 'BEARISH', 'STRONG_BEARISH'
        sentiment_score REAL NOT NULL DEFAULT 0.0,
        affected_symbols TEXT,
        created_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_time ON news(timestamp);",

    # 13. Orders, Positions, Deals
    """
    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        broker_order_id TEXT,
        signal_id TEXT,
        account_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        order_type TEXT NOT NULL, -- 'MARKET', 'LIMIT', 'STOP'
        trade_side TEXT NOT NULL,  -- 'BUY', 'SELL'
        requested_volume REAL NOT NULL,
        executed_volume REAL DEFAULT 0.0,
        price REAL,
        stop_loss REAL,
        take_profit REAL,
        status TEXT NOT NULL,      -- 'PENDING', 'FILLED', 'REJECTED', 'CANCELLED'
        rejection_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        position_id TEXT PRIMARY KEY,
        broker_position_id TEXT,
        signal_id TEXT,
        account_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        volume REAL NOT NULL,
        entry_price REAL NOT NULL,
        current_price REAL NOT NULL,
        stop_loss REAL NOT NULL,
        take_profit REAL NOT NULL,
        unrealized_pnl REAL DEFAULT 0.0,
        realized_pnl REAL DEFAULT 0.0,
        swap REAL DEFAULT 0.0,
        commission REAL DEFAULT 0.0,
        status TEXT NOT NULL, -- 'OPEN', 'CLOSED'
        opened_at TEXT NOT NULL,
        closed_at TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS deals (
        deal_id TEXT PRIMARY KEY,
        position_id TEXT NOT NULL,
        broker_deal_id TEXT,
        account_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        trade_side TEXT NOT NULL,
        volume REAL NOT NULL,
        execution_price REAL NOT NULL,
        pnl REAL DEFAULT 0.0,
        commission REAL DEFAULT 0.0,
        swap REAL DEFAULT 0.0,
        executed_at TEXT NOT NULL
    );
    """,

    # 14. Trades (Unified Master Table)
    """
    CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL,
        mode TEXT NOT NULL, -- 'PAPER', 'DEMO', 'LIVE'
        broker_order_id TEXT,
        ticket_id TEXT,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        entry_price REAL NOT NULL,
        exit_price REAL,
        stop_loss REAL NOT NULL,
        take_profit REAL NOT NULL,
        volume REAL NOT NULL,
        profit_loss REAL DEFAULT 0.0,
        pips REAL DEFAULT 0.0,
        commission REAL DEFAULT 0.0,
        swap REAL DEFAULT 0.0,
        status TEXT NOT NULL,
        close_reason TEXT,
        opened_at TEXT NOT NULL,
        closed_at TEXT,
        FOREIGN KEY(signal_id) REFERENCES signals(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);",
    "CREATE INDEX IF NOT EXISTS idx_trades_mode ON trades(mode);",

    # 15. Trade Journal (Detailed Post-Trade Analytics)
    """
    CREATE TABLE IF NOT EXISTS trade_journal (
        id TEXT PRIMARY KEY,
        trade_id TEXT UNIQUE NOT NULL,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        market_regime TEXT,
        mfe REAL DEFAULT 0.0, -- Maximum Favorable Excursion (Pips)
        mae REAL DEFAULT 0.0, -- Maximum Adverse Excursion (Pips)
        trade_duration_seconds INTEGER DEFAULT 0,
        news_context TEXT,
        ai_reasoning TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(trade_id) REFERENCES trades(id)
    );
    """,

    # 16. Decision DNA
    """
    CREATE TABLE IF NOT EXISTS decision_dna (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT UNIQUE NOT NULL,
        snapshot_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(signal_id) REFERENCES signals(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_dna_signal ON decision_dna(signal_id);",

    # 17. Market Snapshots
    """
    CREATE TABLE IF NOT EXISTS market_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        symbol TEXT NOT NULL,
        bid REAL NOT NULL,
        ask REAL NOT NULL,
        spread REAL NOT NULL,
        price REAL NOT NULL,
        indicators_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,

    # 18. Strategy Performance & Backtest Runs
    """
    CREATE TABLE IF NOT EXISTS strategy_backtests (
        id TEXT PRIMARY KEY,
        strategy_name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        initial_balance REAL NOT NULL,
        final_balance REAL NOT NULL,
        total_trades INTEGER NOT NULL,
        win_rate REAL NOT NULL,
        profit_factor REAL NOT NULL,
        max_drawdown REAL NOT NULL,
        metrics_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS strategy_performance (
        strategy_name TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        total_signals INTEGER DEFAULT 0,
        approved_trades INTEGER DEFAULT 0,
        winning_trades INTEGER DEFAULT 0,
        losing_trades INTEGER DEFAULT 0,
        win_rate REAL DEFAULT 0.0,
        profit_factor REAL DEFAULT 1.0,
        net_profit REAL DEFAULT 0.0,
        sharpe_ratio REAL DEFAULT 0.0,
        last_evaluated_at TEXT
    );
    """,

    # 19. Audit Logs & System Logs
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        event_type TEXT NOT NULL,
        actor TEXT NOT NULL,
        details TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        level TEXT NOT NULL,
        module TEXT NOT NULL,
        message TEXT NOT NULL,
        correlation_id TEXT
    );
    """,

    # 20. Execution Intent Idempotency Lock Table (Phase 2 Hardening)
    """
    CREATE TABLE IF NOT EXISTS execution_intents (
        intent_id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        action TEXT NOT NULL,
        volume REAL NOT NULL,
        entry_price REAL NOT NULL,
        sl_price REAL NOT NULL,
        tp_price REAL NOT NULL,
        status TEXT NOT NULL, -- 'PENDING', 'DISPATCHED', 'COMPLETED', 'REJECTED', 'EXPIRED'
        dispatched_at TEXT NOT NULL,
        completed_at TEXT,
        broker_order_id TEXT,
        provenance TEXT DEFAULT 'BROKER_DEMO'
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_exec_intents_sig ON execution_intents(signal_id);",
    "CREATE INDEX IF NOT EXISTS idx_exec_intents_status ON execution_intents(status);"
]


def init_db_schema(conn: sqlite3.Connection):
    """Initializes SQLite tables and indexes with WAL mode enabled."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA foreign_keys = ON;")

    for stmt in SCHEMA_STATEMENTS:
        try:
            cursor.execute(stmt)
        except Exception as e:
            logger.error(f"Error executing schema statement: {e}")

    # Auto-migration columns if missing
    try:
        cursor.execute("ALTER TABLE signals ADD COLUMN provenance TEXT DEFAULT 'BROKER_DEMO';")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE signals ADD COLUMN execution_intent_id TEXT;")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE risk_checks ADD COLUMN initial_r REAL;")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN initial_r REAL;")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN execution_intent_id TEXT;")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN provenance TEXT DEFAULT 'UNKNOWN';")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN broker_account_id TEXT DEFAULT '5908018';")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN is_broker_verified INTEGER DEFAULT 0;")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN strategy_version TEXT DEFAULT 'Gold_Sniper_SMC_v2.0';")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN execution_environment TEXT DEFAULT 'DEMO';")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN data_source TEXT DEFAULT 'cTrader Open API';")
    except Exception:
        pass

    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_provenance ON trades(is_broker_verified, provenance, broker_account_id);")
    except Exception:
        pass

    conn.commit()
    logger.info("TradeTalk V2 Database schema initialized and auto-migrated successfully.")

