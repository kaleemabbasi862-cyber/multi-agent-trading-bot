import time
import datetime
from typing import Dict, Any
from app.config import trading_config
from app.database.models import (
    SignalPayload,
    AgentDecisionOutput,
    AgentOperationalCriticality,
    AgentHealthStatus
)


class TechnicalAnalystAgent:
    name: str = "Technical Analyst Agent"
    weight: float = 0.20
    criticality: str = AgentOperationalCriticality.DECISION_CRITICAL

    def evaluate(self, signal: SignalPayload, market_data: Dict[str, Any]) -> AgentDecisionOutput:
        t_start = time.time()
        start_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        p = float(signal.entry_price or 0.0)
        act = signal.action.upper()
        ind = market_data.get("indicators", {}) if market_data else {}
        
        # Check input validity
        if p <= 0.0:
            end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return AgentDecisionOutput(
                agent_name=self.name,
                direction="NEUTRAL",
                score=0.0,
                decision="FAIL",
                reasoning_summary="INVALID_INPUT: Entry price non-positive.",
                operational_criticality=self.criticality,
                health_status=AgentHealthStatus.INVALID_INPUT,
                execution_started_at=start_iso,
                execution_completed_at=end_iso,
                execution_latency_ms=round((time.time() - t_start) * 1000, 2),
                data_source="cTrader Live Tick Feed",
                confidence=0.0,
                error="Non-positive entry price"
            )

        rsi_15m = float(ind.get("rsi", 50.0))
        ema_20_15m = float(ind.get("ema_20", p))
        ema_50_15m = float(ind.get("ema_50", p))
        ema_200_15m = float(ind.get("ema_200", p))
        ema_20_1h = float(ind.get("ema_20_1h", p))
        ema_50_1h = float(ind.get("ema_50_1h", p))
        trend_1h = ind.get("trend_1h", "BULLISH")
        support = float(ind.get("support", p - 8.0))
        resistance = float(ind.get("resistance", p + 8.0))
        
        quote_time = market_data.get("updated_at") or market_data.get("timestamp")
        data_age = None
        is_stale = False
        if quote_time:
            try:
                data_age = round(time.time() - float(quote_time), 2)
                if data_age > 10.0:
                    is_stale = True
            except Exception:
                pass

        reasons = []
        score = 70.0
        direction = "NEUTRAL"
        
        # 1. 1H Multi-Timeframe Alignment Check
        is_1h_bull = (trend_1h == "BULLISH" or ema_20_1h >= ema_50_1h)
        is_1h_bear = (trend_1h == "BEARISH" or ema_20_1h <= ema_50_1h)
        
        if act == "BUY":
            direction = "BUY"
            if is_1h_bull:
                score += 15.0
                reasons.append(f"1H Trend Aligned BULLISH (EMA20: ${ema_20_1h:.2f} >= EMA50: ${ema_50_1h:.2f})")
            else:
                score -= 35.0
                reasons.append(f"1H Trend MISALIGNED (1H is {trend_1h})")
                
            # 15m EMAs Check
            if p >= ema_20_15m >= ema_50_15m:
                score += 10.0
                reasons.append("15m Price above EMA20 and EMA50 (Strong Bullish Stack)")
            elif p < ema_50_15m:
                score -= 15.0
                reasons.append("15m Price below EMA50")
                
            # RSI Momentum Check
            if 45.0 <= rsi_15m <= 68.0:
                score += 5.0
                reasons.append(f"RSI 14 in optimal expansion zone ({rsi_15m:.1f})")
            elif rsi_15m > 75.0:
                score -= 20.0
                reasons.append(f"RSI 14 Overbought ({rsi_15m:.1f}) - Pullback risk")
            elif rsi_15m < 35.0:
                score -= 15.0
                reasons.append(f"RSI 14 Weak Bearish Momentum ({rsi_15m:.1f})")
                
        elif act == "SELL":
            direction = "SELL"
            if is_1h_bear:
                score += 15.0
                reasons.append(f"1H Trend Aligned BEARISH (EMA20: ${ema_20_1h:.2f} <= EMA50: ${ema_50_1h:.2f})")
            else:
                score -= 35.0
                reasons.append(f"1H Trend MISALIGNED (1H is {trend_1h})")
                
            # 15m EMAs Check
            if p <= ema_20_15m <= ema_50_15m:
                score += 10.0
                reasons.append("15m Price below EMA20 and EMA50 (Strong Bearish Stack)")
            elif p > ema_50_15m:
                score -= 15.0
                reasons.append("15m Price above EMA50")
                
            # RSI Momentum Check
            if 32.0 <= rsi_15m <= 55.0:
                score += 5.0
                reasons.append(f"RSI 14 in optimal bearish expansion zone ({rsi_15m:.1f})")
            elif rsi_15m < 25.0:
                score -= 20.0
                reasons.append(f"RSI 14 Oversold ({rsi_15m:.1f}) - Reversal risk")
            elif rsi_15m > 65.0:
                score -= 15.0
                reasons.append(f"RSI 14 Strong Bullish Momentum ({rsi_15m:.1f})")

        if is_stale:
            score = 0.0
            decision = "FAIL"
            reasons.insert(0, f"STALE_DATA: Market quote age {data_age}s exceeds freshness limit ({trading_config.get('MAX_DATA_AGE_SECONDS')}s)")

        score = max(0.0, min(100.0, score))
        if not is_stale:
            decision = "PASS" if score >= 65.0 else ("FAIL" if score < 45.0 else "NEUTRAL")
        
        summary = (
            f"Technical Score: {score:.1f}/100. "
            + "; ".join(reasons)
            + f" | S/R Bounds: [${support:.2f} - ${resistance:.2f}]"
        )
        
        t_end = time.time()
        end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        return AgentDecisionOutput(
            agent_name=self.name,
            direction=direction,
            score=score,
            decision=decision,
            reasoning_summary=summary,
            operational_criticality=self.criticality,
            health_status=AgentHealthStatus.STALE_DATA if is_stale else AgentHealthStatus.HEALTHY,
            execution_started_at=start_iso,
            execution_completed_at=end_iso,
            execution_latency_ms=round((t_end - t_start) * 1000, 2),
            data_age_seconds=data_age,
            data_source="cTrader / Yahoo Multi-Timeframe M15/H1 Candles",
            confidence=round(score / 100.0, 2),
            stale=is_stale,
            decision_id=signal.id,
            metrics={
                "rsi_15m": rsi_15m,
                "ema_20_15m": ema_20_15m,
                "ema_50_15m": ema_50_15m,
                "ema_200_15m": ema_200_15m,
                "ema_20_1h": ema_20_1h,
                "ema_50_1h": ema_50_1h,
                "trend_1h": trend_1h,
                "support": support,
                "resistance": resistance
            }
        )


technical_agent = TechnicalAnalystAgent()
