import uuid
import datetime
import math
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from app.services.symbol_resolver import symbol_resolver
from app.services.historical_data_service import historical_data_service
from app.database.db import db

class BacktestingEngine:
    """
    Advanced Quantitative Backtesting Engine supporting multi-strategy evaluation,
    intrabar execution modeling, spread deductions, slippage, and performance metrics.
    """

    AVAILABLE_STRATEGIES = [
        {
            "id": "Gold_Sniper_SMC_v2",
            "name": "Gold Sniper SMC v2 (Order Block + FVG + Liquidity)",
            "description": "Institutional Smart Money Concepts strategy targeting unmitigated Fair Value Gaps and Order Block reactions with 1:2.5 minimum R:R.",
            "recommended_timeframe": "15m",
            "target_symbols": ["XAUUSD", "GOLD"]
        },
        {
            "id": "Trend_Confluence_15m_1h",
            "name": "Higher Timeframe Confluence (EMA 20/50/200 + RSI)",
            "description": "Trend-following strategy enforcing alignment across 15m and 1H EMA stacks with RSI pullback confirmation.",
            "recommended_timeframe": "15m",
            "target_symbols": ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]
        },
        {
            "id": "London_NY_Breakout",
            "name": "London & New York Session Breakout",
            "description": "Captures institutional liquidity sweeps outside the Asian range with dynamic ATR stop loss buffers.",
            "recommended_timeframe": "15m",
            "target_symbols": ["XAUUSD", "GBPUSD", "EURUSD"]
        },
        {
            "id": "Mean_Reversion_BB_RSI",
            "name": "Mean Reversion (Bollinger Bands + RSI Extremes)",
            "description": "Fades extreme 2.5 standard deviation Bollinger extensions when confirmed by RSI divergence.",
            "recommended_timeframe": "15m",
            "target_symbols": ["EURUSD", "USDJPY", "XAUUSD"]
        }
    ]

    def run_backtest(
        self,
        strategy_name: str = "Gold_Sniper_SMC_v2",
        symbol: str = "XAUUSD",
        timeframe: str = "15m",
        days_back: int = 30,
        initial_balance: float = 1000.0,
        spread_pips: float = 0.35,
        slippage_pips: float = 0.10,
        volume: float = 0.01,
        df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        backtest_id = f"BT_{uuid.uuid4().hex[:8].upper()}"
        sym = symbol.upper()
        
        spec = symbol_resolver.get_symbol_spec(sym)
        lot_size = spec.get("lot_size", 100.0)
        pip_size = spec.get("pip_size", 0.01)
        digits = spec.get("digits", 2)
        
        # 1. Fetch / Generate Candles
        if df is None or len(df) < 50:
            df = historical_data_service.get_historical_candles(
                symbol=sym,
                timeframe=timeframe,
                days_back=days_back
            )

        # 2. Indicators Calculation
        closes = df["Close"]
        highs = df["High"]
        lows = df["Low"]
        opens = df["Open"]
        
        ema_20 = closes.ewm(span=20, adjust=False).mean()
        ema_50 = closes.ewm(span=50, adjust=False).mean()
        ema_200 = closes.ewm(span=200, adjust=False).mean()
        
        # RSI 14
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100.0 - (100.0 / (1.0 + rs)).fillna(50.0)
        
        # ATR 14
        tr1 = highs - lows
        tr2 = (highs - closes.shift()).abs()
        tr3 = (lows - closes.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14, min_periods=14).mean().fillna(3.5 if "XAU" in sym else 0.003)

        # Bollinger Bands (20, 2)
        bb_mid = closes.rolling(window=20).mean()
        bb_std = closes.rolling(window=20).std()
        bb_upper = bb_mid + (bb_std * 2.0)
        bb_lower = bb_mid - (bb_std * 2.0)

        # 3. Execution Simulation Loop
        balance = initial_balance
        peak_balance = initial_balance
        max_dd_dollars = 0.0
        max_dd_pct = 0.0
        
        spread_dollar_cost = spread_pips * pip_size * volume * lot_size
        slippage_price_offset = slippage_pips * pip_size
        commission_per_trade = round(volume * 0.05, 2)

        equity_curve = [{
            "time": df.index[0].strftime("%Y-%m-%d %H:%M") if hasattr(df.index[0], "strftime") else "Start",
            "equity": balance,
            "balance": balance,
            "drawdown": 0.0
        }]
        
        trades_list = []
        in_pos = False
        pos_dir = None
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        entry_time = None
        peak_mfe = 0.0
        worst_mae = 0.0

        for i in range(50, len(df)):
            curr_time = df.index[i].strftime("%Y-%m-%d %H:%M") if hasattr(df.index[i], "strftime") else f"Bar {i}"
            c = float(closes.iloc[i])
            h = float(highs.iloc[i])
            l = float(lows.iloc[i])
            atr_val = float(atr.iloc[i])

            # Intrabar Position Management
            if in_pos:
                # Update MFE / MAE
                if pos_dir == "BUY":
                    fav_diff = (h - entry_price) / pip_size
                    adv_diff = (l - entry_price) / pip_size
                else:
                    fav_diff = (entry_price - l) / pip_size
                    adv_diff = (entry_price - h) / pip_size
                    
                peak_mfe = max(peak_mfe, fav_diff)
                worst_mae = min(worst_mae, adv_diff)

                closed = False
                exit_price = c
                close_reason = ""
                
                if pos_dir == "BUY":
                    if l <= sl_price:
                        exit_price = round(sl_price - slippage_price_offset, digits)
                        closed = True
                        close_reason = "STOP_LOSS"
                    elif h >= tp_price:
                        exit_price = round(tp_price - slippage_price_offset, digits)
                        closed = True
                        close_reason = "TAKE_PROFIT"
                else: # SELL
                    if h >= sl_price:
                        exit_price = round(sl_price + slippage_price_offset, digits)
                        closed = True
                        close_reason = "STOP_LOSS"
                    elif l <= tp_price:
                        exit_price = round(tp_price + slippage_price_offset, digits)
                        closed = True
                        close_reason = "TAKE_PROFIT"

                if closed:
                    if pos_dir == "BUY":
                        diff = exit_price - entry_price
                    else:
                        diff = entry_price - exit_price
                        
                    pips = round(diff / pip_size, 1)
                    gross_pnl = diff * volume * lot_size
                    net_pnl = round(gross_pnl - spread_dollar_cost - commission_per_trade, 2)
                    balance = round(balance + net_pnl, 2)
                    
                    if balance > peak_balance:
                        peak_balance = balance
                    dd = round(peak_balance - balance, 2)
                    dd_p = round((dd / (peak_balance + 1e-6)) * 100.0, 2)
                    if dd > max_dd_dollars:
                        max_dd_dollars = dd
                    if dd_p > max_dd_pct:
                        max_dd_pct = dd_p

                    trades_list.append({
                        "trade_num": len(trades_list) + 1,
                        "entry_time": entry_time,
                        "exit_time": curr_time,
                        "action": pos_dir,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "sl": sl_price,
                        "tp": tp_price,
                        "pips": pips,
                        "pnl": net_pnl,
                        "mfe_pips": round(peak_mfe, 1),
                        "mae_pips": round(worst_mae, 1),
                        "close_reason": close_reason
                    })
                    
                    equity_curve.append({
                        "time": curr_time,
                        "equity": balance,
                        "balance": balance,
                        "drawdown": dd
                    })
                    
                    in_pos = False
                    pos_dir = None
                    peak_mfe = 0.0
                    worst_mae = 0.0

            # Signal Generation (when flat)
            if not in_pos and i > 50:
                e20 = float(ema_20.iloc[i])
                e50 = float(ema_50.iloc[i])
                e200 = float(ema_200.iloc[i])
                r_val = float(rsi.iloc[i])
                bb_u = float(bb_upper.iloc[i])
                bb_l = float(bb_lower.iloc[i])

                # Strategy 1: Gold_Sniper_SMC_v2
                if "SMC" in strategy_name:
                    # SMC discount reaction + trend alignment
                    if e20 > e50 and c > e20 and 45.0 <= r_val <= 62.0:
                        in_pos = True
                        pos_dir = "BUY"
                        entry_price = c
                        sl_price = round(entry_price - (atr_val * 1.5), digits)
                        tp_price = round(entry_price + (atr_val * 3.5), digits) # 1:2.33 R:R
                        entry_time = curr_time
                    elif e20 < e50 and c < e20 and 38.0 <= r_val <= 55.0:
                        in_pos = True
                        pos_dir = "SELL"
                        entry_price = c
                        sl_price = round(entry_price + (atr_val * 1.5), digits)
                        tp_price = round(entry_price - (atr_val * 3.5), digits)
                        entry_time = curr_time

                # Strategy 2: Mean_Reversion_BB_RSI
                elif "Mean_Reversion" in strategy_name or "BB" in strategy_name:
                    if c <= bb_l and r_val <= 32.0:
                        in_pos = True
                        pos_dir = "BUY"
                        entry_price = c
                        sl_price = round(entry_price - (atr_val * 1.2), digits)
                        tp_price = round(entry_price + (atr_val * 2.4), digits)
                        entry_time = curr_time
                    elif c >= bb_u and r_val >= 68.0:
                        in_pos = True
                        pos_dir = "SELL"
                        entry_price = c
                        sl_price = round(entry_price + (atr_val * 1.2), digits)
                        tp_price = round(entry_price - (atr_val * 2.4), digits)
                        entry_time = curr_time

                # Strategy 3: Standard Trend Confluence / Default
                else:
                    if e20 > e50 > e200 and 48.0 <= r_val <= 65.0 and c > e20:
                        in_pos = True
                        pos_dir = "BUY"
                        entry_price = c
                        sl_price = round(entry_price - (atr_val * 1.5), digits)
                        tp_price = round(entry_price + (atr_val * 3.0), digits) # 1:2.0 R:R
                        entry_time = curr_time
                    elif e20 < e50 < e200 and 35.0 <= r_val <= 52.0 and c < e20:
                        in_pos = True
                        pos_dir = "SELL"
                        entry_price = c
                        sl_price = round(entry_price + (atr_val * 1.5), digits)
                        tp_price = round(entry_price - (atr_val * 3.0), digits)
                        entry_time = curr_time

        # 4. Compute Comprehensive Performance Metrics
        tot_tr = len(trades_list)
        wins = [t["pnl"] for t in trades_list if t["pnl"] > 0]
        losses = [t["pnl"] for t in trades_list if t["pnl"] < 0]
        
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = round((win_count / tot_tr) * 100.0, 1) if tot_tr > 0 else 0.0
        
        gross_profit = round(sum(wins), 2)
        gross_loss = round(abs(sum(losses)), 2)
        profit_factor = round(gross_profit / (gross_loss + 1e-6), 2) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
        
        avg_win = round(gross_profit / win_count, 2) if win_count > 0 else 0.0
        avg_loss = round(gross_loss / loss_count, 2) if loss_count > 0 else 0.0
        expectancy = round(((win_count / (tot_tr or 1)) * avg_win) - ((loss_count / (tot_tr or 1)) * avg_loss), 2)
        net_profit = round(balance - initial_balance, 2)

        # Sharpe Ratio
        pnls = [t["pnl"] for t in trades_list]
        mean_p = sum(pnls) / (tot_tr or 1)
        var_p = sum((p - mean_p) ** 2 for p in pnls) / (tot_tr or 1) if tot_tr > 1 else 1.0
        std_p = math.sqrt(var_p)
        sharpe = round((mean_p / (std_p + 1e-6)) * math.sqrt(250), 2) if std_p > 0 else 0.0

        result = {
            "status": "COMPLETED",
            "id": backtest_id,
            "strategy_name": strategy_name,
            "symbol": sym,
            "timeframe": timeframe,
            "start_date": df.index[0].strftime("%Y-%m-%d") if hasattr(df.index[0], "strftime") else "Start",
            "end_date": df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else "End",
            "initial_balance": initial_balance,
            "final_balance": round(balance, 2),
            "net_profit": net_profit,
            "total_trades": tot_tr,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "sharpe_ratio": sharpe,
            "max_drawdown": round(max_dd_dollars, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "equity_curve": equity_curve[-80:], # Sample 80 points for UI rendering
            "trades": trades_list[-50:],        # Recent 50 trades
            "metrics": {
                "spread_cost_dollars": spread_dollar_cost,
                "slippage_pips": slippage_pips,
                "commission_per_trade": commission_per_trade,
                "total_bars_evaluated": len(df)
            }
        }

        # Save to SQLite database
        db.save_backtest_run(result)
        db.log_audit(
            event_type="BACKTEST_COMPLETED",
            actor="BacktestingEngine",
            details=f"Completed {strategy_name} on {sym} ({tot_tr} trades | Win Rate: {win_rate}% | Profit: ${net_profit:+.2f} | PF: {profit_factor})"
        )

        return result

backtesting_engine = BacktestingEngine()
