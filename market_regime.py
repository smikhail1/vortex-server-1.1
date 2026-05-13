from typing import Any, Dict
from config import CONFIG
from validators import safe_bool, safe_float, safe_int, safe_str

class MarketRegimeEvaluator:
    def __init__(self) -> None:
        self.cfg = CONFIG.regime

    def classify_trend(self, price: float, ema20: float, ema50: float) -> str:
        if price <= 0 or ema20 <= 0 or ema50 <= 0: return "neutral"
        gap_pct = abs(ema20 - ema50) / ema50 * 100 if ema50 > 0 else 0.0
        if price > ema20 > ema50:
            if gap_pct >= self.cfg.strong_trend_ema_gap_pct: return "strong_up"
            if gap_pct >= self.cfg.weak_trend_ema_gap_pct: return "up"
        elif price < ema20 < ema50:
            if gap_pct >= self.cfg.strong_trend_ema_gap_pct: return "strong_down"
            if gap_pct >= self.cfg.weak_trend_ema_gap_pct: return "down"
        return "neutral"

    def classify_local_bias(self, price: float, ema10: float, ema20: float) -> str:
        if price <= 0 or ema10 <= 0 or ema20 <= 0: return "neutral"
        if price > ema10 > ema20: return "up"
        if price < ema10 < ema20: return "down"
        return "neutral"

    def classify_regime(self, trend_4h: str, atr_pct: float, vol_ratio: float, breakout: bool) -> str:
        if atr_pct <= 0: return "unknown"
        if atr_pct < self.cfg.min_workable_atr_pct: return "dead"
        if atr_pct > self.cfg.max_bad_atr_pct: return "chaotic"
        if trend_4h in {"strong_up", "strong_down"}:
            if breakout and vol_ratio >= self.cfg.breakout_volume_threshold: return "trend_expansion"
            return "trend"
        if trend_4h in {"up", "down"}:
            if vol_ratio >= self.cfg.trend_volume_threshold: return "trend"
            return "structured"
        return "range"

    def build_symbol_context(self, ta: Dict[str, Any]) -> Dict[str, Any]:
        price, ema10, ema20, ema50 = safe_float(ta.get("price")), safe_float(ta.get("ema10")), safe_float(ta.get("ema20")), safe_float(ta.get("ema50"))
        atr_pct, vol_ratio, breakout = safe_float(ta.get("atr_pct")), safe_float(ta.get("vol_ratio"), 1.0), safe_bool(ta.get("breakout"))
        trend_4h = self.classify_trend(price, ema20, ema50)
        return {
            "trend_4h": trend_4h,
            "trend_bias_30m": self.classify_local_bias(price, ema10, ema20),
            "market_regime": self.classify_regime(trend_4h, atr_pct, vol_ratio, breakout),
            "vol_confirmed": vol_ratio >= self.cfg.trend_volume_threshold,
            "breakout_volume_confirmed": vol_ratio >= self.cfg.breakout_volume_threshold,
            "vol_spike": vol_ratio >= self.cfg.vol_spike_threshold,
        }

    def evaluate_macro(self, macro: Dict[str, Any]) -> Dict[str, Any]:
        btc_trend = safe_str(macro.get("btc_trend"), "neutral")
        usdt_d_trend = safe_str(macro.get("usdt_d_trend"), "neutral")
        fng_value = safe_int(macro.get("fng_value"), 50)
        oi_amount = safe_float(macro.get("oi_amount"), 0.0)

        risk_state = "neutral"
        
        # [MACRO LOGIC] Если доминация USDT растет (capital flight) или BTC летит вниз = Risk OFF
        if "strong_bearish" in btc_trend or fng_value <= self.cfg.macro_fng_riskoff_threshold or usdt_d_trend == "capital_flight":
            risk_state = "risk_off"
        elif "strong_bullish" in btc_trend or fng_value >= self.cfg.macro_fng_riskon_threshold:
            risk_state = "risk_on"

        allow_longs = risk_state != "risk_off"
        # Запрещаем шорты только если дикая бычка
        allow_shorts = btc_trend not in {"strong_bullish"} and fng_value < 80

        global_filter = "allow_all"
        if not allow_longs and allow_shorts:
            global_filter = "block_longs"
        elif allow_longs and not allow_shorts:
            global_filter = "block_shorts"
        elif not allow_longs and not allow_shorts:
            global_filter = "block_all"

        return {
            "btc_trend": btc_trend,
            "usdt_d_trend": usdt_d_trend,
            "fng_value": fng_value,
            "oi_amount": oi_amount,
            "risk_state": risk_state,
            "allow_longs": allow_longs,
            "allow_shorts": allow_shorts,
            "global_filter": global_filter,
        }
