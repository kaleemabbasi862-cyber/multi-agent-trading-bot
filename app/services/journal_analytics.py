import json
import logging
from typing import Dict, Any, List, Optional
from app.database.db import get_db_connection, db

logger = logging.getLogger("TradeTalk.JournalAnalytics")

class JournalAnalyticsService:
    @staticmethod
    def get_journal_entries(
        symbol: Optional[str] = None,
        regime: Optional[str] = None,
        strategy: Optional[str] = None,
        outcome: Optional[str] = None, # 'WIN', 'LOSS', 'ALL'
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            query = """
                SELECT 
                    j.*, 
                    t.mode,
                    t.entry_price, 
                    t.exit_price, 
                    t.stop_loss,
                    t.take_profit,
                    t.volume,
                    t.profit_loss, 
                    t.pips, 
                    t.commission,
                    t.swap,
                    t.opened_at, 
                    t.closed_at, 
                    t.status,
                    t.close_reason,
                    t.signal_id
                FROM trade_journal j
                LEFT JOIN trades t ON j.trade_id = t.id
                WHERE 1=1
            """
            params: List[Any] = []
            
            if symbol and symbol.upper() != "ALL":
                query += " AND j.symbol = ?"
                params.append(symbol.upper())
            if regime and regime.upper() != "ALL":
                query += " AND j.market_regime = ?"
                params.append(regime.upper())
            if strategy and strategy.upper() != "ALL":
                query += " AND j.strategy_name = ?"
                params.append(strategy)
            if outcome and outcome.upper() != "ALL":
                if outcome.upper() == "WIN":
                    query += " AND t.profit_loss > 0"
                elif outcome.upper() == "LOSS":
                    query += " AND t.profit_loss < 0"
                elif outcome.upper() == "BREAKEVEN":
                    query += " AND t.profit_loss = 0"
            
            query += " ORDER BY j.created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                pnl = float(item.get("profit_loss") or 0.0)
                mfe = float(item.get("mfe") or 0.0)
                mae = float(item.get("mae") or 0.0)
                
                # Trade Efficiency Calculation: How much of MFE was captured at exit
                pips = float(item.get("pips") or 0.0)
                eff_pct = round((pips / mfe) * 100.0, 1) if mfe > 0 and pips > 0 else 0.0
                item["efficiency_pct"] = eff_pct
                item["is_win"] = pnl > 0
                results.append(item)
            return results

    @staticmethod
    def get_entry_details(entry_id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            row = conn.execute("""
                SELECT 
                    j.*, 
                    t.mode,
                    t.entry_price, 
                    t.exit_price, 
                    t.stop_loss,
                    t.take_profit,
                    t.volume,
                    t.profit_loss, 
                    t.pips, 
                    t.commission,
                    t.swap,
                    t.opened_at, 
                    t.closed_at, 
                    t.status,
                    t.close_reason,
                    t.signal_id
                FROM trade_journal j
                LEFT JOIN trades t ON j.trade_id = t.id
                WHERE j.id = ? OR j.trade_id = ?
            """, (entry_id, entry_id)).fetchone()
            
            if not row:
                return None
            
            res = dict(row)
            sig_id = res.get("signal_id")
            if sig_id:
                res["decision_dna"] = db.get_decision_dna(sig_id)
            else:
                res["decision_dna"] = None
            return res

    @staticmethod
    def update_journal_notes(entry_id: str, notes: str) -> bool:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "UPDATE trade_journal SET notes = ? WHERE id = ? OR trade_id = ?",
                (notes, entry_id, entry_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def get_mfe_mae_matrix(limit: int = 100) -> Dict[str, Any]:
        """
        Returns MFE vs MAE scatter data coordinates for graphical excursion analysis.
        """
        with get_db_connection() as conn:
            rows = conn.execute("""
                SELECT 
                    j.id, j.trade_id, j.symbol, j.direction, j.mfe, j.mae, j.market_regime,
                    t.profit_loss, t.pips, t.volume
                FROM trade_journal j
                JOIN trades t ON j.trade_id = t.id
                WHERE t.status = 'CLOSED'
                ORDER BY j.created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            
            points = []
            mfe_list = []
            mae_list = []
            for r in rows:
                mfe_val = float(r["mfe"] or 0.0)
                mae_val = float(r["mae"] or 0.0)
                pnl = float(r["profit_loss"] or 0.0)
                pips = float(r["pips"] or 0.0)
                mfe_list.append(mfe_val)
                mae_list.append(mae_val)
                points.append({
                    "trade_id": r["trade_id"],
                    "symbol": r["symbol"],
                    "direction": r["direction"],
                    "regime": r["market_regime"],
                    "mfe_pips": mfe_val,
                    "mae_pips": mae_val,
                    "pnl": pnl,
                    "pips": pips,
                    "is_win": pnl > 0
                })
            
            avg_mfe = round(sum(mfe_list) / len(mfe_list), 1) if mfe_list else 0.0
            avg_mae = round(sum(mae_list) / len(mae_list), 1) if mae_list else 0.0
            
            return {
                "total_samples": len(points),
                "avg_mfe_pips": avg_mfe,
                "avg_mae_pips": avg_mae,
                "matrix_points": points
            }

journal_analytics_service = JournalAnalyticsService()
