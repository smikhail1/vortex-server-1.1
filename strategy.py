import time

class SwingStrategy:
    def __init__(self):
        self.cooldowns = {}
        self.loss_streak = {}

    def set_cooldown(self, symbol, hours=4):
        self.cooldowns[symbol] = time.time() + hours * 3600

    def is_cooling_down(self, symbol):
        return time.time() < self.cooldowns.get(symbol, 0)

    def add_loss(self, symbol):
        self.loss_streak[symbol] = self.loss_streak.get(symbol, 0) + 1

    def reset_streak(self, symbol):
        self.loss_streak[symbol] = 0

    def get_streak(self, symbol):
        return self.loss_streak.get(symbol, 0)

    def _calc_tp_sl(self, data, side):
        price = data["last_price"]
        atr   = data["atr"]
        sup   = data["support"]
        res   = data["resistance"]

        # SL: ATR×2 за уровнем
        if side == "long":
            sl_level = sup if sup > 0 else price - atr * 2
            sl = min(sl_level - atr * 0.5, price - atr * 2)
            tp1 = price + atr * 3
            tp2 = res if res > tp1 else price + atr * 5
        else:
            sl_level = res if res > 0 else price + atr * 2
            sl = max(sl_level + atr * 0.5, price + atr * 2)
            tp1 = price - atr * 3
            tp2 = sup if sup > 0 and sup < tp1 else price - atr * 5

        return round(tp1, 6), round(tp2, 6), round(sl, 6)

    def analyze_futures(self, data, symbol, macro_filter="allow_all"):
        if self.is_cooling_down(symbol):
            cd_left = int((self.cooldowns[symbol] - time.time()) / 60)
            return {"signal": "neutral", "score": 0,
                    "args_text": f"⏳ Остывание {cd_left}м"}

        last = data.get("last_price", 0)
        if not last:
            return {"signal": "neutral", "score": 0, "args_text": "Нет цены"}

        # фильтр флэта
        if data.get("atr_pct", 0) < 0.3:
            return {"signal": "neutral", "score": 0, "args_text": "Sc:0 | Флэт"}

        score = 0
        args  = []
        side  = "neutral"

        trend_4h      = data.get("trend_4h", "ranging")
        rsi           = data.get("rsi", 50)
        vol_ratio     = data.get("vol_ratio", 1.0)
        vol_spike     = data.get("vol_spike", False)
        breakout      = data.get("breakout", False)
        breakout_dir  = data.get("breakout_dir", "none")
        near_support  = data.get("near_support", False)
        near_res      = data.get("near_resistance", False)
        rising_no_vol = data.get("rising_no_vol", False)
        imb           = data.get("imbalance", 1.0)
        dist_res      = data.get("dist_to_res_pct", 999)

        # после 3 стопов подряд — пауза 4ч
        if self.get_streak(symbol) >= 3:
            self.set_cooldown(symbol, hours=4)
            self.loss_streak[symbol] = 0
            return {"signal": "neutral", "score": 0,
                    "args_text": "🛑 Пауза после 3 стопов"}

        # ══════════ ЛОНГ ══════════
        # 1. Главный фильтр: тренд 4H вверх
        if trend_4h == "uptrend":
            score += 2
            args.append("4H ↑")
            side = "long"

        # 2. Пробой уровня вверх с объёмом — сильный сигнал
        if breakout and breakout_dir == "up":
            score += 3
            args.append("Пробой ↑")
            side = "long"

        # 3. RSI не перекуплен
        if side == "long":
            if rsi < 35:
                score += 2; args.append(f"RSI перепродан {rsi}")
            elif rsi < 60:
                score += 1; args.append(f"RSI {rsi}")
            elif rsi > 75:
                score -= 1  # перекуплен — снижаем score

        # 4. Объём подтверждает
        if vol_spike:
            score += 2; args.append(f"Объём ×{vol_ratio:.1f}")
        elif vol_ratio > 1.2:
            score += 1; args.append(f"Объём ×{vol_ratio:.1f}")

        # 5. Стакан
        if imb > 1.4:
            score += 1; args.append("Bid стенка")

        # 6. У поддержки — хорошая точка входа
        if near_support and side == "long":
            score += 1; args.append("У поддержки")

        # не входим если до сопротивления < 0.5%
        if side == "long" and dist_res < 0.5:
            return {"signal": "neutral", "score": score,
                    "args_text": f"Sc:{score} | Близко к сопр."}

        # ══════════ ШОРТ ══════════
        if trend_4h == "downtrend" and side == "neutral":
            score += 2; args.append("4H ↓"); side = "short"

        if breakout and breakout_dir == "down" and side == "neutral":
            score += 3; args.append("Пробой ↓"); side = "short"

        # рост без объёма — слабость = шорт
        if rising_no_vol and side == "neutral":
            score += 2; args.append("Рост без объёма ⚠️"); side = "short"

        if side == "short":
            if rsi > 70:
                score += 2; args.append(f"RSI перекуплен {rsi}")
            elif rsi > 55:
                score += 1; args.append(f"RSI {rsi}")
            if vol_spike:
                score += 1; args.append(f"Объём ×{vol_ratio:.1f}")
            if imb < 0.6:
                score += 1; args.append("Ask стенка")
            if near_res:
                score += 1; args.append("У сопротивления")

        # блокировки оракула
        if side == "long" and macro_filter == "block_longs":
            return {"signal": "neutral", "score": score,
                    "args_text": f"Sc:{score} | 🚫 Блок Long"}
        if side == "short" and macro_filter == "block_shorts":
            return {"signal": "neutral", "score": score,
                    "args_text": f"Sc:{score} | 🚫 Блок Short"}

        if score >= 4 and side != "neutral":
            tp1, tp2, sl = self._calc_tp_sl(data, side)
            return {
                "signal":      side,
                "score":       score,
                "take_profit": tp1,
                "take_profit2":tp2,
                "stop_loss":   sl,
                "leverage":    3,
                "args_text":   f"Sc:{score} | " + " + ".join(args[:4]),
            }

        return {"signal": "neutral", "score": score,
                "args_text": f"Sc:{score} | " + (" + ".join(args[:3]) if args else "Ожидание...")}

    def analyze_spot(self, data, symbol, macro_filter="allow_all"):
        last = data.get("last_price", 0)
        if not last:
            return {"signal": "neutral", "score": 0, "args_text": "Нет цены"}

        score = 0
        args  = []

        trend_4h     = data.get("trend_4h", "ranging")
        rsi          = data.get("rsi", 50)
        vol_ratio    = data.get("vol_ratio", 1.0)
        vol_spike    = data.get("vol_spike", False)
        breakout     = data.get("breakout", False)
        breakout_dir = data.get("breakout_dir", "none")
        near_support = data.get("near_support", False)
        imb          = data.get("imbalance", 1.0)
        support      = data.get("support", 0)
        resistance   = data.get("resistance", 0)
        atr          = data.get("atr", last * 0.001)

        if trend_4h == "uptrend":
            score += 2; args.append("4H ↑")

        if breakout and breakout_dir == "up":
            score += 3; args.append("Пробой ↑")

        if rsi < 35:
            score += 2; args.append(f"RSI перепродан {rsi}")
        elif rsi < 55:
            score += 1; args.append(f"RSI {rsi}")

        if vol_spike:
            score += 2; args.append(f"Объём ×{vol_ratio:.1f}")
        elif vol_ratio > 1.2:
            score += 1; args.append(f"Объём ×{vol_ratio:.1f}")

        if imb > 1.2:
            score += 1; args.append("Bid поддержка")

        if near_support:
            score += 1; args.append("У поддержки")

        if score >= 4:
            if macro_filter == "block_longs":
                return {"signal": "neutral", "score": score,
                        "args_text": f"Sc:{score} | 🚫 Блок Спот"}

            tp1 = last + atr * 4
            tp2 = resistance if resistance > tp1 else last + atr * 7
            sl  = support - atr * 0.5 if support > 0 else last - atr * 2

            # лесенка DCA: 20% сразу, +40% на -1%, +40% на -2%
            orders = [
                {"size_pct": 20, "price": last},
                {"size_pct": 40, "price": round(last * 0.99, 6)},
                {"size_pct": 40, "price": round(last * 0.98, 6)},
            ]
            return {
                "signal":       "long_dca",
                "score":        score,
                "orders":       orders,
                "take_profit":  round(tp1, 6),
                "take_profit2": round(tp2, 6),
                "stop_loss":    round(sl, 6),
                "args_text":    f"Sc:{score} | " + " + ".join(args[:4]),
            }

        return {"signal": "neutral", "score": score,
                "args_text": f"Sc:{score} | " + (" + ".join(args[:3]) if args else "Поиск...")}
