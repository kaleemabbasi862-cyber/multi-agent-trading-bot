import time
import datetime
from typing import Dict, Any
from app.config import settings
from app.database.models import (
    SignalPayload,
    AgentDecisionOutput,
    AgentOperationalCriticality,
    AgentHealthStatus
)

class FundamentalSentimentAgent:
    name: str = "Fundamental & Sentiment Agent"
    weight: float = 0.15
    criticality: str = AgentOperationalCriticality.SAFETY_CRITICAL

    def evaluate(self, signal: SignalPayload, macro_data: Dict[str, Any]) -> AgentDecisionOutput:
        t_start = time.time()
        start_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        # Guard against missing or unavailable macroeconomic feed
        if not macro_data or macro_data.get("unavailable", False) or macro_data.get("feed_status") == "OFFLINE":
            end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return AgentDecisionOutput(
                agent_name=self.name,
                direction="NEUTRAL",
                score=0.0,
                decision="VETO",
                reasoning_summary="NEWS_DATA_UNAVAILABLE: Economic calendar / macro feed is offline or unverified. Fail-closed safety gate active.",
                operational_criticality=self.criticality,
                health_status=AgentHealthStatus.UNAVAILABLE,
                execution_started_at=start_iso,
                execution_completed_at=end_iso,
                execution_latency_ms=round((time.time() - t_start) * 1000, 2),
                data_source="Economic Calendar API",
                confidence=0.0,
                error="NEWS_DATA_UNAVAILABLE",
                decision_id=signal.id,
                metrics={"feed_status": "OFFLINE", "unavailable": True}
            )

        act = signal.action.upper()
        minutes_to_high_impact = macro_data.get("minutes_to_next_high_impact_news", 999)
        minutes_since_last_event = macro_data.get("minutes_since_last_event", 999)
        next_event_name = macro_data.get("next_event_name", "None")
        usd_sentiment = macro_data.get("usd_sentiment", "NEUTRAL") # BULLISH_USD, BEARISH_USD, NEUTRAL
        data_source = macro_data.get("data_source", "ForexFactory / SQLite Calendar Feed")
        
        reasons = []
        score = 85.0
        direction = "NEUTRAL"
        
        # 1. High-Impact News Window Clearance Check
        in_pre_news_block = minutes_to_high_impact <= settings.NEWS_PRE_BLOCK_MINUTES
        in_post_news_cooldown = minutes_since_last_event <= settings.NEWS_POST_COOLDOWN_MINUTES
        
        is_fomc = "FOMC" in next_event_name.upper() or "FED" in next_event_name.upper() or "RATE" in next_event_name.upper()

        if is_fomc and minutes_to_high_impact <= 5:
            # Cautious Mode
            score = 60.0
            direction = act
            decision = "CONDITIONAL_PASS"
            reasons.append(f"FOMC CAUTIOUS MODE: High-Impact Event '{next_event_name}' in {minutes_to_high_impact} mins. Half lot size (0.5x), max allowed spread $1.20.")
            t_end = time.time()
            end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return AgentDecisionOutput(
                agent_name=self.name,
                direction=direction,
                score=score,
                decision=decision,
                reasoning_summary=f"Macro Score: {score:.1f}/100. " + "; ".join(reasons),
                operational_criticality=self.criticality,
                health_status=AgentHealthStatus.HEALTHY,
                execution_started_at=start_iso,
                execution_completed_at=end_iso,
                execution_latency_ms=round((t_end - t_start) * 1000, 2),
                data_source=data_source,
                confidence=0.60,
                decision_id=signal.id,
                metrics={
                    "minutes_to_high_impact": minutes_to_high_impact,
                    "minutes_since_last_event": minutes_since_last_event,
                    "next_event_name": next_event_name,
                    "usd_sentiment": usd_sentiment,
                    "fomc_mode": True,
                    "max_lot_multiplier": 0.5,
                    "max_allowed_spread": 1.20
                }
            )
        elif in_pre_news_block:
            score = 10.0
            reasons.append(f"HIGH RISK: Upcoming High-Impact Event ({next_event_name}) in {minutes_to_high_impact} mins (Pre-News Lockout <= {settings.NEWS_PRE_BLOCK_MINUTES}m)")
            decision = "VETO"
        elif in_post_news_cooldown:
            score = 30.0
            reasons.append(f"VOLATILITY COOLDOWN: Recent High-Impact Event ({next_event_name}) was {minutes_since_last_event} mins ago (Post-News Cooldown <= {settings.NEWS_POST_COOLDOWN_MINUTES}m)")
            decision = "FAIL"
        else:
            reasons.append("Economic Calendar Clear (No Tier-1 CPI/NFP/FOMC news lockout)")
            
            # Gold vs USD Macro Flow
            if act == "BUY":
                if usd_sentiment == "BEARISH_USD":
                    score += 10.0
                    direction = "BUY"
                    reasons.append("Macro USD weakness supports Gold Bullish expansion")
                elif usd_sentiment == "BULLISH_USD":
                    score -= 15.0
                    reasons.append("Macro USD strength creates headwinds for Gold Buy")
                else:
                    direction = "BUY"
            elif act == "SELL":
                if usd_sentiment == "BULLISH_USD":
                    score += 10.0
                    direction = "SELL"
                    reasons.append("Macro USD strength supports Gold Bearish liquidation")
                elif usd_sentiment == "BEARISH_USD":
                    score -= 15.0
                    reasons.append("Macro USD weakness opposes Gold Short")
                else:
                    direction = "SELL"
                    
            score = max(0.0, min(100.0, score))
            decision = "PASS" if score >= 65.0 else ("FAIL" if score < 45.0 else "NEUTRAL")

        summary = f"Macro Score: {score:.1f}/100. " + "; ".join(reasons)
        t_end = time.time()
        end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        return AgentDecisionOutput(
            agent_name=self.name,
            direction=direction,
            score=score,
            decision=decision,
            reasoning_summary=summary,
            operational_criticality=self.criticality,
            health_status=AgentHealthStatus.HEALTHY,
            execution_started_at=start_iso,
            execution_completed_at=end_iso,
            execution_latency_ms=round((t_end - t_start) * 1000, 2),
            data_source=data_source,
            confidence=round(score / 100.0, 2),
            decision_id=signal.id,
            metrics={
                "minutes_to_high_impact": minutes_to_high_impact,
                "minutes_since_last_event": minutes_since_last_event,
                "next_event_name": next_event_name,
                "usd_sentiment": usd_sentiment
            }
        )

fundamental_agent = FundamentalSentimentAgent()
