import sqlite3
import json
import threading
import datetime
from typing import List, Dict, Any, Optional, Tuple
from app.config import settings
from app.database.schema import init_db_schema

_lock = threading.Lock()

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DATABASE_PATH, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

# Initialize DB on import
with get_db_connection() as _init_conn:
    init_db_schema(_init_conn)

class DatabaseManager:
    @staticmethod
    def get_connection() -> sqlite3.Connection:
        return get_db_connection()

    @staticmethod
    def log_audit(event_type: str, actor: str, details: str):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                "INSERT INTO audit_logs (timestamp, event_type, actor, details) VALUES (?, ?, ?, ?)",
                (now, event_type, actor, details)
            )
            conn.commit()

    @staticmethod
    def log_system_log(level: str, module: str, message: str, correlation_id: str = "-"):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                "INSERT INTO system_logs (timestamp, level, module, message, correlation_id) VALUES (?, ?, ?, ?, ?)",
                (now, level, module, message, correlation_id)
            )
            conn.commit()

    @staticmethod
    def get_system_logs(limit: int = 100, level_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            if level_filter and level_filter.upper() != "ALL":
                rows = conn.execute(
                    "SELECT * FROM system_logs WHERE level = ? ORDER BY id DESC LIMIT ?",
                    (level_filter.upper(), limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM system_logs ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def log_risk_event(event_type: str, account_id: str, severity: str, details: str):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                "INSERT INTO risk_events (timestamp, event_type, account_id, severity, details) VALUES (?, ?, ?, ?, ?)",
                (now, event_type, account_id, severity, details)
            )
            conn.commit()

    @staticmethod
    def get_risk_events(limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM risk_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def save_signal(signal_data: Dict[str, Any]) -> str:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO signals 
                (id, timestamp, symbol, direction, source, entry_price, stop_loss, take_profit, rr_ratio, timeframe, status, decision_score, rejection_reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_data["id"],
                    signal_data.get("timestamp", now),
                    signal_data["symbol"],
                    signal_data["direction"],
                    signal_data.get("source", "MANUAL_OR_SCANNER"),
                    signal_data["entry_price"],
                    signal_data["stop_loss"],
                    signal_data["take_profit"],
                    signal_data.get("rr_ratio", 2.0),
                    signal_data.get("timeframe", "15m"),
                    signal_data["status"],
                    signal_data.get("decision_score", 0.0),
                    signal_data.get("rejection_reason"),
                    now
                )
            )
            conn.commit()
        return signal_data["id"]

    @staticmethod
    def save_agent_decisions(signal_id: str, decisions: List[Dict[str, Any]]):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            for d in decisions:
                metrics = json.dumps(d.get("metrics", {})) if isinstance(d.get("metrics"), dict) else "{}"
                conn.execute(
                    """
                    INSERT INTO agent_decisions 
                    (signal_id, agent_name, score, direction, decision, reasoning_summary, metrics_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal_id,
                        d["agent_name"],
                        d["score"],
                        d.get("direction", "NEUTRAL"),
                        d["decision"],
                        d.get("reasoning_summary", ""),
                        metrics,
                        now
                    )
                )
            conn.commit()

    @staticmethod
    def save_risk_check(risk_data: Dict[str, Any]):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO risk_checks
                (signal_id, account_balance, account_equity, risk_amount, calculated_volume, sl_distance, tp_distance, rr_ratio, spread, passed, veto_reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    risk_data["signal_id"],
                    risk_data.get("account_balance", 0.0),
                    risk_data.get("account_equity", 0.0),
                    risk_data.get("risk_amount", 0.0),
                    risk_data.get("calculated_volume", 0.01),
                    risk_data.get("sl_distance", 0.0),
                    risk_data.get("tp_distance", 0.0),
                    risk_data.get("rr_ratio", 2.0),
                    risk_data.get("spread", 0.35),
                    1 if risk_data.get("passed", False) else 0,
                    risk_data.get("veto_reason"),
                    now
                )
            )
            conn.commit()

    @staticmethod
    def save_decision_dna(signal_id: str, dna_snapshot: Dict[str, Any]):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        raw_json = json.dumps(dna_snapshot, ensure_ascii=False)
        with _lock, get_db_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO decision_dna (signal_id, snapshot_json, created_at) VALUES (?, ?, ?)",
                (signal_id, raw_json, now)
            )
            conn.commit()

    @staticmethod
    def get_decision_dna(signal_id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            row = conn.execute("SELECT snapshot_json FROM decision_dna WHERE signal_id = ?", (signal_id,)).fetchone()
            if row:
                return json.loads(row["snapshot_json"])
        return None

    @staticmethod
    def save_trade(trade_data: Dict[str, Any]) -> str:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        is_verified = int(trade_data.get("is_broker_verified", 1 if trade_data.get("provenance") in ("BROKER_DEMO_VERIFIED", "BROKER_LIVE_VERIFIED") else 0))
        prov = str(trade_data.get("provenance") or ("BROKER_DEMO_VERIFIED" if is_verified else "TEST"))
        acc_id = str(trade_data.get("broker_account_id") or getattr(settings, "CTRADER_ACCOUNT_ID", "5908018"))
        strat_ver = str(trade_data.get("strategy_version") or "Gold_Sniper_SMC_v2.0")
        env = str(trade_data.get("execution_environment") or ("DEMO" if is_verified else "TEST"))
        src = str(trade_data.get("data_source") or "cTrader Open API")

        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trades
                (id, signal_id, mode, broker_order_id, ticket_id, symbol, direction, entry_price, exit_price, stop_loss, take_profit, volume, profit_loss, pips, commission, swap, status, close_reason, opened_at, closed_at, execution_intent_id, initial_r, provenance, broker_account_id, is_broker_verified, strategy_version, execution_environment, data_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_data["id"],
                    trade_data.get("signal_id", ""),
                    trade_data.get("mode", settings.TRADING_MODE),
                    trade_data.get("broker_order_id"),
                    trade_data.get("ticket_id"),
                    trade_data["symbol"],
                    trade_data["direction"],
                    trade_data["entry_price"],
                    trade_data.get("exit_price"),
                    trade_data["stop_loss"],
                    trade_data["take_profit"],
                    trade_data.get("volume", 0.01),
                    trade_data.get("profit_loss", 0.0),
                    trade_data.get("pips", 0.0),
                    trade_data.get("commission", 0.0),
                    trade_data.get("swap", 0.0),
                    trade_data.get("status", "OPEN"),
                    trade_data.get("close_reason"),
                    trade_data.get("opened_at", now),
                    trade_data.get("closed_at"),
                    trade_data.get("execution_intent_id"),
                    trade_data.get("initial_r"),
                    prov,
                    acc_id,
                    is_verified,
                    strat_ver,
                    env,
                    src
                )
            )
            conn.commit()
        return trade_data["id"]


    @staticmethod
    def update_trade_status(trade_id: str, status: str, exit_price: Optional[float] = None, profit_loss: Optional[float] = None, pips: Optional[float] = None, close_reason: Optional[str] = None):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                UPDATE trades
                SET status = ?, exit_price = COALESCE(?, exit_price), profit_loss = COALESCE(?, profit_loss), pips = COALESCE(?, pips), close_reason = COALESCE(?, close_reason), closed_at = ?
                WHERE id = ? OR ticket_id = ?
                """,
                (status, exit_price, profit_loss, pips, close_reason, now if status == 'CLOSED' else None, trade_id, trade_id)
            )
            conn.commit()

    @staticmethod
    def sync_cbot_closed_trade(item: Dict[str, Any]):
        ticket_id = str(item.get("position_id") or item.get("id") or item.get("ticket_id") or "").strip()
        if not ticket_id:
            return
        
        sym = str(item.get("symbol") or "XAUUSD").upper()
        direction = str(item.get("trade_type") or item.get("side") or item.get("direction") or item.get("action") or "BUY").upper()
        
        entry_p = float(item.get("entry_price") or item.get("entry") or 0.0)
        exit_p = float(item.get("closing_price") or item.get("close") or item.get("exit_price") or 0.0)
        
        # PnL extraction
        raw_pnl = item.get("net_profit")
        if raw_pnl is None:
            raw_pnl = item.get("pnl")
        if raw_pnl is None:
            raw_pnl = item.get("profit_loss")
        pnl = float(raw_pnl) if raw_pnl is not None else 0.0
        
        comm = float(item.get("commission", 0.0))
        swap = float(item.get("swap", 0.0))
        
        raw_vol = float(item.get("volume") or item.get("lots") or item.get("lot_size") or 0.01)
        vol = round(raw_vol / 100.0 if raw_vol >= 10.0 else raw_vol, 2)
        
        closed_at = item.get("closing_time") or item.get("closed_at") or item.get("timestamp")
        opened_at = item.get("entry_time") or item.get("opened_at") or closed_at
        
        pips = float(item.get("pips", 0.0))
        if pips == 0.0 and exit_p > 0 and entry_p > 0:
            if "XAU" in sym or "GOLD" in sym:
                pips = round((exit_p - entry_p) * 10, 1) if direction == "BUY" else round((entry_p - exit_p) * 10, 1)
        
        with _lock, get_db_connection() as conn:
            stripped = ticket_id.removeprefix("CT_").removeprefix("TRD_")
            existing = conn.execute(
                "SELECT id, entry_price, volume FROM trades WHERE ticket_id = ? OR ticket_id = ? OR ticket_id = ? OR id = ? OR id = ?",
                (ticket_id, stripped, f"CT_{stripped}", f"TRD_{stripped}", f"CT_{stripped}")
            ).fetchall()
            
            if existing:
                for ex_row in existing:
                    row_entry = float(ex_row["entry_price"] or 0.0)
                    final_entry = entry_p if (entry_p > 0 or row_entry == 0.0) else row_entry
                    row_vol = float(ex_row["volume"] or 0.0)
                    final_vol = vol if (vol > 0 or row_vol == 0.0) else row_vol
                    
                    conn.execute(
                        """
                        UPDATE trades
                        SET status = 'CLOSED',
                            direction = ?,
                            entry_price = ?,
                            exit_price = ?,
                            profit_loss = ?,
                            pips = ?,
                            commission = ?,
                            swap = ?,
                            volume = ?,
                            closed_at = COALESCE(?, closed_at),
                            opened_at = COALESCE(opened_at, ?),
                            is_broker_verified = 1,
                            provenance = 'BROKER_DEMO_VERIFIED',
                            broker_account_id = ?,
                            execution_environment = 'DEMO',
                            data_source = 'cTrader Open API'
                        WHERE id = ?
                        """,
                        (direction, final_entry, exit_p, pnl, pips, comm, swap, final_vol, closed_at, opened_at, getattr(settings, "CTRADER_ACCOUNT_ID", "5908018"), ex_row["id"])
                    )
            else:
                trade_id = f"CT_{ticket_id}"
                conn.execute(
                    """
                    INSERT INTO trades
                    (id, signal_id, mode, broker_order_id, ticket_id, symbol, direction, entry_price, exit_price, stop_loss, take_profit, volume, profit_loss, pips, commission, swap, status, close_reason, opened_at, closed_at, is_broker_verified, provenance, broker_account_id, execution_environment, data_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade_id,
                        "",
                        settings.TRADING_MODE,
                        f"cBot History #{ticket_id}",
                        ticket_id,
                        sym,
                        direction,
                        entry_p,
                        exit_p,
                        0.0,
                        0.0,
                        vol,
                        pnl,
                        pips,
                        comm,
                        swap,
                        "CLOSED",
                        "Broker History Sync",
                        opened_at,
                        closed_at,
                        1,
                        "BROKER_DEMO_VERIFIED",
                        getattr(settings, "CTRADER_ACCOUNT_ID", "5908018"),
                        "DEMO",
                        "cTrader Open API"
                    )
                )
            conn.commit()

    @staticmethod
    def save_trade_journal_entry(journal_data: Dict[str, Any]):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trade_journal
                (id, trade_id, symbol, direction, strategy_name, market_regime, mfe, mae, trade_duration_seconds, news_context, ai_reasoning, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    journal_data["id"],
                    journal_data["trade_id"],
                    journal_data["symbol"],
                    journal_data["direction"],
                    journal_data.get("strategy_name", "Gold_Sniper_SMC_v2.0"),
                    journal_data.get("market_regime", "NORMAL"),
                    journal_data.get("mfe", 0.0),
                    journal_data.get("mae", 0.0),
                    journal_data.get("trade_duration_seconds", 0),
                    journal_data.get("news_context", "NONE"),
                    journal_data.get("ai_reasoning", ""),
                    journal_data.get("notes", ""),
                    now
                )
            )
            conn.commit()

    @staticmethod
    def get_trade_journal_entries(limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT j.*, t.entry_price, t.exit_price, t.profit_loss, t.pips, t.opened_at, t.closed_at, t.status
                FROM trade_journal j
                LEFT JOIN trades t ON j.trade_id = t.id
                ORDER BY j.created_at DESC LIMIT ?
                """,
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_recent_signals(limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            signals = []
            for r in rows:
                item = dict(r)
                item["action"] = item.get("direction", "BUY")
                agent_rows = conn.execute(
                    "SELECT agent_name, score, direction, decision, reasoning_summary, metrics_json FROM agent_decisions WHERE signal_id = ?",
                    (r["id"],)
                ).fetchall()
                item["agent_decisions"] = [dict(a) for a in agent_rows]
                risk_row = conn.execute(
                    "SELECT * FROM risk_checks WHERE signal_id = ? ORDER BY id DESC LIMIT 1",
                    (r["id"],)
                ).fetchone()
                item["risk_check"] = dict(risk_row) if risk_row else None
                signals.append(item)
            return signals

    @staticmethod
    def get_recent_trades(limit: int = 50, broker_account_id: Optional[str] = None, is_broker_verified_only: bool = True) -> List[Dict[str, Any]]:
        """
        Returns recent trades. Fail-closed: by default returns ONLY authentic, verified broker trades
        for the active broker account.
        """
        acc_id = broker_account_id or getattr(settings, "CTRADER_ACCOUNT_ID", "5908018")
        with get_db_connection() as conn:
            if is_broker_verified_only:
                rows = conn.execute(
                    """
                    SELECT * FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY CASE WHEN ticket_id IS NOT NULL AND ticket_id != '' THEN ticket_id ELSE id END 
                            ORDER BY CASE WHEN id LIKE 'TRD_%' THEN 1 ELSE 2 END, rowid DESC
                        ) as rn
                        FROM trades
                        WHERE is_broker_verified = 1 
                          AND provenance IN ('BROKER_DEMO_VERIFIED', 'BROKER_LIVE_VERIFIED')
                          AND (broker_account_id = ? OR broker_account_id IS NULL OR broker_account_id = '')
                    ) WHERE rn = 1
                    ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT ?
                    """, (acc_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY CASE WHEN ticket_id IS NOT NULL AND ticket_id != '' THEN ticket_id ELSE id END 
                            ORDER BY CASE WHEN id LIKE 'TRD_%' THEN 1 ELSE 2 END, rowid DESC
                        ) as rn
                        FROM trades
                    ) WHERE rn = 1
                    ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT ?
                    """, (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_all_trades_raw(limit: int = 100) -> List[Dict[str, Any]]:
        """Returns raw unrestricted trade records for forensics and auditing."""
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_performance_stats(broker_account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculates performance statistics ONLY from authentic broker-verified closed trades.
        Excludes TEST, PAPER, SIMULATED, BACKTEST, and UNKNOWN provenance.
        """
        acc_id = broker_account_id or getattr(settings, "CTRADER_ACCOUNT_ID", "5908018")
        with get_db_connection() as conn:
            total_signals = conn.execute("SELECT COUNT(*) as c FROM signals").fetchone()["c"]
            approved_signals = conn.execute("SELECT COUNT(*) as c FROM signals WHERE status = 'APPROVED'").fetchone()["c"]
            rejected_signals = conn.execute("SELECT COUNT(*) as c FROM signals WHERE status IN ('REJECTED', 'BLOCKED')").fetchone()["c"]
            
            trade_stats = conn.execute(
                """
                WITH dedup_trades AS (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY CASE WHEN ticket_id IS NOT NULL AND ticket_id != '' THEN ticket_id ELSE id END 
                        ORDER BY CASE WHEN id LIKE 'TRD_%' THEN 1 ELSE 2 END, rowid DESC
                    ) as rn
                    FROM trades 
                    WHERE status = 'CLOSED'
                      AND is_broker_verified = 1
                      AND provenance IN ('BROKER_DEMO_VERIFIED', 'BROKER_LIVE_VERIFIED')
                      AND (broker_account_id = ? OR broker_account_id IS NULL OR broker_account_id = '')
                )
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as win_count,
                    SUM(CASE WHEN profit_loss < 0 THEN 1 ELSE 0 END) as loss_count,
                    SUM(profit_loss) as net_pnl,
                    SUM(CASE WHEN profit_loss > 0 THEN profit_loss ELSE 0 END) as gross_profit,
                    ABS(SUM(CASE WHEN profit_loss < 0 THEN profit_loss ELSE 0 END)) as gross_loss
                FROM dedup_trades WHERE rn = 1
                """, (acc_id,)
            ).fetchone()
            
            tot_tr = trade_stats["total_trades"] or 0
            wins = trade_stats["win_count"] or 0
            win_rate = round((wins / tot_tr) * 100.0, 1) if tot_tr > 0 else 0.0
            gross_p = float(trade_stats["gross_profit"] or 0.0)
            gross_l = float(trade_stats["gross_loss"] or 0.0)
            profit_factor = round(gross_p / gross_l, 2) if gross_l > 0 else (gross_p if gross_p > 0 else 1.0)
            
            return {
                "total_signals": total_signals,
                "approved_signals": approved_signals,
                "rejected_signals": rejected_signals,
                "approval_rate": round((approved_signals / (total_signals + 1e-6)) * 100.0, 1) if total_signals > 0 else 0.0,
                "closed_trades": tot_tr,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "gross_profit": round(gross_p, 2),
                "gross_loss": round(gross_l, 2),
                "net_pnl": round(trade_stats["net_pnl"] or 0.0, 2)
            }

    @staticmethod
    def save_backtest_run(backtest_data: Dict[str, Any]):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO strategy_backtests
                (id, strategy_name, symbol, timeframe, start_date, end_date, initial_balance, final_balance, total_trades, win_rate, profit_factor, max_drawdown, metrics_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    backtest_data["id"],
                    backtest_data["strategy_name"],
                    backtest_data.get("symbol", "XAUUSD"),
                    backtest_data.get("timeframe", "15m"),
                    backtest_data["start_date"],
                    backtest_data["end_date"],
                    backtest_data["initial_balance"],
                    backtest_data["final_balance"],
                    backtest_data["total_trades"],
                    backtest_data["win_rate"],
                    backtest_data["profit_factor"],
                    backtest_data["max_drawdown"],
                    json.dumps(backtest_data.get("metrics", {})),
                    now
                )
            )
            conn.commit()

    @staticmethod
    def save_economic_event(event_data: Dict[str, Any]) -> str:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        ev_id = event_data.get("id") or f"EVT_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}_{event_data.get('currency', 'USD')}"
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO economic_events
                (id, timestamp, currency, country, event_name, impact, actual, forecast, previous, affected_symbols, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev_id,
                    event_data.get("timestamp", now),
                    event_data.get("currency", "USD"),
                    event_data.get("country", "US"),
                    event_data.get("event_name", "Macro Event"),
                    event_data.get("impact", "HIGH"),
                    event_data.get("actual"),
                    event_data.get("forecast"),
                    event_data.get("previous"),
                    json.dumps(event_data.get("affected_symbols", ["XAUUSD"])) if isinstance(event_data.get("affected_symbols"), list) else str(event_data.get("affected_symbols", '["XAUUSD"]')),
                    now
                )
            )
            conn.commit()
        return ev_id

    @staticmethod
    def get_economic_events(
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        impact: Optional[str] = None,
        currency: Optional[str] = None,
        limit: int = 100,
        include_mock: bool = False
    ) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            query = "SELECT * FROM economic_events WHERE 1=1"
            params: List[Any] = []
            if not include_mock:
                query += " AND id NOT LIKE 'TEST%' AND id NOT LIKE 'EVT_TEST%' AND id NOT LIKE '%MOCK%'"
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time)
            if impact and impact.upper() != "ALL":
                query += " AND impact = ?"
                params.append(impact.upper())
            if currency and currency.upper() != "ALL":
                query += " AND currency = ?"
                params.append(currency.upper())
            
            query += " ORDER BY timestamp ASC LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                if item.get("affected_symbols"):
                    try:
                        item["affected_symbols"] = json.loads(item["affected_symbols"])
                    except Exception:
                        pass
                results.append(item)
            return results

    @staticmethod
    def save_news_item(news_data: Dict[str, Any]) -> str:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        news_id = news_data.get("id") or f"NEWS_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO news
                (id, headline, source, timestamp, category, sentiment, sentiment_score, affected_symbols, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    news_id,
                    news_data["headline"],
                    news_data.get("source", "MARKET_FEED"),
                    news_data.get("timestamp", now),
                    news_data.get("category", "FOREX"),
                    news_data.get("sentiment", "NEUTRAL"),
                    float(news_data.get("sentiment_score", 0.0)),
                    json.dumps(news_data.get("affected_symbols", ["XAUUSD"])) if isinstance(news_data.get("affected_symbols"), list) else str(news_data.get("affected_symbols", '["XAUUSD"]')),
                    now
                )
            )
            conn.commit()
        return news_id

    @staticmethod
    def get_recent_news(limit: int = 50, category: Optional[str] = None, sentiment: Optional[str] = None) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            query = "SELECT * FROM news WHERE 1=1"
            params: List[Any] = []
            if category and category.upper() != "ALL":
                query += " AND category = ?"
                params.append(category.upper())
            if sentiment and sentiment.upper() != "ALL":
                query += " AND sentiment = ?"
                params.append(sentiment.upper())
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                if item.get("affected_symbols"):
                    try:
                        item["affected_symbols"] = json.loads(item["affected_symbols"])
                    except Exception:
                        pass
                results.append(item)
            return results

    @staticmethod
    def get_market_sentiment_summary(symbol: str = "XAUUSD") -> Dict[str, Any]:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT sentiment, sentiment_score FROM news ORDER BY timestamp DESC LIMIT 30").fetchall()
            if not rows:
                return {
                    "symbol": symbol,
                    "sentiment": "NEUTRAL",
                    "sentiment_score": 0.0,
                    "usd_bias": "NEUTRAL",
                    "gold_bias": "NEUTRAL",
                    "sample_size": 0
                }
            
            scores = [float(r["sentiment_score"]) for r in rows]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            
            if avg_score >= 0.4:
                sentiment_label = "STRONG_BULLISH"
            elif avg_score >= 0.15:
                sentiment_label = "BULLISH"
            elif avg_score <= -0.4:
                sentiment_label = "STRONG_BEARISH"
            elif avg_score <= -0.15:
                sentiment_label = "BEARISH"
            else:
                sentiment_label = "NEUTRAL"
            
            gold_bias = "BULLISH_GOLD" if avg_score > 0.1 else ("BEARISH_GOLD" if avg_score < -0.1 else "NEUTRAL")
            usd_bias = "BEARISH_USD" if avg_score > 0.1 else ("BULLISH_USD" if avg_score < -0.1 else "NEUTRAL")
            
            return {
                "symbol": symbol,
                "sentiment": sentiment_label,
                "sentiment_score": round(avg_score, 3),
                "usd_bias": usd_bias,
                "gold_bias": gold_bias,
                "sample_size": len(rows)
            }

    @staticmethod
    def clear_economic_events():
        with _lock, get_db_connection() as conn:
            conn.execute("DELETE FROM economic_events")
            conn.commit()

    @staticmethod
    def clear_news():
        with _lock, get_db_connection() as conn:
            conn.execute("DELETE FROM news")
            conn.commit()

    @staticmethod
    def clear_signals():
        with _lock, get_db_connection() as conn:
            conn.execute("DELETE FROM signals")
            conn.execute("DELETE FROM agent_decisions")
            conn.execute("DELETE FROM risk_checks")
            conn.execute("DELETE FROM decision_dna")
            conn.commit()

    @staticmethod
    def record_execution_intent(intent_data: Optional[Dict[str, Any]] = None, **kwargs) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Atomically records an execution intent to enforce strict idempotency (duplicate executions = 0).
        Returns (is_new, existing_intent_record).
        """
        data = dict(intent_data) if intent_data and isinstance(intent_data, dict) else dict(kwargs)
        intent_id = data.get("intent_id") or data.get("execution_intent_id")
        if not intent_id:
            return False, None

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            existing = conn.execute("SELECT * FROM execution_intents WHERE intent_id = ?", (intent_id,)).fetchone()
            if existing:
                return False, dict(existing)

            conn.execute(
                """
                INSERT INTO execution_intents
                (intent_id, signal_id, symbol, action, volume, entry_price, sl_price, tp_price, status, dispatched_at, broker_order_id, provenance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent_id,
                    data.get("signal_id", "SIG_UNKNOWN"),
                    data.get("symbol", "XAUUSD"),
                    data.get("action", "BUY"),
                    float(data.get("volume", 0.01)),
                    float(data.get("entry_price", 0.0)),
                    float(data.get("sl_price", 0.0)),
                    float(data.get("tp_price", 0.0)),
                    data.get("status", "PENDING"),
                    now,
                    data.get("broker_order_id"),
                    data.get("provenance", "BROKER_DEMO")
                )
            )
            conn.commit()
            return True, None


    @staticmethod
    def get_execution_intent(intent_id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM execution_intents WHERE intent_id = ?", (intent_id,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def update_execution_intent_status(intent_id: str, status: str, broker_order_id: Optional[str] = None, error: Optional[str] = None, **kwargs):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                UPDATE execution_intents
                SET status = ?, broker_order_id = COALESCE(?, broker_order_id), completed_at = ?
                WHERE intent_id = ?
                """,
                (status, broker_order_id, now, intent_id)
            )
            conn.commit()


    @staticmethod
    def clear_mock_events_and_news():
        with _lock, get_db_connection() as conn:
            conn.execute("DELETE FROM economic_events WHERE id LIKE 'EVT_%' OR id LIKE 'MOCK_%' OR id LIKE 'TEST_%'")
            conn.execute("DELETE FROM news WHERE source = 'MOCK_FEED' OR id LIKE 'MOCK_%'")
            conn.commit()

db = DatabaseManager()
