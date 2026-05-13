import time
from typing import Any, Dict, Optional
from config import CONFIG
from validators import safe_float, safe_str

class PositionGuide:
    """
    VORTEX 1.7.8 Position Guide (Adaptive ATR Logic).
    """
    def __init__(self) -> None:
        g_cfg = getattr(CONFIG, "position_guide", None)
        self.enabled = bool(getattr(g_cfg, "enabled", True))
        
        # Коэффициенты защиты (ATR-based вместо USDT)
        self.be_atr_trigger = safe_float(getattr(g_cfg, "be_atr_trigger", 1.2), 1.2)
        self.trail_atr_trigger = safe_float(getattr(g_cfg, "trail_atr_trigger", 2.0), 2.0)
        self.trail_atr_dist = safe_float(getattr(g_cfg, "trail_atr_dist", 1.5), 1.5)

        # Параметры закрытия
        self.fade_ratio = safe_float(getattr(g_cfg, "fade_keep_ratio", 0.5), 0.5)
        self.profit_timeout_sec = int(safe_float(getattr(g_cfg, "profit_timeout_sec", 3600), 3600))
        
        # Комиссии (берём из конфига биржи)
        self.fut_fee = safe_float(CONFIG.futures.taker_fee, 0.0006)
        self.spot_fee = safe_float(CONFIG.spot.taker_fee, 0.001)

    def _calculate_fees(self, price, qty, market="futures"):
        fee_rate = self.fut_fee if market == "futures" else self.spot_fee
        # Вход + Выход = x2
        return price * qty * fee_rate * 2

    def _hold(self, reason="HOLD", meta=None):
        return {"action": "HOLD", "reason": reason, "new_sl": 0.0, "meta": meta or {}}

    def _move_sl(self, reason, new_sl, meta=None):
        return {"action": "MOVE_SL", "reason": reason, "new_sl": round(float(new_sl), 8), "meta": meta or {}}

    def _close(self, reason, meta=None):
        return {"action": "CLOSE", "reason": reason, "new_sl": 0.0, "meta": meta or {}}

    def evaluate(self, position: Dict[str, Any], current_price: float, ta_item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.enabled or not position: return self._hold("DISABLED_OR_NO_POS")

        side = safe_str(position.get("side")).lower()
        entry = safe_float(position.get("entry"))
        qty = safe_float(position.get("qty"))
        sl = safe_float(position.get("sl"))
        atr = safe_float(position.get("atr"))
        pnl_net = safe_float(position.get("pnl_net"))
        max_pnl = safe_float(position.get("max_pnl_net"))
        hold_sec = int(safe_float(position.get("hold_sec", 0)))
        
        price = safe_float(current_price)
        ta = ta_item or {}
        
        if price <= 0 or entry <= 0 or atr <= 0: return self._hold("WAIT_DATA")

        meta = {"symbol": position.get("symbol"), "pnl_net": pnl_net}

        # 1. Расчет порога окупаемости (Break Even + Fees)
        est_fees = self._calculate_fees(entry, qty)
        be_level = entry + (est_fees / qty) if side == "long" else entry - (est_fees / qty)

        # 2. Wick Guard (Экстренный подтяг стопа при разворотной тени)
        if pnl_net > est_fees: # Только если мы уже в плюсе
            is_danger = ta.get("wick_long_danger") if side == "long" else ta.get("wick_short_danger")
            if is_danger:
                # Агрессивно подтягиваем стоп к середине текущей прибыли
                tight_sl = (price + entry) / 2
                return self._move_sl("WICK_REJECTION_GUARD", tight_sl, meta)

        # 3. Break-Even (Адаптивный по ATR)
        if pnl_net > 0 and not position.get("breakeven"):
            dist = abs(price - entry)
            if dist >= (atr * self.be_atr_trigger):
                return self._move_sl("ADAPTIVE_BE", be_level, meta)

        # 4. Trailing Stop (Адаптивный по ATR)
        if pnl_net >= (atr * self.trail_atr_trigger):
            new_sl = price - (atr * self.trail_atr_dist) if side == "long" else price + (atr * self.trail_atr_dist)
            # Двигаем стоп только вверх для лонга (или вниз для шорта)
            if (side == "long" and new_sl > sl) or (side == "short" and (sl <= 0 or new_sl < sl)):
                return self._move_sl("GUIDE_ATR_TRAIL", new_sl, meta)

        # 5. Profit Timeout
        if hold_sec > self.profit_timeout_sec and pnl_net > est_fees:
            return self._close("TIME_PROFIT_TAKE", meta)

        return self._hold("NO_ACTION", meta)
