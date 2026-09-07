import sqlite3
import json
import threading
import datetime
from typing import List, Dict, Any, Optional
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
    def log_audit(event_type: str, actor: str, details: str):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _lock, get_db_connection() as conn:
            conn.execute(
                "INSERT INTO audit_logs (timestamp, event_type, actor, details) VALUES (?, ?, ?, ?)",
                (now, event_type, actor, details)
            )
            conn.commit()

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
        with _lock, get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trades
                (id, signal_id, mode, broker_order_id, ticket_id, symbol, direction, entry_price, exit_price, stop_loss, take_profit, volume, profit_loss, pips, commission, swap, status, close_reason, opened_at, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    trade_data.get("closed_at")
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
    def get_recent_signals(limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            signals = []
            for r in rows:
                item = dict(r)
                # Fetch agent decisions for this signal
                agent_rows = conn.execute(
                    "SELECT agent_name, score, direction, decision, reasoning_summary, metrics_json FROM agent_decisions WHERE signal_id = ?",
                    (r["id"],)
                ).fetchall()
                item["agent_decisions"] = [dict(a) for a in agent_rows]
                # Fetch risk check
                risk_row = conn.execute(
                    "SELECT * FROM risk_checks WHERE signal_id = ? ORDER BY id DESC LIMIT 1",
                    (r["id"],)
                ).fetchone()
                item["risk_check"] = dict(risk_row) if risk_row else None
                signals.append(item)
            return signals

    @staticmethod
    def get_recent_trades(limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY opened_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_performance_stats() -> Dict[str, Any]:
        with get_db_connection() as conn:
            total_signals = conn.execute("SELECT COUNT(*) as c FROM signals").fetchone()["c"]
            approved_signals = conn.execute("SELECT COUNT(*) as c FROM signals WHERE status = 'APPROVED'").fetchone()["c"]
            rejected_signals = conn.execute("SELECT COUNT(*) as c FROM signals WHERE status IN ('REJECTED', 'BLOCKED')").fetchone()["c"]
            
            trade_stats = conn.execute(
                """
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as win_count,
                    SUM(CASE WHEN profit_loss < 0 THEN 1 ELSE 0 END) as loss_count,
                    SUM(profit_loss) as net_pnl,
                    SUM(CASE WHEN profit_loss > 0 THEN profit_loss ELSE 0 END) as gross_profit,
                    ABS(SUM(CASE WHEN profit_loss < 0 THEN profit_loss ELSE 0 END)) as gross_loss
                FROM trades WHERE status = 'CLOSED'
                """
            ).fetchone()
            
            tot_tr = trade_stats["total_trades"] or 0
            wins = trade_stats["win_count"] or 0
            win_rate = round((wins / tot_tr) * 100.0, 1) if tot_tr > 0 else 0.0
            gross_p = trade_stats["gross_profit"] or 0.0
            gross_l = trade_stats["gross_loss"] or 0.0
            profit_factor = round(gross_p / (gross_l + 1e-6), 2) if gross_l > 0 else (gross_p if gross_p > 0 else 1.0)
            
            return {
                "total_signals": total_signals,
                "approved_signals": approved_signals,
                "rejected_signals": rejected_signals,
                "approval_rate": round((approved_signals / (total_signals + 1e-6)) * 100.0, 1) if total_signals > 0 else 0.0,
                "closed_trades": tot_tr,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
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

db = DatabaseManager()
