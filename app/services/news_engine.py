import datetime
import re
import json
import logging
import threading
import time
from typing import Dict, Any, List, Optional
import yfinance as yf
from app.database.db import db

logger = logging.getLogger("TradeTalk.NewsEngine")

# Multi-word compound phrases (evaluated first with highest priority)
COMPOUND_PHRASES = {
    # Bullish Drivers for Gold / Risk Assets
    "rate cut": 0.65,
    "rate cuts": 0.65,
    "emergency rate cut": 0.85,
    "rate reduction": 0.60,
    "monetary easing": 0.60,
    "quantitative easing": 0.75,
    "cooling inflation": 0.55,
    "inflation cools": 0.55,
    "inflation softens": 0.55,
    "cpi slows": 0.55,
    "soft landing": 0.40,
    "fed pauses": 0.45,
    "dovish pivot": 0.70,
    "dovish remarks": 0.60,
    "dovish fed": 0.65,
    "safe haven": 0.65,
    "safe-haven": 0.65,
    "safe haven demand": 0.75,
    "gold demand": 0.60,
    "central bank buying": 0.70,
    "central bank accumulation": 0.70,
    "gold rallies": 0.70,
    "gold rally": 0.70,
    "gold surges": 0.80,
    "gold surging": 0.80,
    "gold jumps": 0.65,
    "gold breaks out": 0.75,
    "precious metals rally": 0.75,
    "all-time high": 0.70,
    "record high": 0.70,
    "record highs": 0.70,
    "dollar weakens": 0.60,
    "dollar slumps": 0.65,
    "dollar drops": 0.55,
    "dollar slides": 0.55,
    "usd drops": 0.55,
    "treasury yields slide": 0.55,
    "treasury yields fall": 0.55,
    "yields drop": 0.50,
    "yield drop": 0.50,
    "yields decline": 0.50,

    # Bearish Drivers
    "rate hike": -0.65,
    "rate hikes": -0.65,
    "aggressive rate hike": -0.85,
    "hiking rates": -0.65,
    "monetary tightening": -0.60,
    "quantitative tightening": -0.65,
    "hot cpi": -0.70,
    "cpi surges": -0.70,
    "cpi accelerates": -0.70,
    "hot inflation": -0.70,
    "inflation surges": -0.70,
    "inflation accelerates": -0.70,
    "hawkish fed": -0.65,
    "hawkish remarks": -0.60,
    "hawkish rate hike": -0.75,
    "higher for longer": -0.55,
    "strong dollar": -0.55,
    "dollar soaring": -0.65,
    "dollar surges": -0.65,
    "dollar surges higher": -0.70,
    "usd rallies": -0.65,
    "usd surges": -0.65,
    "yield spike": -0.65,
    "yields jump": -0.55,
    "yields surge": -0.60,
    "treasury yields climb": -0.55,
    "gold plunges": -0.80,
    "gold plunging": -0.80,
    "gold slumps": -0.70,
    "gold selloff": -0.75,
    "gold drops": -0.55,
    "gold tumbling": -0.70,
    "recession fears": -0.55,
    "liquidation wave": -0.70
}

# Standalone single words (matched only after compound phrases)
STANDALONE_WORDS = {
    # Bullish
    "dovish": 0.50,
    "bullish": 0.50,
    "rally": 0.35,
    "rallies": 0.35,
    "rallying": 0.35,
    "optimism": 0.30,
    "breakout": 0.40,
    "upside": 0.30,

    # Bearish
    "hawkish": -0.50,
    "bearish": -0.50,
    "selloff": -0.55,
    "plunge": -0.65,
    "plunges": -0.65,
    "plunging": -0.65,
    "slump": -0.50,
    "slumps": -0.50,
    "slumping": -0.50,
    "crash": -0.75,
    "panic": -0.65,
    "tumble": -0.55,
    "tumbling": -0.55,
    "downside": -0.30
}

INTENSIFIERS = {
    "massive": 1.4,
    "historic": 1.3,
    "huge": 1.3,
    "aggressive": 1.4,
    "shock": 1.3,
    "unprecedented": 1.4,
    "heavy": 1.2,
    "sharp": 1.2,
    "mild": 0.7,
    "slight": 0.5
}


class NewsEngine:
    """
    NLP Financial Sentiment Analysis & Multi-Source Live News Engine.
    Evaluates real financial headlines, quantifies sentiment scores, identifies asset biases, and stores results in SQLite.
    """

    def __init__(self):
        self._last_sync_timestamp: float = 0.0
        self._sync_lock = threading.Lock()
        self._initial_sync()

    def _initial_sync(self):
        """Attempts initial live news sync on startup."""
        try:
            threading.Thread(target=self.sync_live_news, daemon=True).start()
        except Exception as e:
            logger.error(f"Error starting live news sync thread: {e}")

    def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """
        Performs NLP keyword and polarity sentiment analysis on financial news text.
        Returns sentiment classification, continuous polarity score [-1.0 to +1.0], and extracted signals.
        """
        text_lower = text.lower()

        # Check multiplier from intensifiers
        multiplier = 1.0
        for word, factor in INTENSIFIERS.items():
            if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
                multiplier = max(multiplier, factor)

        total_score = 0.0
        matches = []
        matched_spans = []

        # 1. Match compound phrases first (ordered by longest phrase first)
        sorted_compounds = sorted(COMPOUND_PHRASES.items(), key=lambda x: len(x[0]), reverse=True)
        for phrase, weight in sorted_compounds:
            for match in re.finditer(r'\b' + re.escape(phrase) + r'\b', text_lower):
                span = (match.start(), match.end())
                if not any(s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1] for s in matched_spans):
                    matched_spans.append(span)
                    match_val = weight * multiplier
                    total_score += match_val
                    matches.append({"phrase": phrase, "impact": "BULLISH" if weight > 0 else "BEARISH", "weight": match_val})

        # 2. Match standalone single words in non-overlapping parts
        for word, weight in STANDALONE_WORDS.items():
            for match in re.finditer(r'\b' + re.escape(word) + r'\b', text_lower):
                span = (match.start(), match.end())
                if not any(s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1] for s in matched_spans):
                    matched_spans.append(span)
                    match_val = weight * multiplier
                    total_score += match_val
                    matches.append({"phrase": word, "impact": "BULLISH" if weight > 0 else "BEARISH", "weight": match_val})

        # Normalize score into range [-1.0, 1.0]
        if total_score > 1.0:
            normalized_score = 1.0
        elif total_score < -1.0:
            normalized_score = -1.0
        else:
            normalized_score = round(total_score, 3)

        # Classify label
        if normalized_score >= 0.40:
            sentiment_label = "STRONG_BULLISH"
        elif normalized_score >= 0.15:
            sentiment_label = "BULLISH"
        elif normalized_score <= -0.40:
            sentiment_label = "STRONG_BEARISH"
        elif normalized_score <= -0.15:
            sentiment_label = "BEARISH"
        else:
            sentiment_label = "NEUTRAL"

        # Asset-specific implications
        gold_implication = "NEUTRAL"
        usd_implication = "NEUTRAL"

        if "gold" in text_lower or "precious metals" in text_lower or "xau" in text_lower:
            if normalized_score > 0.1:
                gold_implication = "BULLISH_GOLD"
            elif normalized_score < -0.1:
                gold_implication = "BEARISH_GOLD"
        elif "rate cut" in text_lower or "dovish" in text_lower or "dollar weakens" in text_lower:
            gold_implication = "BULLISH_GOLD"
            usd_implication = "BEARISH_USD"
        elif "rate hike" in text_lower or "hawkish" in text_lower or "dollar surges" in text_lower:
            gold_implication = "BEARISH_GOLD"
            usd_implication = "BULLISH_USD"

        return {
            "sentiment": sentiment_label,
            "sentiment_score": normalized_score,
            "gold_implication": gold_implication,
            "usd_implication": usd_implication,
            "matches": matches
        }

    def detect_affected_symbols(self, text: str) -> List[str]:
        """Infers affected currency pairs / assets based on text content."""
        text_lower = text.lower()
        symbols = set()

        if any(w in text_lower for w in ["gold", "xau", "precious metals", "bullion"]):
            symbols.add("XAUUSD")
        if any(w in text_lower for w in ["dollar", "fed", "fomc", "powell", "treasury", "cpi", "nfp"]):
            symbols.update(["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"])
        if any(w in text_lower for w in ["euro", "ecb", "lagarde", "eurozone"]):
            symbols.update(["EURUSD", "EURGBP", "EURJPY"])
        if any(w in text_lower for w in ["pound", "boe", "bailey", "uk", "britain"]):
            symbols.update(["GBPUSD", "EURGBP", "GBPJPY"])
        if any(w in text_lower for w in ["yen", "boj", "ueda", "japan"]):
            symbols.update(["USDJPY", "EURJPY", "GBPJPY"])
        if any(w in text_lower for w in ["oil", "crude", "opec", "wti", "brent"]):
            symbols.update(["USOUSD", "USDCAD"])

        if not symbols:
            symbols.add("XAUUSD")

        return sorted(list(symbols))

    def ingest_news(
        self,
        headline: str,
        source: str = "LIVE_MARKET",
        category: str = "COMMODITIES",
        affected_symbols: Optional[List[str]] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyzes and saves a news headline into the SQLite database.
        """
        analysis = self.analyze_sentiment(headline)
        detected_syms = affected_symbols or self.detect_affected_symbols(headline)
        now = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()

        news_record = {
            "headline": headline,
            "source": source,
            "timestamp": now,
            "category": category,
            "sentiment": analysis["sentiment"],
            "sentiment_score": analysis["sentiment_score"],
            "affected_symbols": detected_syms
        }

        news_id = db.save_news_item(news_record)
        news_record["id"] = news_id
        news_record["analysis"] = analysis

        return news_record

    def sync_live_news(self, force: bool = False) -> int:
        """
        Fetches genuine live market news headlines for Gold and USD macro from Yahoo Finance ticker feeds.
        """
        now_ts = time.time()
        if not force and (now_ts - self._last_sync_timestamp < 900.0):
            return 0

        with self._sync_lock:
            if not force and (now_ts - self._last_sync_timestamp < 900.0):
                return 0

            ingested_count = 0
            tickers_to_query = [
                ("GC=F", "COMMODITIES", ["XAUUSD"]),
                ("DX-Y.NYB", "FOREX", ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]),
                ("EURUSD=X", "FOREX", ["EURUSD", "XAUUSD"])
            ]

            for yf_sym, cat, default_aff in tickers_to_query:
                try:
                    tk = yf.Ticker(yf_sym)
                    news_items = tk.news
                    if not news_items or not isinstance(news_items, list):
                        continue

                    for item in news_items:
                        title = item.get("title")
                        if not title and isinstance(item.get("content"), dict):
                            title = item["content"].get("title")

                        if not title:
                            continue

                        provider = item.get("publisher", "Yahoo Finance")
                        if isinstance(item.get("content"), dict):
                            provider = item["content"].get("provider", {}).get("displayName", provider)

                        ts_epoch = item.get("providerPublishTime")
                        if ts_epoch:
                            ts_iso = datetime.datetime.fromtimestamp(ts_epoch, datetime.timezone.utc).isoformat()
                        else:
                            ts_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

                        self.ingest_news(
                            headline=title,
                            source=f"LIVE_{provider.upper()[:15]}",
                            category=cat,
                            affected_symbols=default_aff,
                            timestamp=ts_iso
                        )
                        ingested_count += 1
                except Exception as e:
                    logger.warning(f"Error fetching live news for {yf_sym}: {e}")

            self._last_sync_timestamp = time.time()
            if ingested_count > 0:
                logger.info(f"Successfully ingested {ingested_count} live financial news items.")
            return ingested_count

    def get_live_sentiment(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        """Fetches aggregated sentiment metrics from database for symbol."""
        if time.time() - self._last_sync_timestamp > 1800.0:
            threading.Thread(target=self.sync_live_news, daemon=True).start()
        return db.get_market_sentiment_summary(symbol=symbol)


news_engine = NewsEngine()
