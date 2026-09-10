import uuid
import math
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from app.services.historical_data_service import historical_data_service
from app.services.backtesting_engine import backtesting_engine

class WalkForwardValidationEngine:
    """
    Evaluates strategy robustness and prevents curve-fitting via multi-fold
    In-Sample (IS) training and Out-of-Sample (OOS) testing cross-validation.
    """

    @staticmethod
    def run_walk_forward_validation(
        strategy_name: str = "Gold_Sniper_SMC_v2",
        symbol: str = "XAUUSD",
        timeframe: str = "15m",
        total_days: int = 60,
        num_folds: int = 4,
        is_ratio: float = 0.70, # 70% In-Sample, 30% Out-of-Sample
        initial_balance: float = 1000.0
    ) -> Dict[str, Any]:
        val_id = f"WF_{uuid.uuid4().hex[:8].upper()}"
        
        # 1. Fetch entire historical dataset
        df = historical_data_service.get_historical_candles(
            symbol=symbol,
            timeframe=timeframe,
            days_back=total_days
        )
        
        total_bars = len(df)
        if total_bars < 200:
            total_bars = 200
            
        fold_size = int(total_bars / num_folds)
        folds_results = []
        is_wfes = []
        
        for fold_idx in range(num_folds):
            start_bar = fold_idx * int(fold_size * 0.75) # overlapping rolling window
            end_bar = min(total_bars, start_bar + fold_size)
            if end_bar - start_bar < 60:
                continue
                
            fold_df = df.iloc[start_bar:end_bar]
            is_split_point = int(len(fold_df) * is_ratio)
            
            is_df = fold_df.iloc[:is_split_point]
            oos_df = fold_df.iloc[is_split_point:]
            
            # Run In-Sample Backtest
            is_res = backtesting_engine.run_backtest(
                strategy_name=strategy_name,
                symbol=symbol,
                timeframe=timeframe,
                initial_balance=initial_balance,
                df=is_df
            )
            
            # Run Out-of-Sample Backtest
            oos_res = backtesting_engine.run_backtest(
                strategy_name=strategy_name,
                symbol=symbol,
                timeframe=timeframe,
                initial_balance=initial_balance,
                df=oos_df
            )
            
            # Compute Walk-Forward Efficiency for this fold
            is_return = is_res.get("net_profit", 0.0)
            oos_return = oos_res.get("net_profit", 0.0)
            
            # Normalized Annualized WFE calculation
            is_norm_ret = (is_return / max(1, len(is_df))) * 1000.0
            oos_norm_ret = (oos_return / max(1, len(oos_df))) * 1000.0
            
            if is_norm_ret > 0:
                wfe = round((oos_norm_ret / is_norm_ret) * 100.0, 1)
            elif oos_norm_ret > 0:
                wfe = 100.0
            else:
                wfe = 0.0
                
            wfe = max(0.0, min(150.0, wfe))
            is_wfes.append(wfe)
            
            folds_results.append({
                "fold_num": fold_idx + 1,
                "in_sample": {
                    "bars": len(is_df),
                    "candles_count": len(is_df),
                    "trades": is_res.get("total_trades", 0),
                    "win_rate": is_res.get("win_rate", 0.0),
                    "profit_factor": is_res.get("profit_factor", 1.0),
                    "net_profit": is_res.get("net_profit", 0.0),
                    "max_drawdown": is_res.get("max_drawdown", 0.0)
                },
                "out_of_sample": {
                    "bars": len(oos_df),
                    "candles_count": len(oos_df),
                    "trades": oos_res.get("total_trades", 0),
                    "win_rate": oos_res.get("win_rate", 0.0),
                    "profit_factor": oos_res.get("profit_factor", 1.0),
                    "net_profit": oos_res.get("net_profit", 0.0),
                    "max_drawdown": oos_res.get("max_drawdown", 0.0)
                },
                "walk_forward_efficiency": wfe
            })
            
        avg_wfe = round(sum(is_wfes) / len(is_wfes), 1) if is_wfes else 0.0
        
        # Robustness Classification
        if avg_wfe >= 55.0:
            verdict = "ROBUST_INSTITUTIONAL"
            explanation = "Strategy exhibits high generalizability with strong Out-of-Sample profit retention (WFE >= 55%)."
        elif avg_wfe >= 35.0:
            verdict = "ACCEPTABLE_MODERATE"
            explanation = "Strategy performs adequately out-of-sample with moderate decay."
        else:
            verdict = "OVERFITTED_HIGH_RISK"
            explanation = "Significant performance drop in out-of-sample testing indicates curve-fitting."

        return {
            "status": "COMPLETED",
            "validation_id": val_id,
            "strategy_name": strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "total_days_evaluated": total_days,
            "num_folds": len(folds_results),
            "average_wfe_pct": avg_wfe,
            "verdict": verdict,
            "explanation": explanation,
            "folds": folds_results
        }

walk_forward_engine = WalkForwardValidationEngine()
