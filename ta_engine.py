class TAEngine:

    def _ema(self, values, period):
        if not values or len(values) < 2:
            return values[0] if values else 0
        k = 2 / (period + 1)
        ema = values[-1]
        for v in reversed(values[:-1]):
            ema = v * k + ema * (1 - k)
        return ema

    def _atr(self, candles, period=14):
        trs = []
        for i in range(1, min(period + 1, len(candles))):
            h  = float(candles[i][2])
            l  = float(candles[i][3])
            pc = float(candles[i + 1][4]) if i + 1 < len(candles) else l
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return sum(trs) / len(trs) if trs else 0

    def _rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(1, period + 1):
            diff = closes[i - 1] - closes[i]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        ag = sum(gains) / period
        al = sum(losses) / period
        if al == 0:
            return 100
        return round(100 - 100 / (1 + ag / al), 1)

    def _levels(self, candles, lookback=50):
        n = min(lookback, len(candles))
        if n < 6:
            return {"support": 0, "resistance": 0,
                    "near_support": False, "near_resistance": False,
                    "dist_to_res_pct": 999, "dist_to_sup_pct": 999}
        highs  = [float(x[2]) for x in candles[:n]]
        lows   = [float(x[3]) for x in candles[:n]]
        closes = [float(x[4]) for x in candles[:n]]
        current = closes[0]

        pivot_h, pivot_l = [], []
        for i in range(2, n - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                pivot_h.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                pivot_l.append(lows[i])

        resistance = min((h for h in pivot_h if h > current), default=max(highs))
        support    = max((l for l in pivot_l if l < current), default=min(lows))

        atr = self._atr(candles, 14) or current * 0.001
        return {
            "support":          round(support, 6),
            "resistance":       round(resistance, 6),
            "near_support":     abs(current - support) < atr * 1.5,
            "near_resistance":  abs(current - resistance) < atr * 1.5,
            "dist_to_res_pct":  round((resistance - current) / current * 100, 2),
            "dist_to_sup_pct":  round((current - support) / current * 100, 2),
        }

    def _volume_signal(self, buf):
        last_vol = buf.get("last_vol", 0)
        avg_vol  = buf.get("avg_vol", 1)
        ratio    = last_vol / avg_vol if avg_vol > 0 else 1.0
        return round(ratio, 2)

    def _trend_4h(self, candles_4h):
        if not candles_4h or len(candles_4h) < 5:
            return "ranging"
        closes  = [float(x[4]) for x in candles_4h[:30]]
        ema20   = self._ema(closes[:20], 20)
        current = closes[0]
        higher  = closes[0] > closes[1] > closes[2]
        lower   = closes[0] < closes[1] < closes[2]
        if current > ema20 and higher:
            return "uptrend"
        elif current < ema20 and lower:
            return "downtrend"
        return "ranging"

    def _breakout(self, candles_30m, levels):
        if len(candles_30m) < 3:
            return {"breakout": False, "direction": "none"}
        current = float(candles_30m[0][4])
        prev    = float(candles_30m[1][4])
        res     = levels["resistance"]
        sup     = levels["support"]
        if current > res > prev > 0:
            return {"breakout": True, "direction": "up", "level": res}
        if current < sup < prev and sup > 0:
            return {"breakout": True, "direction": "down", "level": sup}
        return {"breakout": False, "direction": "none"}

    def analyze_all(self, buf):
        if not buf or "30m" not in buf or "4h" not in buf:
            return None
        c_30m = buf["30m"]
        c_4h  = buf["4h"]
        if len(c_30m) < 26 or len(c_4h) < 5:
            return None

        last = buf.get("last_price", float(c_30m[0][4]))
        imb  = buf.get("imbalance", 1.0)

        closes_30m = [float(x[4]) for x in c_30m]

        atr       = self._atr(c_30m, 14) or last * 0.001
        ema20     = self._ema(closes_30m[:20], 20)
        ema50     = self._ema(closes_30m[:50], 50) if len(closes_30m) >= 50 else ema20
        rsi       = self._rsi(closes_30m, 14)
        trend_4h  = self._trend_4h(c_4h)
        levels    = self._levels(c_30m, 60)
        breakout  = self._breakout(c_30m, levels)
        vol_ratio = self._volume_signal(buf)

        delta     = closes_30m[0] - closes_30m[1] if len(closes_30m) > 1 else 0
        delta_pct = abs(delta) / last if last > 0 else 0

        rising_no_vol = (closes_30m[0] > closes_30m[1] and vol_ratio < 0.7)

        return {
            "last_price":      last,
            "atr":             round(atr, 8),
            "atr_pct":         round(atr / last * 100, 3),
            "ema20":           ema20,
            "ema50":           ema50,
            "rsi":             rsi,
            "trend_4h":        trend_4h,
            "imbalance":       imb,
            "vol_ratio":       vol_ratio,
            "vol_spike":       vol_ratio > 1.5,
            "rising_no_vol":   rising_no_vol,
            "support":         levels["support"],
            "resistance":      levels["resistance"],
            "near_support":    levels["near_support"],
            "near_resistance": levels["near_resistance"],
            "dist_to_res_pct": levels["dist_to_res_pct"],
            "dist_to_sup_pct": levels["dist_to_sup_pct"],
            "breakout":        breakout["breakout"],
            "breakout_dir":    breakout["direction"],
            "breakout_level":  breakout.get("level", 0),
            "delta_pct":       delta_pct,
        }
