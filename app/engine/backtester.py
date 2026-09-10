import uuid
import datetime
import math
import numpy as np
import pandas as pd
from typing import Dict, Any, List
from app.database.models import BacktestRequest
from app.services.backtesting_engine import backtesting_engine as service_engine
from app.database.db import db

class StrategyLabBacktester:
    """
    Backtesting Engine with realistic spread, slippage, commission, and walk-forward verification.
    """

    def run_backtest(self, req: BacktestRequest) -> Dict[str, Any]:
        return service_engine.run_backtest(
            strategy_name=req.strategy_name,
            symbol=req.symbol,
            timeframe=req.timeframe,
            days_back=min(req.days_back, 60),
            initial_balance=req.initial_balance,
            spread_pips=req.spread_pips,
            slippage_pips=req.slippage_pips
        )

backtester = StrategyLabBacktester()
