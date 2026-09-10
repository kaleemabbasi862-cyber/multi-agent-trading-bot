from typing import Dict, Any, List

class TradeQualityScorer:
    """
    Transparent 0-100 Trade Quality Scoring Engine.
    Evaluates setups across 6 objective quantitative dimensions:
    1. Higher Timeframe Trend Alignment (20 pts)
    2. Market Structure & BOS/CHoCH Quality (15 pts)
    3. SMC Liquidity & Order Flow Confluence (20 pts)
    4. Dealing Range / Premium-Discount Location (15 pts)
    5. Indicator & Momentum Confirmation (15 pts)
    6. Risk-to-Reward & Spread Efficiency (15 pts)
    
    Default Action Threshold: >= 75 / 100
    """

    DEFAULT_THRESHOLD = 75.0

    @classmethod
    def score_trade_setup(
        cls,
        setup: Dict[str, Any],
        mtf_data: Dict[str, Any],
        smc_data: Dict[str, Any],
        indicators: Dict[str, Any],
        live_spread_pips: float,
        target_rr_ratio: float = 2.0
    ) -> Dict[str, Any]:
        """
        Calculates itemized 0-100 score and returns full explanation.
        """
        breakdown = {}
        total_score = 0.0
        direction = setup.get("direction", "FLAT")

        # 1. Higher Timeframe Alignment (20 pts max)
        consensus_trend = mtf_data.get("consensus_trend", "NEUTRAL")
        mtf_score = 0.0
        if (direction == "BUY" and consensus_trend == "BULLISH") or (direction == "SELL" and consensus_trend == "BEARISH"):
            mtf_score = 20.0
        elif consensus_trend == "NO_TRADE_CONFLICT" or consensus_trend == "NEUTRAL":
            mtf_score = 8.0
        else: # Counter-trend
            mtf_score = 4.0
        breakdown["mtf_alignment"] = {"score": mtf_score, "max": 20.0, "details": f"Macro bias is {consensus_trend}"}
        total_score += mtf_score

        # 2. Market Structure & BOS/CHoCH Quality (15 pts max)
        structure = smc_data.get("structure", "RANGE")
        latest_event = smc_data.get("latest_event", "NONE")
        struct_score = 0.0
        if direction == "BUY":
            if structure == "BULLISH_TREND" or "BULLISH" in latest_event:
                struct_score = 15.0
            elif structure == "RANGE":
                struct_score = 8.0
            else:
                struct_score = 3.0
        elif direction == "SELL":
            if structure == "BEARISH_TREND" or "BEARISH" in latest_event:
                struct_score = 15.0
            elif structure == "RANGE":
                struct_score = 8.0
            else:
                struct_score = 3.0
        breakdown["market_structure"] = {"score": struct_score, "max": 15.0, "details": f"Structure is {structure}, Event: {latest_event}"}
        total_score += struct_score

        # 3. SMC Confluence (OB + FVG + Liquidity Sweeps) (20 pts max)
        setup_type = setup.get("setup_type", "NO_VALID_SETUP")
        smc_score = 0.0
        if setup_type == "LIQUIDITY_SWEEP_REVERSAL":
            smc_score = 20.0
        elif setup_type == "OB_REACTION":
            smc_score = 18.0
        elif setup_type == "FVG_RETRACEMENT":
            smc_score = 16.0
        elif setup_type == "STRUCTURE_REVERSAL":
            smc_score = 15.0
        elif setup_type == "TREND_CONTINUATION":
            smc_score = 14.0
        else:
            smc_score = 0.0
        breakdown["smc_confluence"] = {"score": smc_score, "max": 20.0, "details": f"Setup model: {setup_type}"}
        total_score += smc_score

        # 4. Dealing Range / Premium-Discount Location (15 pts max)
        pd_range = smc_data.get("dealing_range", {})
        zone = pd_range.get("zone", "EQUILIBRIUM")
        loc_pct = pd_range.get("location_pct", 50.0)
        pd_score = 0.0

        if direction == "BUY":
            if zone == "DEEP_DISCOUNT":
                pd_score = 15.0
            elif zone == "DISCOUNT":
                pd_score = 12.0
            elif zone == "EQUILIBRIUM":
                pd_score = 7.0
            else:
                pd_score = 2.0 # Buying in Premium
        elif direction == "SELL":
            if zone == "EXTREME_PREMIUM":
                pd_score = 15.0
            elif zone == "PREMIUM":
                pd_score = 12.0
            elif zone == "EQUILIBRIUM":
                pd_score = 7.0
            else:
                pd_score = 2.0 # Selling in Discount
        breakdown["dealing_range"] = {"score": pd_score, "max": 15.0, "details": f"Price at {loc_pct:.1f}% ({zone})"}
        total_score += pd_score

        # 5. Indicators & Momentum Confirmation (15 pts max)
        rsi = indicators.get("rsi", 50.0)
        adx_info = indicators.get("adx", {})
        adx_val = adx_info.get("adx", 20.0) if isinstance(adx_info, dict) else 20.0
        ind_score = 0.0

        if direction == "BUY":
            if 40.0 <= rsi <= 65.0: # Healthy momentum
                ind_score += 8.0
            elif rsi < 35.0: # Oversold bounce
                ind_score += 6.0
            else:
                ind_score += 3.0
        elif direction == "SELL":
            if 35.0 <= rsi <= 60.0:
                ind_score += 8.0
            elif rsi > 65.0: # Overbought rejection
                ind_score += 6.0
            else:
                ind_score += 3.0

        if adx_val >= 25.0:
            ind_score += 7.0
        elif adx_val >= 18.0:
            ind_score += 4.0
        else:
            ind_score += 2.0

        breakdown["momentum_indicators"] = {"score": round(ind_score, 1), "max": 15.0, "details": f"RSI: {rsi:.1f}, ADX: {adx_val:.1f}"}
        total_score += ind_score

        # 6. Risk-to-Reward & Spread Efficiency (15 pts max)
        rr_score = 0.0
        if target_rr_ratio >= 2.5:
            rr_score += 10.0
        elif target_rr_ratio >= 1.8:
            rr_score += 8.0
        elif target_rr_ratio >= 1.5:
            rr_score += 5.0
        else:
            rr_score += 2.0

        # Spread penalty
        if live_spread_pips <= 1.5:
            rr_score += 5.0
        elif live_spread_pips <= 3.0:
            rr_score += 3.0
        elif live_spread_pips <= 5.0:
            rr_score += 1.0
        else:
            rr_score += 0.0

        breakdown["risk_reward_spread"] = {"score": round(rr_score, 1), "max": 15.0, "details": f"R:R: {target_rr_ratio:.2f}, Spread: {live_spread_pips:.1f} pips"}
        total_score += rr_score

        final_score = round(min(100.0, max(0.0, total_score)), 1)
        passed = final_score >= cls.DEFAULT_THRESHOLD and direction in ("BUY", "SELL")

        return {
            "score": final_score,
            "threshold": cls.DEFAULT_THRESHOLD,
            "passed": passed,
            "verdict": "TRADE_APPROVED" if passed else "NO_TRADE_QUALITY_BELOW_THRESHOLD",
            "breakdown": breakdown
        }

trade_quality_scorer = TradeQualityScorer()
