from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from app.engine.smart_money_engine import smart_money_engine
from app.engine.multi_timeframe_engine import multi_timeframe_engine
from app.engine.technical_indicators import technical_indicators
from app.services.session_engine import session_engine
from app.services.setup_classifier import setup_classifier
from app.services.trade_quality_scorer import trade_quality_scorer
from app.services.entry_safety_policy import directional_location_block_reason
from app.config import trading_config
import settings_manager

class PreTradeIntelligenceEngine:
    """
    Unified Real-Time Pre-Trade Intelligence & Chart Scanner Engine.
    Combines MTF sync, Smart Money Analysis, Session timing, Indicator confirmation,
    Setup classification, and Trade Quality scoring into a single unified telemetry scan.
    """

    def scan_market(
        self,
        symbol: str,
        live_tick: Dict[str, Any],
        timeframe_candles: Dict[str, List[Dict[str, Any]]],
        news_events: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Executes complete pre-trade analysis for a symbol.
        Returns exhaustive diagnostics, setup classification, score, and trade decision.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # 1. Broker Live Data Validation (Fail closed if missing)
        bid = float(live_tick.get("bid", 0.0))
        ask = float(live_tick.get("ask", 0.0))
        spread_pips = float(live_tick.get("spread", 0.0))

        if bid <= 0.0 or ask <= 0.0:
            return {
                "symbol": symbol,
                "timestamp": timestamp,
                "status": "FAIL_CLOSED_NO_MARKET_DATA",
                "trade_allowed": False,
                "reason": "Invalid or missing live broker price feed."
            }

        # 2. Broker candle validation (hard fail-closed; never synthesize indicators)
        required_timeframes = ("M5", "M15", "H1", "H4", "D1")
        missing_timeframes = [tf for tf in required_timeframes if len(timeframe_candles.get(tf, [])) < 30]
        if missing_timeframes:
            return {
                "symbol": symbol,
                "timestamp": timestamp,
                "status": "FAIL_CLOSED_BROKER_CANDLES",
                "trade_allowed": False,
                "decision_reason": "BROKER_CANDLES_UNAVAILABLE: " + ",".join(missing_timeframes),
                "reason": "Broker-authoritative candle history is missing or insufficient.",
                "missing_timeframes": missing_timeframes,
            }

        # 3. Multi-Timeframe Analysis
        mtf_result = multi_timeframe_engine.evaluate_multi_timeframe(timeframe_candles)

        # 3. M15 / Execution Structure Analysis
        m15_candles = timeframe_candles.get("M15") or timeframe_candles.get("15m", [])
        if not m15_candles and timeframe_candles:
            # Fallback to first available timeframe
            m15_candles = next(iter(timeframe_candles.values()))

        smc_result = smart_money_engine.analyze_market_structure(m15_candles, timeframe="M15")

        # 4. Session Engine
        session_info = session_engine.get_current_session_info()
        session_levels = session_engine.calculate_session_levels(m15_candles)

        # 5. Technical Indicators
        closes = [float(c["close"]) for c in m15_candles] if m15_candles else [bid]
        rsi = technical_indicators.calculate_rsi(closes, 14)
        atr = technical_indicators.calculate_atr(m15_candles, 14) if m15_candles else 1.5
        adx_info = technical_indicators.calculate_adx(m15_candles, 14) if m15_candles else {"adx": 20.0}
        indicators = {
            "rsi": rsi,
            "atr": atr,
            "adx": adx_info
        }

        # 6. Setup Classification
        current_price = (bid + ask) / 2.0
        setup = setup_classifier.classify_setup(
            mtf_data=mtf_result,
            smc_data=smc_result,
            current_price=current_price,
            session_info=session_info
        )

        # 7. Trade Quality Scoring (0-100)
        quality_score = trade_quality_scorer.score_trade_setup(
            setup=setup,
            mtf_data=mtf_result,
            smc_data=smc_result,
            indicators=indicators,
            live_spread_pips=spread_pips,
            target_rr_ratio=2.0,
            quality_threshold=settings_manager.get_min_confidence_threshold()
        )

        # 8. High-Impact News Check
        active_news_blackout = False
        news_reason = None
        if news_events:
            for event in news_events:
                if event.get("impact") in ("HIGH", "CRITICAL") and event.get("is_blackout", False):
                    active_news_blackout = True
                    news_reason = f"High-impact news blackout active: {event.get('title')}"
                    break

        # 9. Phase 6 candidate regime gates (fail closed)
        trade_allowed = False
        decision_reason = ""

        adx_raw = indicators.get("adx", {})
        adx_value = float(adx_raw.get("adx", 0.0)) if isinstance(adx_raw, dict) else float(adx_raw or 0.0)
        adx_minimum = float(trading_config.get("REGIME_ADX_MINIMUM"))
        structure = str(smc_result.get("structure", "RANGE")).upper()
        setup_type = str(setup.get("setup_type", "NO_VALID_SETUP")).upper()
        regime = str(setup.get("regime", "TRANSITION")).upper()
        allowed_direction = str(setup.get("allowed_direction", "BOTH")).upper()
        setup_direction = str(setup.get("direction", "FLAT")).upper()
        consolidation_detected = (structure in ("RANGE", "CONSOLIDATION", "CONSOLIDATING") and setup_type not in ("STRUCTURE_REVERSAL",)) or setup_type == "NO_VALID_SETUP"
        disallow_consolidation = bool(trading_config.get("DISALLOW_CONSOLIDATION_ENTRIES"))
        location_block_reason = directional_location_block_reason(setup_direction, smc_result)

        if regime == "NO_TRADE":
            trade_allowed = False
            decision_reason = "NO_TRADE_REGIME_CONFLICT: higher-timeframe direction is conflicted."
        elif allowed_direction not in ("BOTH", setup_direction) and setup_direction in ("BUY", "SELL"):
            trade_allowed = False
            decision_reason = f"NO_TRADE_DIRECTION_CONFLICT: regime={regime} permits {allowed_direction}, setup requested {setup_direction}."
        elif adx_value < adx_minimum:
            trade_allowed = False
            decision_reason = f"NO_TRADE_REGIME_ADX: ADX {adx_value:.1f} is below required minimum {adx_minimum:.1f}."
        elif disallow_consolidation and consolidation_detected:
            trade_allowed = False
            decision_reason = f"NO_TRADE_CONSOLIDATION: structure={structure}, setup={setup_type}."
        elif location_block_reason:
            trade_allowed = False
            decision_reason = location_block_reason
        elif active_news_blackout:
            trade_allowed = False
            decision_reason = news_reason or "High-impact news blackout active."
        elif not setup.get("is_actionable", False):
            trade_allowed = False
            decision_reason = f"No actionable setup model detected ({setup.get('setup_type')})."
        elif not quality_score.get("passed", False):
            trade_allowed = False
            decision_reason = f"Quality score {quality_score.get('score')}/100 is below minimum threshold {quality_score.get('threshold')}."
        elif spread_pips > 5.0 and "XAU" in symbol:
            trade_allowed = False
            decision_reason = f"Gold spread of {spread_pips:.1f} pips exceeds max tolerance (5.0 pips)."
        elif spread_pips > 2.0 and "EUR" in symbol:
            trade_allowed = False
            decision_reason = f"EURUSD spread of {spread_pips:.1f} pips exceeds max tolerance (2.0 pips)."
        else:
            trade_allowed = True
            decision_reason = f"High-probability {setup.get('direction')} setup verified with Quality Score {quality_score.get('score')}/100."

        return {
            "symbol": symbol,
            "timestamp": timestamp,
            "current_price": round(current_price, 3),
            "bid": round(bid, 3),
            "ask": round(ask, 3),
            "spread_pips": round(spread_pips, 2),
            "trade_allowed": trade_allowed,
            "decision_reason": decision_reason,
            "setup": setup,
            "quality_score": quality_score,
            "session": {**session_info, **session_levels},
            "smc": smc_result,
            "mtf": mtf_result,
            "indicators": indicators,
            "news_blackout": active_news_blackout
        }

pretrade_intelligence_engine = PreTradeIntelligenceEngine()
