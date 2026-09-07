import sqlite3
import logging

logger = logging.getLogger("TradeTalk.DB.Schema")

SCHEMA_STATEMENTS = [
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
    """
    CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
    """,
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
    """
    CREATE INDEX IF NOT EXISTS idx_agent_decisions_signal ON agent_decisions(signal_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_decisions_name ON agent_decisions(agent_name);
    """,
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
    """
    CREATE INDEX IF NOT EXISTS idx_risk_checks_signal ON risk_checks(signal_id);
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL,
        mode TEXT NOT NULL,
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
    """
    CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_trades_mode ON trades(mode);
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_dna (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT UNIQUE NOT NULL,
        snapshot_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(signal_id) REFERENCES signals(id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_dna_signal ON decision_dna(signal_id);
    """,
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
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        event_type TEXT NOT NULL,
        actor TEXT NOT NULL,
        details TEXT NOT NULL
    );
    """
]

def init_db_schema(conn: sqlite3.Connection):
    """Initializes SQLite tables and indexes with WAL mode enabled."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    for stmt in SCHEMA_STATEMENTS:
        cursor.execute(stmt)
    
    conn.commit()
    logger.info("TradeTalk V2 Database schema initialized successfully.")
