from typing import Dict, Any
from app.config import settings
from app.database.models import SignalPayload, AgentDecisionOutput

class FundamentalSentimentAgent:
    name: str = "Fundamental & Sentiment Agent"
    weight: float = 0.15

    def evaluate(self, signal: SignalPayload, macro_data: Dict[str, Any]) -> AgentDecisionOutput:
        act = signal.action.upper()
        minutes_to_high_impact = macro_data.get("minutes_to_next_high_impact_news", 999)
        minutes_since_last_event = macro_data.get("minutes_since_last_event", 999)
        next_event_name = macro_data.get("next_event_name", "None")
        usd_sentiment = macro_data.get("usd_sentiment", "NEUTRAL") # BULLISH_USD, BEARISH_USD, NEUTRAL
        
        reasons = []
        score = 85.0
        direction = "NEUTRAL"
        
        # 1. High-Impact News Window Clearance Check
        in_pre_news_block = minutes_to_high_impact <= settings.NEWS_PRE_BLOCK_MINUTES
        in_post_news_cooldown = minutes_since_last_event <= settings.NEWS_POST_COOLDOWN_MINUTES
        
        if in_pre_news_block:
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
            decision = "PASS" if score >= 80.0 else ("FAIL" if score < 60.0 else "NEUTRAL")

        summary = f"Macro Score: {score:.1f}/100. " + "; ".join(reasons)
        
        return AgentDecisionOutput(
            agent_name=self.name,
            direction=direction,
            score=score,
            decision=decision,
            reasoning_summary=summary,
            metrics={
                "minutes_to_high_impact": minutes_to_high_impact,
                "minutes_since_last_event": minutes_since_last_event,
                "next_event_name": next_event_name,
                "usd_sentiment": usd_sentiment
            }
        )

fundamental_agent = FundamentalSentimentAgent()
