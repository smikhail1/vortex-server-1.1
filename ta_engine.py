class TAEngine:
    def _ema(self, values, period):
        if not values:
            return 0.0
        if len(values) == 1:
            return float(values[0])

        k = 2 / (period + 1)
        ema = float(values[-1])

        for v in reversed(values[:-1]):
            ema = float(v) * k + ema * (1 - k)

        return ema

    def _atr(self, candles, period=14):
        trs = []
        max_i = min(period + 1, len(candles) - 1)

        for i in range(1, max_i):
            high = float(candles[i][2])
            low = float(candles[i][3])
            prev_close = float(candles[i + 1][4]) if i + 1 < len(candles) else low
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)

        return sum(trs) / len(trs) if trs else 0.0

    def _rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return 50.0

        gains = []
        losses = []

        for i in range(1, period + 1):
            diff = closes[i - 1] - closes[i]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0 and avg_gain == 0:
            return 50.0
        if avg_loss == 0:
            return 99.0
        if avg_gain == 0:
            return 1.0

        rs = avg_gain / avg_loss
        return round(100 - 100 / (1 + rs), 1)

    def _levels(self, candles, lookback=50):
        n = min(lookback, len(candles))
        if n < 6:
            return {
                "support": 0.0,
                "resistance": 0.0,
                "near_support": False,
                "near_resistance": False,
                "dist_to_res_pct": 999.0,
                "dist_to_sup_pct": 999.0
            }

        highs = [float(x[2]) for x in candles[:n]]
        lows = [float(x[3]) for x in candles[:n]]
        closes = [float(x[4]) for x in candles[:n]]
        current = closes[0]

        pivot_h = []
        pivot_l = []

        for i in range(2, n - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                pivot_h.append(highs[i])
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                pivot_l.append(lows[i])

        resistance = min((h for h in pivot_h if h > current), default=max(highs))
        support = max((l for l in pivot_l if l < current), default=min(lows))

        atr = self._atr(candles, 14) or current * 0.001

        return {
            "support": round(support, 8),
            "resistance": round(resistance, 8),
            "near_support": abs(current - support) < atr * 1.5,
            "near_resistance": abs(current - resistance) < atr * 1.5,
            "dist_to_res_pct": round((resistance - current) / current * 100, 2) if current > 0 else 999.0,
            "dist_to_sup_pct": round((current - support) / current * 100, 2) if current > 0 else 999.0,
        }

    def _volume_signal(self, buf):
        last_vol = float(buf.get("last_vol", 0.0))
        avg_vol = float(buf.get("avg_vol", 1.0))
        if avg_vol <= 0:
            return 1.0
        return round(last_vol / avg_vol, 2)

    def _trend_4h(self, candles_4h):
        if not candles_4h or len(candles_4h) < 6:
            return "ranging"

        closes = [float(x[4]) for x in candles_4h[:30]]
        current = closes[0]
        ema20 = self._ema(closes[:20], 20)

        higher = closes[0] > closes[1] > closes[2]
        lower = closes[0] < closes[1] < closes[2]

        if current > ema20 and higher:
            return "uptrend"
        if current < ema20 and lower:
            return "downtrend"
        return "ranging"

    def _trend_bias_30m(self, closes_30m):
        if len(closes_30m) < 20:
            return "neutral", 0.0, 0.0

        ema20 = self._ema(closes_30m[:20], 20)
        ema50 = self._ema(closes_30m[:50], 50) if len(closes_30m) >= 50 else ema20
        price = closes_30m[0]

        if price > ema20 > ema50:
            return "bull", ema20, ema50
        if price < ema20 < ema50:
            return "bear", ema20, ema50
        return "neutral", ema20, ema50

    def _breakout(self, candles_30m, levels):
        if len(candles_30m) < 3:
            return {"breakout": False, "direction": "none", "level": 0.0}

        current = float(candles_30m[0][4])
        prev = float(candles_30m[1][4])
        res = levels["resistance"]
        sup = levels["support"]

        if current > res > prev > 0:
            return {"breakout": True, "direction": "up", "level": res}
        if current < sup < prev and sup > 0:
            return {"breakout": True, "direction": "down", "level": sup}

        return {"breakout": False, "direction": "none", "level": 0.0}

    def _market_regime(self, atr_pct, trend_4h, trend_bias_30m):
        if atr_pct < 0.8:
            return "dead"
        if trend_4h == "ranging" and trend_bias_30m == "neutral":
            return "chop"
        if trend_4h == "uptrend" and trend_bias_30m == "bull":
            return "trend_up"
        if trend_4h == "downtrend" and trend_bias_30m == "bear":
            return "trend_down"
        return "mixed"

    def analyze_all(self, buf):
        if not buf or "30m" not in buf or "4h" not in buf:
            return None

        c_30m = buf["30m"]
        c_4h = buf["4h"]
        c_5m = buf.get("5m", [])

        if len(c_30m) < 26 or len(c_4h) < 5:
            return None

        last = float(buf.get("last_price", float(c_30m[0][4])))
        imb = float(buf.get("imbalance", 1.0))

        closes_30m = [float(x[4]) for x in c_30m]
        closes_5m = [float(x[4]) for x in c_5m] if c_5m else closes_30m

        atr = self._atr(c_30m, 14) or last * 0.001
        atr_pct = round((atr / last) * 100, 3) if last > 0 else 0.0

        trend_bias_30m, ema20, ema50 = self._trend_bias_30m(closes_30m)
        trend_4h = self._trend_4h(c_4h)

        rsi_main = self._rsi(closes_30m, 14)
        rsi_fast = self._rsi(closes_5m, 14)

        levels = self._levels(c_30m, 60)
        breakout = self._breakout(c_30m, levels)
        vol_ratio = self._volume_signal(buf)

        rising_no_vol = (closes_30m[0] > closes_30m[1] and vol_ratio < 0.7)
        market_regime = self._market_regime(atr_pct, trend_4h, trend_bias_30m)

        near_support = levels["near_support"]
        near_resistance = levels["near_resistance"]
        dist_to_sup_pct = levels["dist_to_sup_pct"]
        dist_to_res_pct = levels["dist_to_res_pct"]

        pullback_long_ready = (
            trend_4h == "uptrend"
            and trend_bias_30m == "bull"
            and (near_support or abs(last - ema20) <= atr * 1.0 or abs(last - ema50) <= atr * 1.2)
            and rsi_fast <= 52
            and not rising_no_vol
        )

        pullback_short_ready = (
            trend_4h == "downtrend"
            and trend_bias_30m == "bear"
            and (near_resistance or abs(last - ema20) <= atr * 1.0 or abs(last - ema50) <= atr * 1.2)
            and rsi_fast >= 48
            and not rising_no_vol
        )

        retest_long_ready = (
            trend_4h != "downtrend"
            and trend_bias_30m == "bull"
            and breakout["direction"] == "up"
            and vol_ratio >= 1.0
            and imb >= 1.0
        )

        retest_short_ready = (
            trend_4h != "uptrend"
            and trend_bias_30m == "bear"
            and breakout["direction"] == "down"
            and vol_ratio >= 1.0
            and imb <= 1.0
        )

        setup_zone = "none"
        if near_support:
            setup_zone = "support"
        elif near_resistance:
            setup_zone = "resistance"
        elif breakout["breakout"]:
            setup_zone = "breakout_level"

        return {
            "last_price": last,
            "atr": round(atr, 8),
            "atr_pct": atr_pct,
            "ema20": round(ema20, 8),
            "ema50": round(ema50, 8),
            "rsi": rsi_main,
            "rsi_fast": rsi_fast,
            "trend_4h": trend_4h,
            "trend_bias_30m": trend_bias_30m,
            "market_regime": market_regime,
            "imbalance": imb,
            "vol_ratio": vol_ratio,
            "vol_spike": vol_ratio > 1.5,
            "rising_no_vol": rising_no_vol,
            "support": levels["support"],
            "resistance": levels["resistance"],
            "near_support": near_support,
            "near_resistance": near_resistance,
            "dist_to_res_pct": dist_to_res_pct,
            "dist_to_sup_pct": dist_to_sup_pct,
            "breakout": breakout["breakout"],
            "breakout_dir": breakout["direction"],
            "breakout_level": breakout["level"],
            "pullback_long_ready": pullback_long_ready,
            "pullback_short_ready": pullback_short_ready,
            "retest_long_ready": retest_long_ready,
            "retest_short_ready": retest_short_ready,
            "setup_zone": setup_zone,
        }