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
    weight: float = 4 / 17
    criticality: str = AgentOperationalCriticality.DECISION_CRITICAL

    def _classify_regime(self, rsi, ema_20, ema_50, ema_200, support, resistance, entry_price):
        range_span = abs(resistance - support)
        ema_spread = abs(ema_20 - ema_50)
        if ema_20 > ema_50 > ema_200 and rsi >= 55.0:
            return "STRONG_UPTREND", range_span, ema_spread
        elif ema_20 > ema_50 and rsi >= 50.0:
            return "WEAK_UPTREND", range_span, ema_spread
        elif ema_20 < ema_50 < ema_200 and rsi <= 45.0:
            return "STRONG_DOWNTREND", range_span, ema_spread
        elif ema_20 < ema_50 and rsi <= 50.0:
            return "WEAK_DOWNTREND", range_span, ema_spread
        elif range_span < 5.0 and abs(entry_price - ema_50) < 1.5:
            return "RANGE", range_span, ema_spread
        elif range_span > 25.0:
            return "HIGH_VOLATILITY", range_span, ema_spread
        else:
            return "BREAKOUT", range_span, ema_spread

    def evaluate(self, signal: SignalPayload, market_data: Dict[str, Any]) -> AgentDecisionOutput:
        t_start = time.time()
        start_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        p = float(signal.entry_price or 0.0)
        act = signal.action.upper()
        ind = market_data.get("indicators", {}) if market_data else {}
        
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

        required = (
            "rsi", "ema_20", "ema_50", "ema_200",
            "ema_20_1h", "ema_50_1h", "trend_1h", "support", "resistance",
        )
        source = str(market_data.get("source") or "").upper()
        candle_source = str(market_data.get("candle_source") or "").upper()
        missing = [key for key in required if ind.get(key) is None]
        quote_time = market_data.get("updated_at")
        try:
            quote_age = time.time() - float(quote_time)
        except (TypeError, ValueError):
            quote_age = None
        if quote_age is not None and quote_age > float(trading_config.get("MAX_DATA_AGE_SECONDS")):
            end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return AgentDecisionOutput(
                agent_name=self.name, direction="NEUTRAL", score=0.0, decision="FAIL",
                reasoning_summary=f"STALE_DATA: broker data age {quote_age:.2f}s.",
                operational_criticality=self.criticality,
                health_status=AgentHealthStatus.STALE_DATA,
                execution_started_at=start_iso, execution_completed_at=end_iso,
                execution_latency_ms=round((time.time() - t_start) * 1000, 2),
                data_age_seconds=round(quote_age, 2), data_source=source or "UNVERIFIED",
                confidence=0.0, stale=True, fallback_used=False,
            )
        if source != "CTRADER_CBOT" or candle_source != "CTRADER_CBOT" or missing:
            end_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return AgentDecisionOutput(
                agent_name=self.name,
                direction="NEUTRAL",
                score=0.0,
                decision="FAIL",
                reasoning_summary=f"UNVERIFIED_BROKER_INDICATORS: missing={missing}",
                operational_criticality=self.criticality,
                health_status=AgentHealthStatus.INVALID_INPUT,
                execution_started_at=start_iso,
                execution_completed_at=end_iso,
                execution_latency_ms=round((time.time() - t_start) * 1000, 2),
                data_source="UNVERIFIED",
                confidence=0.0,
                error="Broker tick and broker candles are required.",
                fallback_used=False,
            )

        rsi_15m = float(ind["rsi"])
        ema_20_15m = float(ind["ema_20"])
        ema_50_15m = float(ind["ema_50"])
        ema_200_15m = float(ind["ema_200"])
        ema_20_1h = float(ind["ema_20_1h"])
        ema_50_1h = float(ind["ema_50_1h"])
        trend_1h = str(ind["trend_1h"]).upper()
        support = float(ind["support"])
        resistance = float(ind["resistance"])
        
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
            if p >= ema_20_15m >= ema_50_15m:
                score += 10.0
                reasons.append("15m Price above EMA20 and EMA50 (Strong Bullish Stack)")
            elif p < ema_50_15m:
                score -= 15.0
                reasons.append("15m Price below EMA50")
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
            if p <= ema_20_15m <= ema_50_15m:
                score += 10.0
                reasons.append("15m Price below EMA20 and EMA50 (Strong Bearish Stack)")
            elif p > ema_50_15m:
                score -= 15.0
                reasons.append("15m Price above EMA50")
            if 32.0 <= rsi_15m <= 55.0:
                score += 5.0
                reasons.append(f"RSI 14 in optimal bearish expansion zone ({rsi_15m:.1f})")
            elif rsi_15m < 25.0:
                score -= 20.0
                reasons.append(f"RSI 14 Oversold ({rsi_15m:.1f}) - Reversal risk")
            elif rsi_15m > 65.0:
                score -= 15.0
                reasons.append(f"RSI 14 Strong Bullish Momentum ({rsi_15m:.1f})")

        regime, range_span, ema_spread = self._classify_regime(
            rsi_15m, ema_20_15m, ema_50_15m, ema_200_15m, support, resistance, p
        )

        if regime in ("STRONG_UPTREND", "WEAK_UPTREND"):
            if act == "BUY":
                score += 10.0
                reasons.append(f"Regime {regime} supports directional alignment")
            else:
                score -= 20.0
                reasons.append(f"Regime {regime} conflicts with counter-trend short")
        elif regime in ("STRONG_DOWNTREND", "WEAK_DOWNTREND"):
            if act == "SELL":
                score += 10.0
                reasons.append(f"Regime {regime} supports directional alignment")
            else:
                score -= 20.0
                reasons.append(f"Regime {regime} conflicts with counter-trend long")
        elif regime == "RANGE":
            score -= 15.0
            reasons.append(f"Regime RANGE: choppy consolidation, low trend-follow win rate")
        elif regime == "HIGH_VOLATILITY":
            score -= 5.0
            reasons.append(f"Regime HIGH_VOLATILITY: wide swings, strict SL enforcement required")
        elif regime == "BREAKOUT":
            score += 5.0
            reasons.append(f"Regime BREAKOUT: structural momentum confirmed")

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
            data_source="CTRADER_CBOT_M15_H1_CANDLES",
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
                "resistance": resistance,
                "regime": regime,
                "range_span": round(range_span, 2),
                "ema_spread": round(ema_spread, 2)
            }
        )


technical_agent = TechnicalAnalystAgent()
