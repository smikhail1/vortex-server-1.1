import time

class SwingStrategy:
    def __init__(self):
        self.cooldowns = {}

    def set_cooldown(self, symbol):
        self.cooldowns[symbol] = time.time()

    def is_cooling_down(self, symbol):
        # Остывание 4 часа после сделки
        return time.time() - self.cooldowns.get(symbol, 0) < 14400

    def analyze_futures(self, data, symbol, macro_filter="allow_all"):
        if self.is_cooling_down(symbol):
            return {"signal": "neutral"}

        last = data.get("last_price", 0)
        struct = data.get("structure", "ranging")
        rsi = data.get("rsi", 50)
        vol_spike = data.get("vol_spike", False)
        atr = data.get("atr", 0)

        # Лонг при пробое или сильном тренде с объемами (Плечо 3х)
        if struct == "uptrend" and vol_spike and rsi < 70 and macro_filter != "block_longs":
            return {
                "signal": "long",
                "leverage": 3,
                "take_profit": round(last + (atr * 2.5), 6), # Тейк 2.5 ATR
                "stop_loss": round(last - (atr * 1.5), 6),   # Стоп 1.5 ATR
                "args_text": "Свинг Лонг (OCO)"
            }

        # Шорт
        if struct == "downtrend" and vol_spike and rsi > 30 and macro_filter != "block_shorts":
            return {
                "signal": "short",
                "leverage": 3,
                "take_profit": round(last - (atr * 2.5), 6),
                "stop_loss": round(last + (atr * 1.5), 6),
                "args_text": "Свинг Шорт (OCO)"
            }

        return {"signal": "neutral"}

    def analyze_spot(self, data, symbol, macro_filter="allow_all"):
        if self.is_cooling_down(symbol) or macro_filter == "block_longs":
            return {"signal": "neutral"}

        last = data.get("last_price", 0)
        struct = data.get("structure", "ranging")
        rsi = data.get("rsi", 50)
        ladder = data.get("support_ladder", [])

        # Покупка отката на споте (Pullback DCA)
        if struct == "uptrend" and rsi < 45 and len(ladder) >= 3:
            return {
                "signal": "long_dca",
                "orders": [
                    {"price": round(ladder[0], 6), "size_pct": 20}, # 20% депо на ближнюю
                    {"price": round(ladder[1], 6), "size_pct": 30}, # 30% депо глубже
                    {"price": round(ladder[2], 6), "size_pct": 50}  # 50% депо на дно
                ],
                "take_profit": round(data.get("resistance", last * 1.05), 6),
                "args_text": "Спот DCA Лесенка"
            }

        return {"signal": "neutral"}
