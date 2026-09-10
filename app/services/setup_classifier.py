from typing import Dict, Any, List, Optional

class SetupClassifier:
    """
    Classifies market conditions into discrete Institutional Setup Models:
    1. TREND_CONTINUATION (MTF trend alignment + pullback into Discount/Premium OB)
    2. LIQUIDITY_SWEEP_REVERSAL (Key swing sweep + immediate CHoCH + FVG retest)
    3. OB_REACTION (Clean touch and wick rejection off an unmitigated Order Block)
    4. FVG_RETRACEMENT (Displacement rebalance into a Fair Value Gap 50% midpoint)
    5. BREAKOUT_RETEST (Confirmed structure break followed by successful level retest)
    6. STRUCTURE_REVERSAL (CHoCH on intermediate timeframe indicating major regime shift)
    7. NO_VALID_SETUP (Chop, lack of displacement, equilibrium zone, or conflicting signals)
    """

    SETUP_TYPES = [
        "TREND_CONTINUATION",
        "LIQUIDITY_SWEEP_REVERSAL",
        "OB_REACTION",
        "FVG_RETRACEMENT",
        "BREAKOUT_RETEST",
        "STRUCTURE_REVERSAL",
        "NO_VALID_SETUP"
    ]

    @classmethod
    def classify_setup(
        cls,
        mtf_data: Dict[str, Any],
        smc_data: Dict[str, Any],
        current_price: float,
        session_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Evaluates MTF indicators and SMC structures to determine the active setup model.
        """
        trend = smc_data.get("trend", "NEUTRAL")
        structure = smc_data.get("structure", "RANGE")
        latest_event = smc_data.get("latest_event", "NONE")
        obs = smc_data.get("unmitigated_obs", [])
        fvgs = smc_data.get("unmitigated_fvgs", [])
        sweeps = smc_data.get("recent_sweeps", [])
        dealing_range = smc_data.get("dealing_range", {})
        zone = dealing_range.get("zone", "EQUILIBRIUM")

        direction = "FLAT"
        setup_type = "NO_VALID_SETUP"
        reasons = []
        confidence = 0.0

        # 1. Check LIQUIDITY_SWEEP_REVERSAL (Highest priority institutional entry)
        if sweeps:
            recent_sweep = sweeps[-1]
            if recent_sweep["type"] == "BULLISH_LIQUIDITY_SWEEP" and zone in ("DISCOUNT", "DEEP_DISCOUNT"):
                setup_type = "LIQUIDITY_SWEEP_REVERSAL"
                direction = "BUY"
                confidence = 88.0
                reasons.append(recent_sweep["description"])
                reasons.append(f"Favorable buying location in {zone} zone.")
            elif recent_sweep["type"] == "BEARISH_LIQUIDITY_SWEEP" and zone in ("PREMIUM", "EXTREME_PREMIUM"):
                setup_type = "LIQUIDITY_SWEEP_REVERSAL"
                direction = "SELL"
                confidence = 88.0
                reasons.append(recent_sweep["description"])
                reasons.append(f"Favorable selling location in {zone} zone.")

        # 2. Check OB_REACTION
        if setup_type == "NO_VALID_SETUP" and obs:
            for ob in obs:
                ob_high = ob["high"]
                ob_low = ob["low"]
                ob_type = ob["type"]

                if ob_type == "BULLISH_ORDER_BLOCK" and (ob_low <= current_price <= ob_high * 1.002):
                    setup_type = "OB_REACTION"
                    direction = "BUY"
                    confidence = 82.0
                    reasons.append(f"Tapping Bullish Order Block at ${ob_low:.2f}-${ob_high:.2f} (Displacement: ${ob.get('displacement', 0):.2f})")
                    break
                elif ob_type == "BEARISH_ORDER_BLOCK" and (ob_low * 0.998 <= current_price <= ob_high):
                    setup_type = "OB_REACTION"
                    direction = "SELL"
                    confidence = 82.0
                    reasons.append(f"Tapping Bearish Order Block at ${ob_low:.2f}-${ob_high:.2f} (Displacement: ${ob.get('displacement', 0):.2f})")
                    break

        # 3. Check FVG_RETRACEMENT
        if setup_type == "NO_VALID_SETUP" and fvgs:
            for fvg in fvgs:
                top = fvg["top"]
                bottom = fvg["bottom"]
                fvg_type = fvg["type"]

                if fvg_type == "BULLISH_FVG" and bottom <= current_price <= top and zone in ("DISCOUNT", "DEEP_DISCOUNT", "EQUILIBRIUM"):
                    setup_type = "FVG_RETRACEMENT"
                    direction = "BUY"
                    confidence = 78.0
                    reasons.append(f"Retracing into Bullish Fair Value Gap [${bottom:.2f} - ${top:.2f}] (Fill: {fvg.get('fill_pct', 0)}%)")
                    break
                elif fvg_type == "BEARISH_FVG" and bottom <= current_price <= top and zone in ("PREMIUM", "EXTREME_PREMIUM", "EQUILIBRIUM"):
                    setup_type = "FVG_RETRACEMENT"
                    direction = "SELL"
                    confidence = 78.0
                    reasons.append(f"Retracing into Bearish Fair Value Gap [${bottom:.2f} - ${top:.2f}] (Fill: {fvg.get('fill_pct', 0)}%)")
                    break

        # 4. Check STRUCTURE_REVERSAL (CHoCH)
        if setup_type == "NO_VALID_SETUP" and "CHOCH" in latest_event:
            if latest_event == "BULLISH_CHOCH" and zone in ("DISCOUNT", "DEEP_DISCOUNT"):
                setup_type = "STRUCTURE_REVERSAL"
                direction = "BUY"
                confidence = 80.0
                reasons.append("Bullish Change of Character (CHOCH) confirmed on swing structure.")
            elif latest_event == "BEARISH_CHOCH" and zone in ("PREMIUM", "EXTREME_PREMIUM"):
                setup_type = "STRUCTURE_REVERSAL"
                direction = "SELL"
                confidence = 80.0
                reasons.append("Bearish Change of Character (CHOCH) confirmed on swing structure.")

        # 5. Check TREND_CONTINUATION (BOS + Trend)
        if setup_type == "NO_VALID_SETUP":
            if trend == "BULLISH" and structure == "BULLISH_TREND" and zone in ("DISCOUNT", "EQUILIBRIUM"):
                setup_type = "TREND_CONTINUATION"
                direction = "BUY"
                confidence = 75.0
                reasons.append("Bullish Trend Continuation (Higher Highs & Higher Lows) in discount/equilibrium.")
            elif trend == "BEARISH" and structure == "BEARISH_TREND" and zone in ("PREMIUM", "EQUILIBRIUM"):
                setup_type = "TREND_CONTINUATION"
                direction = "SELL"
                confidence = 75.0
                reasons.append("Bearish Trend Continuation (Lower Highs & Lower Lows) in premium/equilibrium.")

        if setup_type == "NO_VALID_SETUP":
            reasons.append("Market is consolidating or lacking high-probability institutional displacement.")
            confidence = 35.0

        return {
            "setup_type": setup_type,
            "direction": direction,
            "confidence": round(confidence, 1),
            "reasons": reasons,
            "is_actionable": setup_type != "NO_VALID_SETUP" and confidence >= 70.0
        }

setup_classifier = SetupClassifier()
