import uuid
import datetime
import math
import logging
from typing import Dict, Any, List, Optional
from app.services.symbol_resolver import symbol_resolver
from app.database.db import db, get_db_connection

logger = logging.getLogger("TradeTalk.PaperTradingEngine")

class PaperPosition:
    def __init__(
        self,
        position_id: str,
        symbol: str,
        direction: str,
        volume: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        signal_id: Optional[str] = None,
        strategy_name: str = "Autonomous",
        market_regime: str = "TRENDING",
        leverage: float = 100.0
    ):
        self.position_id = position_id
        self.symbol = symbol.upper()
        self.direction = direction.upper() # 'BUY' or 'SELL'
        self.volume = volume
        self.entry_price = entry_price
        self.current_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.signal_id = signal_id or ""
        self.strategy_name = strategy_name
        self.market_regime = market_regime
        self.leverage = leverage
        self.opened_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.closed_at: Optional[str] = None
        self.status = "OPEN" # 'OPEN' or 'CLOSED'
        self.exit_price: Optional[float] = None
        self.close_reason: Optional[str] = None
        
        # Financial metrics
        self.unrealized_pnl = 0.0
        self.realized_pnl = 0.0
        self.current_pips = 0.0
        self.realized_pips = 0.0
        self.commission = round(volume * 0.05, 2) # $0.05 per 0.01 lot simulation
        self.swap = 0.0
        
        # Excursion Tracking (MFE & MAE)
        self.peak_mfe_pips = 0.0 # Maximum Favorable Excursion
        self.peak_mfe_usd = 0.0
        self.worst_mae_pips = 0.0 # Maximum Adverse Excursion (stored as negative or 0)
        self.worst_mae_usd = 0.0
        
        # Contract Specifications
        spec = symbol_resolver.get_symbol_spec(self.symbol)
        self.lot_size = spec.get("lot_size", 100.0)
        self.pip_size = spec.get("pip_size", 0.01)
        self.digits = spec.get("digits", 2)
        
        # Margin Required = (Volume * LotSize * EntryPrice) / Leverage
        self.margin_required = round((self.volume * self.lot_size * self.entry_price) / self.leverage, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "volume": self.volume,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "signal_id": self.signal_id,
            "strategy_name": self.strategy_name,
            "market_regime": self.market_regime,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "current_pips": round(self.current_pips, 1),
            "realized_pips": round(self.realized_pips, 1),
            "peak_mfe_pips": round(self.peak_mfe_pips, 1),
            "peak_mfe_usd": round(self.peak_mfe_usd, 2),
            "worst_mae_pips": round(self.worst_mae_pips, 1),
            "worst_mae_usd": round(self.worst_mae_usd, 2),
            "margin_required": self.margin_required,
            "commission": self.commission,
            "swap": self.swap,
            "status": self.status,
            "exit_price": self.exit_price,
            "close_reason": self.close_reason,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at
        }


class PaperTradingEngine:
    def __init__(self, initial_balance: float = 1000.0, leverage: float = 100.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.open_positions: Dict[str, PaperPosition] = {}
        self.closed_positions: List[Dict[str, Any]] = []
        self._load_state_from_db()

    @property
    def equity(self) -> float:
        unrealized_sum = sum(pos.unrealized_pnl for pos in self.open_positions.values())
        return round(self.balance + unrealized_sum, 2)

    @property
    def used_margin(self) -> float:
        return round(sum(pos.margin_required for pos in self.open_positions.values()), 2)

    @property
    def free_margin(self) -> float:
        return round(self.equity - self.used_margin, 2)

    @property
    def margin_level(self) -> float:
        if self.used_margin <= 0:
            return 999999.0
        return round((self.equity / self.used_margin) * 100.0, 2)

    def get_account_summary(self) -> Dict[str, Any]:
        return {
            "account_id": "PAPER_VIRTUAL_01",
            "account_type": "PAPER",
            "currency": "USD",
            "initial_balance": self.initial_balance,
            "balance": round(self.balance, 2),
            "equity": self.equity,
            "margin": self.used_margin,
            "free_margin": self.free_margin,
            "margin_level": self.margin_level,
            "leverage": self.leverage,
            "open_positions_count": len(self.open_positions),
            "closed_positions_count": len(self.closed_positions),
            "total_realized_pnl": round(self.balance - self.initial_balance, 2)
        }

    def place_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        current_bid: float,
        current_ask: float,
        stop_loss: float,
        take_profit: float,
        signal_id: Optional[str] = None,
        strategy_name: str = "Autonomous",
        market_regime: str = "TRENDING",
        slippage_pips: float = 0.0
    ) -> Dict[str, Any]:
        """
        Executes a simulated paper order with authentic spread and slippage.
        """
        sym = symbol.upper()
        dir_clean = direction.upper()
        if dir_clean not in ("BUY", "SELL"):
            return {"status": "ERROR", "message": f"Invalid order direction: {direction}"}

        spec = symbol_resolver.get_symbol_spec(sym)
        min_vol = spec.get("min_volume", 0.01)
        max_vol = spec.get("max_volume", 100.0)
        vol_step = spec.get("volume_step", 0.01)
        pip_size = spec.get("pip_size", 0.01)
        digits = spec.get("digits", 2)

        # Clamping and stepping volume
        vol = max(min_vol, min(max_vol, volume))
        steps = math.floor((vol + 1e-9) / vol_step)
        vol = round(steps * vol_step, 4)

        # Simulated Execution Price (BUY at Ask, SELL at Bid + slippage)
        base_fill = current_ask if dir_clean == "BUY" else current_bid
        slippage_offset = (slippage_pips * pip_size) if dir_clean == "BUY" else -(slippage_pips * pip_size)
        fill_price = round(base_fill + slippage_offset, digits)

        pos_id = f"PAP_{uuid.uuid4().hex[:8].upper()}"
        pos = PaperPosition(
            position_id=pos_id,
            symbol=sym,
            direction=dir_clean,
            volume=vol,
            entry_price=fill_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            signal_id=signal_id,
            strategy_name=strategy_name,
            market_regime=market_regime,
            leverage=self.leverage
        )

        # Check Free Margin Sufficiency
        if self.free_margin < pos.margin_required:
            logger.warning(f"Paper execution rejected: Insufficient free margin (${self.free_margin:.2f} < ${pos.margin_required:.2f})")
            return {
                "status": "REJECTED_INSUFFICIENT_MARGIN",
                "message": f"Free margin (${self.free_margin:.2f}) is insufficient for required margin (${pos.margin_required:.2f})."
            }

        self.open_positions[pos_id] = pos
        
        # Persist to database trades table as PAPER trade
        trade_record = {
            "id": pos_id,
            "signal_id": signal_id or "",
            "mode": "PAPER",
            "broker_order_id": f"Paper Sim #{pos_id}",
            "ticket_id": pos_id,
            "symbol": sym,
            "direction": dir_clean,
            "entry_price": fill_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "volume": vol,
            "profit_loss": 0.0,
            "pips": 0.0,
            "status": "OPEN",
            "opened_at": pos.opened_at
        }
        db.save_trade(trade_record)
        db.log_audit(
            event_type="PAPER_TRADE_EXECUTED",
            actor="PaperTradingEngine",
            details=f"Simulated {dir_clean} {vol} {sym} @ ${fill_price:.2f} (SL: ${stop_loss:.2f}, TP: ${take_profit:.2f}) | Margin: ${pos.margin_required:.2f}"
        )

        logger.info(f"[Paper Trading] Executed #{pos_id}: {dir_clean} {vol} {sym} @ {fill_price}")
        return {
            "status": "EXECUTED_PAPER",
            "position": pos.to_dict()
        }

    def on_tick(self, symbol: str, bid: float, ask: float, high: Optional[float] = None, low: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        Processes real-time market tick across all open paper positions:
        - Updates Unrealized PnL and Pips
        - Tracks Maximum Favorable Excursion (MFE) & Maximum Adverse Excursion (MAE)
        - Triggers SL / TP closures when target levels are breached
        - Evaluates margin liquidation
        """
        sym = symbol.upper()
        closed_events: List[Dict[str, Any]] = []
        positions_to_close: List[tuple] = [] # (pos_id, exit_price, reason)

        for pos_id, pos in list(self.open_positions.items()):
            if pos.symbol != sym or pos.status != "OPEN":
                continue

            current_p = bid if pos.direction == "BUY" else ask
            pos.current_price = current_p

            # Calculate Price Difference & PnL
            if pos.direction == "BUY":
                price_diff = current_p - pos.entry_price
                pos.current_pips = price_diff / pos.pip_size
                pos.unrealized_pnl = round(price_diff * pos.volume * pos.lot_size - pos.commission, 2)
            else:
                price_diff = pos.entry_price - current_p
                pos.current_pips = price_diff / pos.pip_size
                pos.unrealized_pnl = round(price_diff * pos.volume * pos.lot_size - pos.commission, 2)

            # Update MFE / MAE Peak Excursions
            if pos.current_pips > pos.peak_mfe_pips:
                pos.peak_mfe_pips = pos.current_pips
                pos.peak_mfe_usd = max(pos.peak_mfe_usd, pos.unrealized_pnl)

            if pos.current_pips < pos.worst_mae_pips:
                pos.worst_mae_pips = pos.current_pips
                pos.worst_mae_usd = min(pos.worst_mae_usd, pos.unrealized_pnl)

            # Evaluate Stop Loss / Take Profit triggers
            h_val = high if high is not None else current_p
            l_val = low if low is not None else current_p

            if pos.direction == "BUY":
                if pos.stop_loss > 0 and l_val <= pos.stop_loss:
                    positions_to_close.append((pos_id, pos.stop_loss, "STOP_LOSS_HIT"))
                elif pos.take_profit > 0 and h_val >= pos.take_profit:
                    positions_to_close.append((pos_id, pos.take_profit, "TAKE_PROFIT_HIT"))
            else: # SELL
                if pos.stop_loss > 0 and h_val >= pos.stop_loss:
                    positions_to_close.append((pos_id, pos.stop_loss, "STOP_LOSS_HIT"))
                elif pos.take_profit > 0 and l_val <= pos.take_profit:
                    positions_to_close.append((pos_id, pos.take_profit, "TAKE_PROFIT_HIT"))

        # Close triggered positions
        for pos_id, exit_price, reason in positions_to_close:
            res = self.close_position(pos_id, exit_price=exit_price, reason=reason)
            if res.get("status") == "SUCCESS":
                closed_events.append(res)

        # Margin Call / Stop-out Check (Liquidation at < 50% Margin Level)
        if self.margin_level < 50.0 and len(self.open_positions) > 0:
            worst_pos = min(self.open_positions.values(), key=lambda p: p.unrealized_pnl)
            logger.warning(f"MARGIN CALL STOP-OUT: Liquidating position #{worst_pos.position_id} (Margin Level: {self.margin_level:.1f}%)")
            res = self.close_position(worst_pos.position_id, exit_price=worst_pos.current_price, reason="MARGIN_STOP_OUT")
            closed_events.append(res)

        return closed_events

    def close_position(self, position_id: str, exit_price: Optional[float] = None, reason: str = "MANUAL_CLOSE") -> Dict[str, Any]:
        """
        Closes an open paper position, updates account balance, and writes to database & journal.
        """
        pos = self.open_positions.pop(position_id, None)
        if not pos:
            return {"status": "ERROR", "message": f"Position #{position_id} not found in active open positions."}

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        fill_exit = exit_price if exit_price is not None else pos.current_price
        pos.exit_price = fill_exit
        pos.status = "CLOSED"
        pos.close_reason = reason
        pos.closed_at = now_iso

        if pos.direction == "BUY":
            price_diff = fill_exit - pos.entry_price
        else:
            price_diff = pos.entry_price - fill_exit

        pos.realized_pips = round(price_diff / pos.pip_size, 1)
        gross_pnl = price_diff * pos.volume * pos.lot_size
        net_pnl = round(gross_pnl - pos.commission + pos.swap, 2)
        pos.realized_pnl = net_pnl

        # Update Virtual Account Balance
        self.balance = round(self.balance + net_pnl, 2)

        # Update persistent SQLite record
        db.update_trade_status(
            trade_id=pos.position_id,
            status="CLOSED",
            exit_price=pos.exit_price,
            profit_loss=pos.realized_pnl,
            pips=pos.realized_pips,
            close_reason=reason
        )

        # Create Post-Trade Journal Entry
        entry_time = datetime.datetime.fromisoformat(pos.opened_at) if "T" in pos.opened_at else datetime.datetime.now(datetime.timezone.utc)
        exit_time = datetime.datetime.fromisoformat(pos.closed_at) if "T" in pos.closed_at else datetime.datetime.now(datetime.timezone.utc)
        duration_sec = max(1, int((exit_time - entry_time).total_seconds()))

        journal_entry = {
            "id": f"JRN_{pos.position_id}",
            "trade_id": pos.position_id,
            "symbol": pos.symbol,
            "direction": pos.direction,
            "strategy_name": pos.strategy_name,
            "market_regime": pos.market_regime,
            "mfe": pos.peak_mfe_pips,
            "mae": pos.worst_mae_pips,
            "trade_duration_seconds": duration_sec,
            "news_context": f"Simulated Paper Close ({reason})",
            "ai_reasoning": f"Autonomous execution with MFE: +{pos.peak_mfe_pips:.1f} pips, MAE: {pos.worst_mae_pips:.1f} pips. Exit reason: {reason}.",
            "notes": f"Paper Trade #{pos.position_id} result: ${pos.realized_pnl:.2f} ({pos.realized_pips:+.1f} pips)"
        }
        db.save_trade_journal_entry(journal_entry)

        db.log_audit(
            event_type="PAPER_TRADE_CLOSED",
            actor="PaperTradingEngine",
            details=f"Closed #{pos.position_id} ({pos.symbol} {pos.direction}) @ ${fill_exit:.2f} | PnL: ${pos.realized_pnl:+.2f} ({pos.realized_pips:+.1f} pips) | Reason: {reason} | New Balance: ${self.balance:.2f}"
        )

        dict_pos = pos.to_dict()
        self.closed_positions.append(dict_pos)
        logger.info(f"[Paper Trading] Closed #{pos.position_id}: PnL=${pos.realized_pnl:+.2f}, Balance=${self.balance:.2f}")

        return {
            "status": "SUCCESS",
            "position": dict_pos,
            "new_balance": self.balance,
            "new_equity": self.equity
        }

    def modify_position(self, position_id: str, stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> Dict[str, Any]:
        pos = self.open_positions.get(position_id)
        if not pos:
            return {"status": "ERROR", "message": f"Position #{position_id} not found."}

        if stop_loss is not None:
            pos.stop_loss = stop_loss
        if take_profit is not None:
            pos.take_profit = take_profit

        db.log_audit(
            event_type="PAPER_TRADE_MODIFIED",
            actor="PaperTradingEngine",
            details=f"Modified #{pos.position_id} SL=${pos.stop_loss:.2f}, TP=${pos.take_profit:.2f}"
        )
        return {"status": "SUCCESS", "position": pos.to_dict()}

    def reset_account(self, initial_balance: float = 1000.0) -> Dict[str, Any]:
        """Resets the virtual paper account to a fresh deposit state."""
        self.open_positions.clear()
        self.closed_positions.clear()
        self.initial_balance = initial_balance
        self.balance = initial_balance

        db.log_audit(
            event_type="PAPER_ACCOUNT_RESET",
            actor="UserOrAdmin",
            details=f"Reset Paper Account balance to initial deposit: ${initial_balance:.2f}"
        )
        return self.get_account_summary()

    def deposit_funds(self, amount: float) -> Dict[str, Any]:
        if amount <= 0:
            return {"status": "ERROR", "message": "Deposit amount must be positive."}
        self.balance = round(self.balance + amount, 2)
        db.log_audit(
            event_type="PAPER_FUNDS_DEPOSITED",
            actor="UserOrAdmin",
            details=f"Deposited ${amount:.2f} into paper account. New balance: ${self.balance:.2f}"
        )
        return self.get_account_summary()

    def _load_state_from_db(self):
        """Loads closed paper trades count or history from SQLite."""
        try:
            with get_db_connection() as conn:
                rows = conn.execute("SELECT * FROM trades WHERE mode = 'PAPER' AND status = 'CLOSED' ORDER BY closed_at ASC").fetchall()
                self.closed_positions = [dict(r) for r in rows]
                if self.closed_positions:
                    realized_sum = sum(float(r.get("profit_loss", 0.0)) for r in self.closed_positions)
                    self.balance = round(self.initial_balance + realized_sum, 2)
        except Exception as e:
            logger.warning(f"Could not load paper state from DB: {e}")

paper_trading_engine = PaperTradingEngine()
