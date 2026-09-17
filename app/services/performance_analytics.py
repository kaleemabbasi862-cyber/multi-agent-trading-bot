import math
import datetime
from typing import Dict, Any, List, Optional
from app.database.db import get_db_connection

class QuantitativePerformanceEngine:
    @staticmethod
    def calculate_full_performance(
        trades_filter_mode: Optional[str] = None,
        broker_account_id: Optional[str] = None,
        is_broker_verified_only: bool = True
    ) -> Dict[str, Any]:
        with get_db_connection() as conn:
            where_clauses = ["status = 'CLOSED'"]
            params = []
            
            if is_broker_verified_only:
                where_clauses.append("is_broker_verified = 1")
                where_clauses.append("provenance IN ('BROKER_DEMO_VERIFIED', 'BROKER_LIVE_VERIFIED')")
                where_clauses.append("mode NOT IN ('TEST', 'PAPER')")
                where_clauses.append("id NOT LIKE 'TRD_TEST_%'")
                where_clauses.append("(ticket_id IS NULL OR ticket_id NOT LIKE 'TEST_%')")

            if trades_filter_mode and trades_filter_mode.upper() != "ALL":
                where_clauses.append("mode = ?")
                params.append(trades_filter_mode.upper())

            if broker_account_id:
                where_clauses.append("broker_account_id = ?")
                params.append(str(broker_account_id))

            where_str = " AND ".join(where_clauses)
            query = f"""
            WITH dedup_trades AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY CASE WHEN ticket_id IS NOT NULL AND ticket_id != '' THEN ticket_id ELSE id END 
                    ORDER BY CASE WHEN id LIKE 'TRD_%' THEN 1 ELSE 2 END, rowid DESC
                ) as rn
                FROM trades 
                WHERE {where_str}
            )
            SELECT * FROM dedup_trades WHERE rn = 1 ORDER BY closed_at ASC
            """
            
            rows = conn.execute(query, params).fetchall()
            trades = [dict(r) for r in rows]

        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "breakeven_trades": 0,
                "win_rate": 0.0,
                "loss_rate": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "net_profit": 0.0,
                "profit_factor": 1.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "win_loss_ratio": 1.0,
                "expectancy": 0.0,
                "max_drawdown_dollars": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "max_consecutive_wins": 0,
                "max_consecutive_losses": 0,
                "avg_trade_duration_mins": 0.0,
                "total_volume_traded": 0.0
            }

        pnls = [float(t.get("profit_loss") or 0.0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        breakevens = [p for p in pnls if p == 0]

        total_count = len(trades)
        win_count = len(wins)
        loss_count = len(losses)
        be_count = len(breakevens)

        win_rate = round((win_count / total_count) * 100.0, 1)
        loss_rate = round((loss_count / total_count) * 100.0, 1)

        gross_profit = round(sum(wins), 2)
        gross_loss = round(abs(sum(losses)), 2)
        net_profit = round(sum(pnls), 2)

        profit_factor = round(gross_profit / (gross_loss + 1e-6), 2) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
        avg_win = round(gross_profit / win_count, 2) if win_count > 0 else 0.0
        avg_loss = round(gross_loss / loss_count, 2) if loss_count > 0 else 0.0
        win_loss_ratio = round(avg_win / (avg_loss + 1e-6), 2) if avg_loss > 0 else avg_win

        win_prob = win_count / total_count
        loss_prob = loss_count / total_count
        expectancy = round((win_prob * avg_win) - (loss_prob * avg_loss), 2)

        # Drawdown & Equity Curve Metrics
        peak_equity = 1000.0 # Standard nominal base
        current_equity = 1000.0
        max_dd_dollars = 0.0
        max_dd_pct = 0.0

        consecutive_wins = 0
        max_cons_wins = 0
        consecutive_losses = 0
        max_cons_losses = 0

        durations_sec = []

        for t in trades:
            pnl = float(t.get("profit_loss") or 0.0)
            current_equity += pnl
            if current_equity > peak_equity:
                peak_equity = current_equity
            
            dd_dollars = peak_equity - current_equity
            dd_pct = (dd_dollars / (peak_equity + 1e-6)) * 100.0
            
            if dd_dollars > max_dd_dollars:
                max_dd_dollars = dd_dollars
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            # Streak tracking
            if pnl > 0:
                consecutive_wins += 1
                consecutive_losses = 0
                if consecutive_wins > max_cons_wins:
                    max_cons_wins = consecutive_wins
            elif pnl < 0:
                consecutive_losses += 1
                consecutive_wins = 0
                if consecutive_losses > max_cons_losses:
                    max_cons_losses = consecutive_losses
            else:
                consecutive_wins = 0
                consecutive_losses = 0

            # Duration tracking
            op = t.get("opened_at")
            cl = t.get("closed_at")
            if op and cl:
                try:
                    t1 = datetime.datetime.fromisoformat(op)
                    t2 = datetime.datetime.fromisoformat(cl)
                    durations_sec.append(abs((t2 - t1).total_seconds()))
                except Exception:
                    pass

        avg_duration_mins = round((sum(durations_sec) / len(durations_sec)) / 60.0, 1) if durations_sec else 0.0
        tot_volume = round(sum(float(t.get("volume") or 0.01) for t in trades), 2)

        # Sharpe & Sortino Ratios (Annualized trade representation)
        mean_pnl = sum(pnls) / total_count
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / total_count if total_count > 1 else 1.0
        std_dev = math.sqrt(variance)

        # Annualized Sharpe (assuming ~250 trading batches/year)
        sharpe_ratio = round((mean_pnl / (std_dev + 1e-6)) * math.sqrt(250), 2) if std_dev > 0 else 0.0

        # Downside Deviation for Sortino
        downside_variance = sum((p - mean_pnl) ** 2 for p in pnls if p < 0) / (loss_count if loss_count > 0 else 1)
        downside_std = math.sqrt(downside_variance)
        sortino_ratio = round((mean_pnl / (downside_std + 1e-6)) * math.sqrt(250), 2) if downside_std > 0 else 0.0

        # Calmar Ratio (Net Return % / Max Drawdown %)
        return_pct = (net_profit / 1000.0) * 100.0
        calmar_ratio = round(return_pct / (max_dd_pct + 1e-6), 2) if max_dd_pct > 0 else 1.0

        return {
            "total_trades": total_count,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "breakeven_trades": be_count,
            "win_rate": win_rate,
            "loss_rate": loss_rate,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "net_profit": net_profit,
            "profit_factor": profit_factor,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "win_loss_ratio": win_loss_ratio,
            "expectancy": expectancy,
            "max_drawdown_dollars": round(max_dd_dollars, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": sortino_ratio,
            "calmar_ratio": calmar_ratio,
            "max_consecutive_wins": max_cons_wins,
            "max_consecutive_losses": max_cons_losses,
            "avg_trade_duration_mins": avg_duration_mins,
            "total_volume_traded": tot_volume
        }

    @staticmethod
    def generate_equity_curve(
        initial_balance: float = 1000.0,
        trades_filter_mode: Optional[str] = None,
        broker_account_id: Optional[str] = None,
        is_broker_verified_only: bool = True
    ) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            where_clauses = ["status = 'CLOSED'"]
            params = []
            
            if is_broker_verified_only:
                where_clauses.append("is_broker_verified = 1")
                where_clauses.append("provenance IN ('BROKER_DEMO_VERIFIED', 'BROKER_LIVE_VERIFIED')")
                where_clauses.append("mode NOT IN ('TEST', 'PAPER')")
                where_clauses.append("id NOT LIKE 'TRD_TEST_%'")
                where_clauses.append("(ticket_id IS NULL OR ticket_id NOT LIKE 'TEST_%')")

            if trades_filter_mode and trades_filter_mode.upper() != "ALL":
                where_clauses.append("mode = ?")
                params.append(trades_filter_mode.upper())

            if broker_account_id:
                where_clauses.append("broker_account_id = ?")
                params.append(str(broker_account_id))

            where_str = " AND ".join(where_clauses)
            query = f"""
            WITH dedup_trades AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY CASE WHEN ticket_id IS NOT NULL AND ticket_id != '' THEN ticket_id ELSE id END 
                    ORDER BY CASE WHEN id LIKE 'TRD_%' THEN 1 ELSE 2 END, rowid DESC
                ) as rn
                FROM trades 
                WHERE {where_str}
            )
            SELECT id, profit_loss, closed_at FROM dedup_trades WHERE rn = 1 ORDER BY closed_at ASC
            """
            rows = conn.execute(query, params).fetchall()
            trades = [dict(r) for r in rows]

        curve = [{
            "trade_num": 0,
            "trade_id": "INIT",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "pnl": 0.0,
            "balance": initial_balance,
            "equity": initial_balance,
            "drawdown": 0.0,
            "drawdown_pct": 0.0
        }]

        current_balance = initial_balance
        peak = initial_balance

        for idx, t in enumerate(trades, start=1):
            pnl = float(t.get("profit_loss") or 0.0)
            current_balance = round(current_balance + pnl, 2)
            if current_balance > peak:
                peak = current_balance
            
            dd = round(peak - current_balance, 2)
            dd_pct = round((dd / (peak + 1e-6)) * 100.0, 2)

            curve.append({
                "trade_num": idx,
                "trade_id": t["id"],
                "timestamp": t.get("closed_at") or "",
                "pnl": pnl,
                "balance": current_balance,
                "equity": current_balance,
                "drawdown": dd,
                "drawdown_pct": dd_pct
            })

        return curve

    @staticmethod
    def get_breakdown_analytics(
        trades_filter_mode: Optional[str] = None,
        broker_account_id: Optional[str] = None,
        is_broker_verified_only: bool = True
    ) -> Dict[str, Any]:
        with get_db_connection() as conn:
            where_clauses = ["status = 'CLOSED'"]
            params = []
            
            if is_broker_verified_only:
                where_clauses.append("is_broker_verified = 1")
                where_clauses.append("provenance IN ('BROKER_DEMO_VERIFIED', 'BROKER_LIVE_VERIFIED')")
                where_clauses.append("mode NOT IN ('TEST', 'PAPER')")
                where_clauses.append("id NOT LIKE 'TRD_TEST_%'")
                where_clauses.append("(ticket_id IS NULL OR ticket_id NOT LIKE 'TEST_%')")

            if trades_filter_mode and trades_filter_mode.upper() != "ALL":
                where_clauses.append("mode = ?")
                params.append(trades_filter_mode.upper())

            if broker_account_id:
                where_clauses.append("broker_account_id = ?")
                params.append(str(broker_account_id))

            where_str = " AND ".join(where_clauses)
            query = f"""
            WITH dedup_trades AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY CASE WHEN ticket_id IS NOT NULL AND ticket_id != '' THEN ticket_id ELSE id END 
                    ORDER BY CASE WHEN id LIKE 'TRD_%' THEN 1 ELSE 2 END, rowid DESC
                ) as rn
                FROM trades 
                WHERE {where_str}
            )
            SELECT * FROM dedup_trades WHERE rn = 1
            """
            trade_rows = conn.execute(query, params).fetchall()
            trades = [dict(r) for r in trade_rows]

            # Journal mapping for Market Regime
            journal_map = {}
            j_rows = conn.execute("SELECT trade_id, market_regime, strategy_name FROM trade_journal").fetchall()
            for j in j_rows:
                journal_map[j["trade_id"]] = {
                    "regime": j["market_regime"] or "TRENDING",
                    "strategy": j["strategy_name"] or "Autonomous"
                }

        by_symbol: Dict[str, Dict[str, Any]] = {}
        by_direction: Dict[str, Dict[str, Any]] = {"BUY": {"total": 0, "wins": 0, "pnl": 0.0}, "SELL": {"total": 0, "wins": 0, "pnl": 0.0}}
        by_regime: Dict[str, Dict[str, Any]] = {}
        by_weekday: Dict[str, Dict[str, Any]] = {
            "Monday": {"total": 0, "wins": 0, "pnl": 0.0},
            "Tuesday": {"total": 0, "wins": 0, "pnl": 0.0},
            "Wednesday": {"total": 0, "wins": 0, "pnl": 0.0},
            "Thursday": {"total": 0, "wins": 0, "pnl": 0.0},
            "Friday": {"total": 0, "wins": 0, "pnl": 0.0}
        }

        weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        for t in trades:
            sym = t.get("symbol", "XAUUSD")
            direction = t.get("direction", "BUY").upper()
            pnl = float(t.get("profit_loss") or 0.0)
            is_win = pnl > 0

            # Symbol Breakdown
            if sym not in by_symbol:
                by_symbol[sym] = {"symbol": sym, "total": 0, "wins": 0, "pnl": 0.0}
            by_symbol[sym]["total"] += 1
            if is_win:
                by_symbol[sym]["wins"] += 1
            by_symbol[sym]["pnl"] = round(by_symbol[sym]["pnl"] + pnl, 2)

            # Direction Breakdown
            if direction in by_direction:
                by_direction[direction]["total"] += 1
                if is_win:
                    by_direction[direction]["wins"] += 1
                by_direction[direction]["pnl"] = round(by_direction[direction]["pnl"] + pnl, 2)

            # Regime Breakdown
            j_info = journal_map.get(t["id"], {"regime": "TRENDING"})
            reg = j_info.get("regime", "TRENDING")
            if reg not in by_regime:
                by_regime[reg] = {"regime": reg, "total": 0, "wins": 0, "pnl": 0.0}
            by_regime[reg]["total"] += 1
            if is_win:
                by_regime[reg]["wins"] += 1
            by_regime[reg]["pnl"] = round(by_regime[reg]["pnl"] + pnl, 2)

            # Weekday Breakdown
            op = t.get("opened_at")
            if op:
                try:
                    dt = datetime.datetime.fromisoformat(op)
                    day_name = weekday_names[dt.weekday()]
                    if day_name in by_weekday:
                        by_weekday[day_name]["total"] += 1
                        if is_win:
                            by_weekday[day_name]["wins"] += 1
                        by_weekday[day_name]["pnl"] = round(by_weekday[day_name]["pnl"] + pnl, 2)
                except Exception:
                    pass

        # Calculate win rates for each group
        for s, d in by_symbol.items():
            d["win_rate"] = round((d["wins"] / d["total"]) * 100.0, 1) if d["total"] > 0 else 0.0
        for s, d in by_direction.items():
            d["win_rate"] = round((d["wins"] / d["total"]) * 100.0, 1) if d["total"] > 0 else 0.0
        for s, d in by_regime.items():
            d["win_rate"] = round((d["wins"] / d["total"]) * 100.0, 1) if d["total"] > 0 else 0.0
        for s, d in by_weekday.items():
            d["win_rate"] = round((d["wins"] / d["total"]) * 100.0, 1) if d["total"] > 0 else 0.0

        return {
            "by_symbol": list(by_symbol.values()),
            "by_direction": by_direction,
            "by_regime": list(by_regime.values()),
            "by_weekday": by_weekday
        }

performance_engine = QuantitativePerformanceEngine()
