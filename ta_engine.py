class TAEngine:
    def _ema(self, values, period):
        if not values or len(values) < period:
            return values[-1] if values else 0
        k = 2 / (period + 1)
        ema = values[-1]
        for v in reversed(values[:-1]):
            ema = v * k + ema * (1 - k)
        return ema

    def _atr(self, candles, period=14):
        trs = []
        for i in range(1, min(period + 1, len(candles))):
            h, l = float(candles[i][2]), float(candles[i][3])
            pc = float(candles[i + 1][4]) if i + 1 < len(candles) else l
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return sum(trs) / len(trs) if trs else 0

    def _rsi(self, closes, period=14):
        if len(closes) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(1, period + 1):
            diff = closes[i - 1] - closes[i]
            if diff > 0:
                gains.append(diff); losses.append(0)
            else:
                gains.append(0); losses.append(abs(diff))
        avg_gain, avg_loss = sum(gains) / period, sum(losses) / period
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 1)

    def _macd(self, closes):
        if len(closes) < 26: return 0, 0, 0
        macd_line = self._ema(closes[:12], 12) - self._ema(closes[:26], 26)
        signal = macd_line * 0.9
        return round(macd_line, 6), round(signal, 6), round(macd_line - signal, 6)

    def _volume_analysis(self, candles, period=20):
        if len(candles) < period:
            return {"vol_ratio": 1.0, "vol_spike": False}
        volumes = [float(x[5]) for x in candles[:period]]
        avg_vol = sum(volumes) / len(volumes)
        vol_ratio = volumes[0] / avg_vol if avg_vol > 0 else 1.0
        return {
            "vol_ratio": round(vol_ratio, 2),
            "vol_spike": vol_ratio > 1.8
        }

    def _levels(self, candles, lookback=50):
        if len(candles) < 10:
            return {"support": 0, "resistance": 0, "support_ladder": []}

        n = min(lookback, len(candles))
        highs = [float(x[2]) for x in candles[:n]]
        lows = [float(x[3]) for x in candles[:n]]
        closes = [float(x[4]) for x in candles[:n]]
        current = closes[0]

        pivot_highs, pivot_lows = [], []
        for i in range(2, n - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1] and highs[i] > highs[i-2] and highs[i] > highs[i+2]:
                pivot_highs.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i+1] and lows[i] < lows[i-2] and lows[i] < lows[i+2]:
                pivot_lows.append(lows[i])

        valid_supports = sorted([l for l in pivot_lows if l < current], reverse=True)
        support_ladder = valid_supports[:3] if valid_supports else [min(lows)]
        
        return {
            "support": round(support_ladder[0], 6),
            "support_ladder": [round(s, 6) for s in support_ladder],
            "resistance": round(min([h for h in pivot_highs if h > current], default=max(highs)), 6)
        }

    def analyze_all(self, buf):
        # Базовые таймфреймы теперь 1 час и 4 часа
        if not buf or "1h" not in buf or "4h" not in buf:
            return None
        c_1h, c_4h = buf["1h"], buf["4h"]
        if len(c_1h) < 26 or len(c_4h) < 2:
            return None

        last = float(c_1h[0][4])
        trend_4h = "bullish" if float(c_4h[1][4]) > float(c_4h[1][1]) else "bearish"
        closes = [float(x[4]) for x in c_1h]
        
        ema20 = self._ema(closes[:20], 20)
        atr = self._atr(c_1h, 14) or (last * 0.01)
        rsi = self._rsi(closes, 14)
        vol = self._volume_analysis(c_1h, 20)
        levels = self._levels(c_1h, 50)

        struct = "ranging"
        if last > ema20 and trend_4h == "bullish":
            struct = "uptrend"
        elif last < ema20 and trend_4h == "bearish":
            struct = "downtrend"

        return {
            "last_price": last,
            "atr": atr,
            "structure": struct,
            "ema_20": ema20,
            "rsi": rsi,
            "vol_spike": vol["vol_spike"],
            "support": levels["support"],
            "support_ladder": levels["support_ladder"],
            "resistance": levels["resistance"],
        }
