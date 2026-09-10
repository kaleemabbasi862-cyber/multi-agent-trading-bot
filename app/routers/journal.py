from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from app.services.journal_analytics import journal_analytics_service

router = APIRouter(prefix="/api/journal", tags=["Trade Journal & Analytics"])

class JournalNotesUpdateRequest(BaseModel):
    notes: str = Field(..., example="Clean breakout confirmed by 5 agents. Trailing SL executed properly.")

@router.get("/entries")
async def get_journal_entries(
    symbol: Optional[str] = Query(None, description="Symbol filter e.g. XAUUSD"),
    regime: Optional[str] = Query(None, description="Market regime filter e.g. TRENDING"),
    strategy: Optional[str] = Query(None, description="Strategy name filter"),
    outcome: Optional[str] = Query(None, description="WIN, LOSS, or BREAKEVEN"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """Returns filterable trade journal entries with MFE, MAE, and trade efficiency metrics."""
    return journal_analytics_service.get_journal_entries(
        symbol=symbol,
        regime=regime,
        strategy=strategy,
        outcome=outcome,
        limit=limit,
        offset=offset
    )

@router.get("/entry/{entry_id}")
async def get_journal_entry_details(entry_id: str):
    """Returns single journal entry details with full Decision DNA snapshot."""
    entry = journal_analytics_service.get_entry_details(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Journal entry #{entry_id} not found.")
    return entry

@router.put("/entry/{entry_id}/notes")
async def update_journal_entry_notes(entry_id: str, req: JournalNotesUpdateRequest):
    """Updates trader notes on a specific journal entry."""
    success = journal_analytics_service.update_journal_notes(entry_id, req.notes)
    if not success:
        raise HTTPException(status_code=404, detail=f"Could not update journal entry #{entry_id}.")
    return {"status": "SUCCESS", "message": f"Updated notes for #{entry_id}"}

@router.get("/mfe-mae-matrix")
async def get_mfe_mae_matrix(limit: int = Query(100, ge=10, le=500)):
    """Returns Maximum Favorable Excursion vs Maximum Adverse Excursion distribution coordinates."""
    return journal_analytics_service.get_mfe_mae_matrix(limit=limit)
