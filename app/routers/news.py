import logging
from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from app.database.db import db
from app.services.news_engine import news_engine

logger = logging.getLogger("TradeTalk.Router.News")
router = APIRouter(prefix="/api/news", tags=["News & Sentiment"])


@router.get("")
@router.get("/")
async def get_recent_news(
    category: Optional[str] = None,
    sentiment: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200)
):
    """Retrieves recent news items and sentiment analysis from SQLite."""
    try:
        news_items = db.get_recent_news(limit=limit, category=category, sentiment=sentiment)
        return {
            "status": "SUCCESS",
            "count": len(news_items),
            "news": news_items
        }
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AnalyzeNewsRequest(BaseModel):
    headline: str
    source: Optional[str] = "USER_INPUT"
    category: Optional[str] = "FOREX"
    affected_symbols: Optional[List[str]] = None


@router.post("/analyze")
async def analyze_and_ingest_news(req: AnalyzeNewsRequest):
    """
    Performs real-time financial NLP sentiment analysis on a news headline,
    computes asset biases, and records the item in SQLite.
    """
    try:
        if not req.headline or not req.headline.strip():
            raise HTTPException(status_code=400, detail="Headline text cannot be empty.")
        
        result = news_engine.ingest_news(
            headline=req.headline.strip(),
            source=req.source or "USER_INPUT",
            category=req.category or "FOREX",
            affected_symbols=req.affected_symbols
        )
        return {
            "status": "SUCCESS",
            "data": result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing news headline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sentiment-summary")
async def get_sentiment_summary(symbol: str = Query(default="XAUUSD")):
    """Calculates aggregated sentiment score, USD bias, and Gold bias."""
    try:
        summary = news_engine.get_live_sentiment(symbol=symbol)
        return {
            "status": "SUCCESS",
            "data": summary
        }
    except Exception as e:
        logger.error(f"Error fetching sentiment summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seed")
async def seed_market_news():
    """Seeds default financial news items into the database."""
    try:
        seeded = news_engine.seed_mock_news()
        return {
            "status": "SUCCESS",
            "message": f"Successfully seeded {len(seeded)} news headlines.",
            "count": len(seeded)
        }
    except Exception as e:
        logger.error(f"Error seeding news: {e}")
        raise HTTPException(status_code=500, detail=str(e))
