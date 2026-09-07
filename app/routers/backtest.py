from fastapi import APIRouter
from app.database.models import BacktestRequest
from app.engine.backtester import backtester
from app.database.db import get_db_connection
import json

router = APIRouter(prefix="/api/backtest", tags=["Backtesting"])

@router.post("/run")
async def run_backtest_strategy(req: BacktestRequest):
    return backtester.run_backtest(req)

@router.get("/history")
async def get_backtest_history():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM strategy_backtests ORDER BY created_at DESC LIMIT 20").fetchall()
        results = []
        for r in rows:
            item = dict(r)
            if item.get("metrics_json"):
                try:
                    item["metrics"] = json.loads(item["metrics_json"])
                except Exception:
                    pass
            results.append(item)
        return results
