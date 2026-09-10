import math
from typing import List, Dict, Any, Optional

class SmartMoneyEngine:
    """
    Objective Quantitative Smart Money Concepts (SMC) & Price Action Engine.
    Detects Market Structure (HH, HL, LH, LL), BOS vs CHoCH, Liquidity Sweeps,
    Order Blocks (with mitigation tracking), Fair Value Gaps (FVG fill tracking),
    and Premium/Discount Dealing Ranges.
    """

    @staticmethod
    def detect_swing_points(candles: List[Dict[str, Any]], lookback: int = 3) -> Dict[str, Any]:
        """
        Detects fractal swing highs and swing lows to classify Higher Highs (HH),
        Higher Lows (HL), Lower Highs (LH), Lower Lows (LL).
        """
        if len(candles) < (lookback * 2) + 1:
            return {"swing_highs": [], "swing_lows": [], "structure": "UNCLEAR"}

        swing_highs = []
        swing_lows = []

        for i in range(lookback, len(candles) - lookback):
            current_h = float(candles[i]["high"])
            current_l = float(candles[i]["low"])

            # Swing High
            is_sh = all(current_h >= float(candles[i - j]["high"]) and current_h >= float(candles[i + j]["high"]) for j in range(1, lookback + 1))
            if is_sh:
                swing_highs.append({
                    "index": i,
                    "price": round(current_h, 3),
                    "timestamp": candles[i].get("timestamp"),
                    "type": "SWING_HIGH"
                })

            # Swing Low
            is_sl = all(current_l <= float(candles[i - j]["low"]) and current_l <= float(candles[i + j]["low"]) for j in range(1, lookback + 1))
            if is_sl:
                swing_lows.append({
                    "index": i,
                    "price": round(current_l, 3),
                    "timestamp": candles[i].get("timestamp"),
                    "type": "SWING_LOW"
                })

        # Market Structure Sequence Labeling
        labeled_sh = []
        for idx, sh in enumerate(swing_highs):
            label = "SH"
            if idx > 0:
                if sh["price"] > swing_highs[idx - 1]["price"]:
                    label = "HH" # Higher High
                elif sh["price"] < swing_highs[idx - 1]["price"]:
                    label = "LH" # Lower High
            labeled_sh.append({**sh, "label": label})

        labeled_sl = []
        for idx, sl in enumerate(swing_lows):
            label = "SL"
            if idx > 0:
                if sl["price"] > swing_lows[idx - 1]["price"]:
                    label = "HL" # Higher Low
                elif sl["price"] < swing_lows[idx - 1]["price"]:
                    label = "LL" # Lower Low
            labeled_sl.append({**sl, "label": label})

        structure = "RANGE"
        if len(labeled_sh) >= 2 and len(labeled_sl) >= 2:
            last_sh = labeled_sh[-1]["label"]
            last_sl = labeled_sl[-1]["label"]
            if last_sh == "HH" and last_sl == "HL":
                structure = "BULLISH_TREND"
            elif last_sh == "LH" and last_sl == "LL":
                structure = "BEARISH_TREND"
            elif last_sh == "HH" and last_sl == "LL":
                structure = "EXPANDING_VOLATILITY"
            elif last_sh == "LH" and last_sl == "HL":
                structure = "COMPRESSION_TRIANGLE"

        return {
            "swing_highs": labeled_sh,
            "swing_lows": labeled_sl,
            "structure": structure,
            "last_swing_high": labeled_sh[-1] if labeled_sh else None,
            "last_swing_low": labeled_sl[-1] if labeled_sl else None
        }

    @staticmethod
    def detect_bos_choch(candles: List[Dict[str, Any]], lookback: int = 3) -> Dict[str, Any]:
        """
        Detects Break of Structure (BOS) vs Change of Character (CHOCH).
        - BOS: Continuation break in the direction of the dominant trend.
        - CHOCH: Reversal break against the prior structure (e.g. break below last HL in uptrend).
        """
        if len(candles) < 15:
            return {"events": [], "trend": "UNCLEAR", "latest_event": "NONE"}

        swings = SmartMoneyEngine.detect_swing_points(candles, lookback=lookback)
        swing_highs = swings["swing_highs"]
        swing_lows = swings["swing_lows"]

        events = []
        current_trend = "NEUTRAL"

        # Walk through candles after first 2 swings
        if swing_highs and swing_lows:
            for i in range(10, len(candles)):
                c = candles[i]
                c_close = float(c["close"])
                c_high = float(c["high"])
                c_low = float(c["low"])
                c_time = c.get("timestamp")

                # Look at previous swing highs and lows before candle i
                valid_sh = [s for s in swing_highs if s["index"] < i]
                valid_sl = [s for s in swing_lows if s["index"] < i]

                if not valid_sh or not valid_sl:
                    continue

                recent_sh = valid_sh[-1]
                recent_sl = valid_sl[-1]

                # Bullish Breakout
                if c_close > recent_sh["price"]:
                    # If prior trend was Bearish or Neutral, this is a CHOCH (reversal)
                    if current_trend in ("BEARISH", "NEUTRAL"):
                        event_type = "BULLISH_CHOCH"
                        current_trend = "BULLISH"
                    else:
                        event_type = "BULLISH_BOS"

                    # Avoid duplicate logging if already triggered on same swing
                    if not events or events[-1].get("broken_level") != recent_sh["price"]:
                        events.append({
                            "type": event_type,
                            "index": i,
                            "timestamp": c_time,
                            "price": round(c_close, 3),
                            "broken_level": recent_sh["price"],
                            "broken_swing_label": recent_sh.get("label", "SH"),
                            "significance": "HIGH" if event_type == "BULLISH_CHOCH" else "MEDIUM"
                        })

                # Bearish Breakdown
                elif c_close < recent_sl["price"]:
                    if current_trend in ("BULLISH", "NEUTRAL"):
                        event_type = "BEARISH_CHOCH"
                        current_trend = "BEARISH"
                    else:
                        event_type = "BEARISH_BOS"

                    if not events or events[-1].get("broken_level") != recent_sl["price"]:
                        events.append({
                            "type": event_type,
                            "index": i,
                            "timestamp": c_time,
                            "price": round(c_close, 3),
                            "broken_level": recent_sl["price"],
                            "broken_swing_label": recent_sl.get("label", "SL"),
                            "significance": "HIGH" if event_type == "BEARISH_CHOCH" else "MEDIUM"
                        })

        latest_event = events[-1]["type"] if events else "NONE"
        latest_obj = events[-1] if events else None

        return {
            "events": events[-10:],
            "latest_event": latest_event,
            "latest_details": latest_obj,
            "trend": current_trend if current_trend != "NEUTRAL" else swings["structure"]
        }

    @staticmethod
    def detect_liquidity_sweeps(candles: List[Dict[str, Any]], lookback: int = 5) -> List[Dict[str, Any]]:
        """
        Detects Liquidity Sweeps (Stop Hunts / Judas Swings):
        Price pokes beyond swing high/low (taking stops) then aggressively rejects and closes inside.
        """
        if len(candles) < lookback + 1:
            return []

        sweeps = []

        for i in range(lookback, len(candles)):
            c = candles[i]
            c_high, c_low = float(c["high"]), float(c["low"])
            c_open, c_close = float(c["open"]), float(c["close"])

            prev_highs = [float(candles[j]["high"]) for j in range(i - lookback, i)]
            prev_lows = [float(candles[j]["low"]) for j in range(i - lookback, i)]

            max_prev_h = max(prev_highs)
            min_prev_l = min(prev_lows)

            # Bullish Sweep (Sell-side liquidity sweep): Pokes below previous low but closes firmly above it
            if c_low < min_prev_l and c_close > min_prev_l and c_close > c_open:
                sweep_depth = min_prev_l - c_low
                sweeps.append({
                    "type": "BULLISH_LIQUIDITY_SWEEP",
                    "index": i,
                    "timestamp": c.get("timestamp"),
                    "swept_level": round(min_prev_l, 3),
                    "wick_extreme": round(c_low, 3),
                    "close": round(c_close, 3),
                    "sweep_depth": round(sweep_depth, 3),
                    "strength": 90,
                    "description": f"Swept sell-side liquidity at ${min_prev_l:.2f} with strong bullish rejection."
                })

            # Bearish Sweep (Buy-side liquidity sweep): Pokes above previous high but closes firmly below it
            elif c_high > max_prev_h and c_close < max_prev_h and c_close < c_open:
                sweep_depth = c_high - max_prev_h
                sweeps.append({
                    "type": "BEARISH_LIQUIDITY_SWEEP",
                    "index": i,
                    "timestamp": c.get("timestamp"),
                    "swept_level": round(max_prev_h, 3),
                    "wick_extreme": round(c_high, 3),
                    "close": round(c_close, 3),
                    "sweep_depth": round(sweep_depth, 3),
                    "strength": 90,
                    "description": f"Swept buy-side liquidity at ${max_prev_h:.2f} with strong bearish rejection."
                })

        return sweeps

    @staticmethod
    def detect_order_blocks(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Detects institutional Order Blocks (OB) with Mitigation status tracking:
        - Bullish OB: Last down-close candle before a strong upward displacement.
        - Bearish OB: Last up-close candle before a strong downward displacement.
        - Tracks status: UNMITIGATED (fresh), TESTED (tapped), MITIGATED (filled/invalidated).
        """
        if len(candles) < 2:
            return []

        order_blocks = []
        for i in range(len(candles) - 1):
            c_curr = candles[i]
            c_next1 = candles[i + 1]

            curr_open, curr_close = float(c_curr["open"]), float(c_curr["close"])
            curr_high, curr_low = float(c_curr["high"]), float(c_curr["low"])

            next1_open, next1_close = float(c_next1["open"]), float(c_next1["close"])

            # Bullish OB: Down candle followed by aggressive bullish expansion
            if curr_close < curr_open and next1_close > curr_high:
                displacement = round(next1_close - curr_open, 3)
                # Check mitigation in subsequent candles
                tested_count = 0
                is_mitigated = False
                for j in range(i + 2, len(candles)):
                    cj_low = float(candles[j]["low"])
                    if cj_low <= curr_high:
                        tested_count += 1
                        if cj_low < curr_low: # Violated OB
                            is_mitigated = True
                            break

                status = "MITIGATED" if is_mitigated else ("TESTED" if tested_count > 0 else "UNMITIGATED")
                order_blocks.append({
                    "type": "BULLISH_ORDER_BLOCK",
                    "index": i,
                    "timestamp": c_curr.get("timestamp"),
                    "high": round(curr_high, 3),
                    "low": round(curr_low, 3),
                    "open": round(curr_open, 3),
                    "displacement": displacement,
                    "status": status,
                    "tested_count": tested_count,
                    "strength": 90 if status == "UNMITIGATED" else (70 if status == "TESTED" else 30)
                })

            # Bearish OB: Up candle followed by aggressive bearish expansion
            elif curr_close > curr_open and next1_close < curr_low:
                displacement = round(curr_open - next1_close, 3)
                tested_count = 0
                is_mitigated = False
                for j in range(i + 2, len(candles)):
                    cj_high = float(candles[j]["high"])
                    if cj_high >= curr_low:
                        tested_count += 1
                        if cj_high > curr_high: # Violated OB
                            is_mitigated = True
                            break

                status = "MITIGATED" if is_mitigated else ("TESTED" if tested_count > 0 else "UNMITIGATED")
                order_blocks.append({
                    "type": "BEARISH_ORDER_BLOCK",
                    "index": i,
                    "timestamp": c_curr.get("timestamp"),
                    "high": round(curr_high, 3),
                    "low": round(curr_low, 3),
                    "open": round(curr_open, 3),
                    "displacement": displacement,
                    "status": status,
                    "tested_count": tested_count,
                    "strength": 90 if status == "UNMITIGATED" else (70 if status == "TESTED" else 30)
                })

        return order_blocks


    @staticmethod
    def detect_fair_value_gaps(candles: List[Dict[str, Any]], min_gap_pips: float = 0.5) -> List[Dict[str, Any]]:
        """
        Detects 3-candle Fair Value Gaps (FVG) and tracks fill percentage:
        - Bullish FVG: Low of candle 3 > High of candle 1.
        - Bearish FVG: High of candle 3 < Low of candle 1.
        """
        if len(candles) < 3:
            return []

        fvgs = []
        for i in range(2, len(candles)):
            c1 = candles[i - 2]
            c2 = candles[i - 1]
            c3 = candles[i]

            c1_high = float(c1["high"])
            c1_low = float(c1["low"])
            c3_high = float(c3["high"])
            c3_low = float(c3["low"])

            # Bullish FVG
            if c3_low > c1_high:
                gap_size = c3_low - c1_high
                if gap_size >= min_gap_pips:
                    # Calculate fill percentage from future candles
                    min_future_low = min((float(candles[j]["low"]) for j in range(i + 1, len(candles))), default=c3_low)
                    if min_future_low <= c1_high:
                        fill_pct = 100.0
                        status = "FULLY_FILLED"
                    elif min_future_low < c3_low:
                        fill_pct = round(((c3_low - min_future_low) / gap_size) * 100.0, 1)
                        status = "PARTIALLY_FILLED"
                    else:
                        fill_pct = 0.0
                        status = "UNMITIGATED"

                    fvgs.append({
                        "type": "BULLISH_FVG",
                        "index": i - 1,
                        "timestamp": c2.get("timestamp"),
                        "top": round(c3_low, 3),
                        "bottom": round(c1_high, 3),
                        "midpoint": round((c3_low + c1_high) / 2.0, 3), # 50% equilibrium of FVG
                        "gap_size": round(gap_size, 3),
                        "fill_pct": fill_pct,
                        "status": status,
                        "strength": 85 if status == "UNMITIGATED" else (60 if status == "PARTIALLY_FILLED" else 20)
                    })

            # Bearish FVG
            elif c3_high < c1_low:
                gap_size = c1_low - c3_high
                if gap_size >= min_gap_pips:
                    max_future_high = max((float(candles[j]["high"]) for j in range(i + 1, len(candles))), default=c3_high)
                    if max_future_high >= c1_low:
                        fill_pct = 100.0
                        status = "FULLY_FILLED"
                    elif max_future_high > c3_high:
                        fill_pct = round(((max_future_high - c3_high) / gap_size) * 100.0, 1)
                        status = "PARTIALLY_FILLED"
                    else:
                        fill_pct = 0.0
                        status = "UNMITIGATED"

                    fvgs.append({
                        "type": "BEARISH_FVG",
                        "index": i - 1,
                        "timestamp": c2.get("timestamp"),
                        "top": round(c1_low, 3),
                        "bottom": round(c3_high, 3),
                        "midpoint": round((c1_low + c3_high) / 2.0, 3),
                        "gap_size": round(gap_size, 3),
                        "fill_pct": fill_pct,
                        "status": status,
                        "strength": 85 if status == "UNMITIGATED" else (60 if status == "PARTIALLY_FILLED" else 20)
                    })

        return fvgs

    @staticmethod
    def calculate_premium_discount(candles: List[Dict[str, Any]], period: int = 50) -> Dict[str, Any]:
        """
        Calculates Dealing Range (0% to 100%) and categorizes price into:
        - Deep Discount (<25%)
        - Discount (25% - 45%)
        - Equilibrium (45% - 55%)
        - Premium (55% - 75%)
        - Extreme Premium (>75%)
        """
        if not candles:
            return {"range_high": 0.0, "range_low": 0.0, "equilibrium": 0.0, "zone": "EQUILIBRIUM", "location_pct": 50.0}

        window = candles[-period:] if len(candles) >= period else candles
        high = max(float(c["high"]) for c in window)
        low = min(float(c["low"]) for c in window)
        current = float(window[-1]["close"])

        rng = high - low
        eq = low + (rng * 0.5)

        location_pct = ((current - low) / (rng + 1e-6)) * 100.0

        if location_pct < 25.0:
            zone = "DEEP_DISCOUNT"
        elif location_pct < 45.0:
            zone = "DISCOUNT"
        elif location_pct <= 55.0:
            zone = "EQUILIBRIUM"
        elif location_pct <= 75.0:
            zone = "PREMIUM"
        else:
            zone = "EXTREME_PREMIUM"

        return {
            "range_high": round(high, 3),
            "range_low": round(low, 3),
            "equilibrium": round(eq, 3),
            "current_price": round(current, 3),
            "location_pct": round(location_pct, 1),
            "zone": zone,
            "is_buy_favorable": zone in ("DISCOUNT", "DEEP_DISCOUNT"),
            "is_sell_favorable": zone in ("PREMIUM", "EXTREME_PREMIUM")
        }

    @classmethod
    def analyze_market_structure(cls, candles: List[Dict[str, Any]], timeframe: str = "M15") -> Dict[str, Any]:
        """
        Unified multi-dimensional SMC Analysis.
        Returns full structure summary, OBs, FVGs, Sweeps, and Dealing Range.
        """
        if not candles or len(candles) < 5:
            return {
                "timeframe": timeframe,
                "trend": "UNCLEAR",
                "structure": "UNCLEAR",
                "dealing_range": {"zone": "EQUILIBRIUM", "location_pct": 50.0},
                "unmitigated_obs": [],
                "unmitigated_fvgs": [],
                "recent_sweeps": [],
                "latest_event": "NONE"
            }

        swings = cls.detect_swing_points(candles)
        bos_choch = cls.detect_bos_choch(candles)
        sweeps = cls.detect_liquidity_sweeps(candles)
        obs = cls.detect_order_blocks(candles)
        fvgs = cls.detect_fair_value_gaps(candles)
        pd_range = cls.calculate_premium_discount(candles)

        unmitigated_obs = [ob for ob in obs if ob["status"] in ("UNMITIGATED", "TESTED")]
        unmitigated_fvgs = [fvg for fvg in fvgs if fvg["status"] in ("UNMITIGATED", "PARTIALLY_FILLED")]

        return {
            "timeframe": timeframe,
            "trend": bos_choch["trend"],
            "structure": swings["structure"],
            "dealing_range": pd_range,
            "unmitigated_obs": unmitigated_obs[-3:],
            "unmitigated_fvgs": unmitigated_fvgs[-3:],
            "recent_sweeps": sweeps[-3:],
            "latest_event": bos_choch["latest_event"],
            "latest_event_details": bos_choch.get("latest_details"),
            "last_swing_high": swings.get("last_swing_high"),
            "last_swing_low": swings.get("last_swing_low")
        }


smart_money_engine = SmartMoneyEngine()
