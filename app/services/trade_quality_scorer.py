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
        target_rr_ratio: float = 2.0,
        quality_threshold: float = None
    ) -> Dict[str, Any]:
        """
        Calculates itemized 0-100 score and returns full explanation.
        """
        breakdown = {}
        total_score = 0.0
        setup_direction = str(setup.get("direction", "FLAT")).upper()
        intraday_trend = str(mtf_data.get("intraday_trend", "NO_TRADE_CONFLICT")).upper()
        intraday_aligned = bool(mtf_data.get("intraday_aligned", False))
        is_strong_alignment = bool(mtf_data.get("is_strong_alignment", False))
        structure_hint = str(smc_data.get("structure", "RANGE")).upper()
        event_hint = str(smc_data.get("latest_event", "NONE")).upper()
        trend_hint = str(smc_data.get("trend", "NEUTRAL")).upper()

        if setup_direction in ("BUY", "SELL"):
            scoring_direction = setup_direction
        elif intraday_aligned and intraday_trend in ("BULLISH", "BEARISH"):
            scoring_direction = "BUY" if intraday_trend == "BULLISH" else "SELL"
        elif "BULLISH" in event_hint or structure_hint == "BULLISH_TREND" or trend_hint == "BULLISH":
            scoring_direction = "BUY"
        elif "BEARISH" in event_hint or structure_hint == "BEARISH_TREND" or trend_hint == "BEARISH":
            scoring_direction = "SELL"
        elif intraday_trend == "BULLISH":
            scoring_direction = "BUY"
        elif intraday_trend == "BEARISH":
            scoring_direction = "SELL"
        else:
            scoring_direction = "FLAT"

        # 1. Higher Timeframe & Intraday Alignment (20 pts max)
        consensus_trend = mtf_data.get("consensus_trend", "NEUTRAL")
        macro_opposition = int(mtf_data.get("macro_opposition_count", 0) or 0)
        confluence_score = float(mtf_data.get("confluence_score", 50.0))
        intraday_score = float(mtf_data.get("intraday_score", 50.0))
        mtf_score = 0.0

        if scoring_direction == "BUY":
            if consensus_trend == "BULLISH":
                mtf_score = 20.0
            elif intraday_aligned and intraday_trend == "BULLISH":
                base = 19.0 if is_strong_alignment else 16.0
                mtf_score = max(8.0, base - (2.5 * macro_opposition))
            elif intraday_trend == "BULLISH":
                mtf_score = max(6.0, 12.0 - (2.0 * macro_opposition))
            elif consensus_trend in ("NO_TRADE_CONFLICT", "NEUTRAL"):
                mtf_score = round(max(4.0, min(10.0, confluence_score * 0.15)), 1)
            else: # Counter-trend
                mtf_score = 3.0
        elif scoring_direction == "SELL":
            if consensus_trend == "BEARISH":
                mtf_score = 20.0
            elif intraday_aligned and intraday_trend == "BEARISH":
                base = 19.0 if is_strong_alignment else 16.0
                mtf_score = max(8.0, base - (2.5 * macro_opposition))
            elif intraday_trend == "BEARISH":
                mtf_score = max(6.0, 12.0 - (2.0 * macro_opposition))
            elif consensus_trend in ("NO_TRADE_CONFLICT", "NEUTRAL"):
                mtf_score = round(max(4.0, min(10.0, confluence_score * 0.15)), 1)
            else: # Counter-trend
                mtf_score = 3.0
        else:
            mtf_score = round(max(4.0, min(12.0, (confluence_score + intraday_score) / 2.0 * 0.15)), 1)

        breakdown["mtf_alignment"] = {"score": mtf_score, "max": 20.0, "details": f"Macro bias: {consensus_trend}, Intraday: {intraday_trend} (Opp: {macro_opposition})"}
        total_score += mtf_score

        # 2. Market Structure & BOS/CHoCH Quality (15 pts max)
        structure = smc_data.get("structure", "RANGE")
        latest_event = smc_data.get("latest_event", "NONE")
        struct_score = 0.0

        if scoring_direction == "BUY":
            if structure == "BULLISH_TREND" and "BULLISH" in latest_event:
                struct_score = 15.0
            elif structure == "BULLISH_TREND":
                struct_score = 13.0
            elif "BULLISH" in latest_event:
                struct_score = 12.0
            elif structure in ("RANGE", "CONSOLIDATION", "TRANSITION"):
                struct_score = 7.5
            else:
                struct_score = 3.0
        elif scoring_direction == "SELL":
            if structure == "BEARISH_TREND" and "BEARISH" in latest_event:
                struct_score = 15.0
            elif structure == "BEARISH_TREND":
                struct_score = 13.0
            elif "BEARISH" in latest_event:
                struct_score = 12.0
            elif structure in ("RANGE", "CONSOLIDATION", "TRANSITION"):
                struct_score = 7.5
            else:
                struct_score = 3.0
        else:
            struct_score = 6.0 if structure in ("RANGE", "CONSOLIDATION") else 4.0

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
        elif setup_type == "PROVISIONAL_INTRADAY_EXPANSION":
            smc_score = 11.0
        else:
            obs = smc_data.get("unmitigated_obs", [])
            fvgs = smc_data.get("unmitigated_fvgs", [])
            sweeps = smc_data.get("recent_sweeps", [])
            partial = 0.0
            if obs:
                partial += min(4.0, len(obs) * 2.0)
            if fvgs:
                partial += min(3.0, len(fvgs) * 1.5)
            if sweeps:
                partial += min(3.0, len(sweeps) * 1.5)
            smc_score = round(partial, 1)

        smc_direction = "BULLISH" if structure == "BULLISH_TREND" or "BULLISH" in latest_event else ("BEARISH" if structure == "BEARISH_TREND" or "BEARISH" in latest_event else "NEUTRAL")
        direction_conflict = (scoring_direction == "BUY" and smc_direction == "BEARISH") or (scoring_direction == "SELL" and smc_direction == "BULLISH")
        if direction_conflict:
            smc_score = min(smc_score, 6.0)

        breakdown["smc_confluence"] = {"score": smc_score, "max": 20.0, "details": f"Setup model: {setup_type}; SMC direction: {smc_direction}"}
        total_score += smc_score

        # 4. Dealing Range / Premium-Discount Location (15 pts max)
        pd_range = smc_data.get("dealing_range", {})
        zone = pd_range.get("zone", "EQUILIBRIUM")
        loc_pct = float(pd_range.get("location_pct", 50.0))
        pd_score = 0.0

        if scoring_direction == "BUY":
            if zone == "DEEP_DISCOUNT":
                base_pd = 15.0
            elif zone == "DISCOUNT":
                base_pd = 12.0
            elif zone == "EQUILIBRIUM":
                base_pd = 7.0
            else:
                base_pd = 2.0
            pd_score = round(max(1.0, min(15.0, base_pd + (50.0 - loc_pct) * 0.05)), 1)
        elif scoring_direction == "SELL":
            if zone == "EXTREME_PREMIUM":
                base_pd = 15.0
            elif zone == "PREMIUM":
                base_pd = 12.0
            elif zone == "EQUILIBRIUM":
                base_pd = 7.0
            else:
                base_pd = 2.0
            pd_score = round(max(1.0, min(15.0, base_pd + (loc_pct - 50.0) * 0.05)), 1)
        else:
            pd_score = round(max(2.0, min(10.0, 8.0 - abs(loc_pct - 50.0) * 0.1)), 1)

        breakdown["dealing_range"] = {"score": pd_score, "max": 15.0, "details": f"Price at {loc_pct:.1f}% ({zone})"}
        total_score += pd_score

        # 5. Indicators & Momentum Confirmation (15 pts max)
        rsi = float(indicators.get("rsi", 50.0))
        adx_info = indicators.get("adx", {})
        adx_val = float(adx_info.get("adx", 20.0) if isinstance(adx_info, dict) else adx_info or 20.0)

        if scoring_direction == "BUY":
            if 40.0 <= rsi <= 65.0:
                rsi_pts = 8.0
            elif rsi < 35.0:
                rsi_pts = 6.0
            elif 35.0 <= rsi < 40.0:
                rsi_pts = 7.0
            elif 65.0 < rsi <= 72.0:
                rsi_pts = 5.0
            else:
                rsi_pts = 2.5
        elif scoring_direction == "SELL":
            if 35.0 <= rsi <= 60.0:
                rsi_pts = 8.0
            elif rsi > 65.0:
                rsi_pts = 6.0
            elif 60.0 < rsi <= 65.0:
                rsi_pts = 7.0
            elif 28.0 <= rsi < 35.0:
                rsi_pts = 5.0
            else:
                rsi_pts = 2.5
        else:
            rsi_pts = round(max(2.0, min(7.0, 7.0 - abs(rsi - 50.0) * 0.1)), 1)

        if adx_val >= 25.0:
            adx_pts = 7.0
        elif adx_val >= 18.0:
            adx_pts = round(4.0 + (adx_val - 18.0) / 7.0 * 2.5, 1)
        else:
            adx_pts = round(max(1.0, (adx_val / 18.0) * 3.5), 1)

        ind_score = round(rsi_pts + adx_pts, 1)
        breakdown["momentum_indicators"] = {"score": ind_score, "max": 15.0, "details": f"RSI: {rsi:.1f}, ADX: {adx_val:.1f}"}
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

        if live_spread_pips <= 1.0:
            spread_score = 5.0
        elif live_spread_pips <= 2.0:
            spread_score = 4.0
        elif live_spread_pips <= 3.5:
            spread_score = 2.5
        elif live_spread_pips <= 5.0:
            spread_score = 1.0
        else:
            spread_score = 0.0

        rr_total = round(rr_score + spread_score, 1)
        breakdown["risk_reward_spread"] = {"score": rr_total, "max": 15.0, "details": f"R:R: {target_rr_ratio:.2f}, Spread: {live_spread_pips:.1f} pips"}
        total_score += rr_total

        final_score = round(min(100.0, max(0.0, total_score)), 1)
        effective_threshold = cls.DEFAULT_THRESHOLD if quality_threshold is None else max(60.0, min(90.0, float(quality_threshold)))
        passed = final_score >= effective_threshold and setup_direction in ("BUY", "SELL")

        return {
            "score": final_score,
            "candidate_direction": scoring_direction,
            "actionable_direction": setup_direction,
            "threshold": effective_threshold,
            "passed": passed,
            "verdict": "TRADE_APPROVED" if passed else "NO_TRADE_QUALITY_BELOW_THRESHOLD",
            "breakdown": breakdown
        }

trade_quality_scorer = TradeQualityScorer()
