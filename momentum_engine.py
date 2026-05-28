from dataclasses import dataclass
from typing import Dict, Optional

from config import CONFIG
from validators import safe_bool, safe_float, safe_str

@dataclass(frozen=True)
class MomentumSignal:
    active: bool
    confirmed: bool
    side: str
    score: int
    setup_type: str
    reason: str
    trigger_price: float
    invalidation_price: float
    range_pct: float
    change_pct: float
    vol_ratio: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "active": self.active,
            "confirmed": self.confirmed,
            "side": self.side,
            "score": self.score,
            "setup_type": self.setup_type,
            "reason": self.reason,
            "trigger_price": round(self.trigger_price, 8),
            "invalidation_price": round(self.invalidation_price, 8),
            "range_pct": round(self.range_pct, 4),
            "change_pct": round(self.change_pct, 4),
            "vol_ratio": round(self.vol_ratio, 4),
        }

class MomentumEngine:
    """
    VORTEX 1.5 Movement Hunter. (With OI & Funding Blockers)
    """

    def __init__(self) -> None:
        self.enabled = bool(CONFIG.momentum.enabled)

    def _range_pct(self, data: Dict[str, object], price: float, atr: float) -> float:
        raw = safe_float(data.get("range_pct", data.get("range_24h_pct", data.get("h24_range_pct"))), 0.0)
        if raw > 0: return raw
        high = safe_float(data.get("high_24h", data.get("recent_high")), 0.0)
        low = safe_float(data.get("low_24h", data.get("recent_low")), 0.0)
        if high > 0 and low > 0 and high > low:
            mid = max(price, (high + low) / 2.0)
            if mid > 0: return abs(high - low) / mid * 100.0
        if price > 0 and atr > 0: return atr / price * 100.0
        return 0.0

    def _change_pct(self, data: Dict[str, object], price: float) -> float:
        raw = safe_float(data.get("change_pct", data.get("change_24h_pct", data.get("h24_change_pct", data.get("price_change_pct")))), 0.0)
        if raw != 0.0: return raw
        open_24h = safe_float(data.get("open_24h"), 0.0)
        if open_24h > 0 and price > 0: return (price - open_24h) / open_24h * 100.0
        return 0.0

    def _base_score(self, range_pct: float, change_pct: float, vol_ratio: float, breakout: bool) -> int:
        score = 0
        if range_pct >= CONFIG.momentum.min_range_pct: score += 2
        if abs(change_pct) >= CONFIG.momentum.min_change_abs_pct: score += 2
        if vol_ratio >= CONFIG.momentum.min_vol_ratio: score += 2
        if breakout: score += 1
        if range_pct >= CONFIG.momentum.strong_range_pct: score += 1
        if abs(change_pct) >= CONFIG.momentum.strong_change_abs_pct: score += 1
        if vol_ratio >= CONFIG.momentum.strong_vol_ratio: score += 1
        return score

    def _quality_block_reason(self, data: Dict[str, object], side: str, price: float, atr: float, ema20: float, rsi: float, range_pct: float, change_pct: float) -> str:
        cfg = CONFIG.momentum
        if not safe_bool(getattr(cfg, "quality_filter_enabled", True), True): return ""
        side_u = safe_str(side).upper()

        if side_u == "LONG" and rsi >= safe_float(getattr(cfg, "long_rsi_exhaustion", 78.0), 78.0):
            return f"long RSI exhaustion {rsi:.2f}>={safe_float(getattr(cfg, 'long_rsi_exhaustion', 78.0), 78.0):.2f}"
        if side_u == "SHORT" and rsi <= safe_float(getattr(cfg, "short_rsi_exhaustion", 22.0), 22.0):
            return f"short RSI exhaustion {rsi:.2f}<={safe_float(getattr(cfg, 'short_rsi_exhaustion', 22.0), 22.0):.2f}"

        if price > 0 and ema20 > 0:
            ema_dist_pct = abs(price - ema20) / ema20 * 100.0
            max_ema_pct = safe_float(getattr(cfg, "max_ema_distance_pct", 8.0), 8.0)
            if ema_dist_pct > max_ema_pct: return f"EMA dist too high {ema_dist_pct:.2f}%>{max_ema_pct:.2f}%"

        max_range = safe_float(getattr(cfg, "max_quality_range_pct", 22.0), 22.0)
        if range_pct >= max_range: return f"range overextended {range_pct:.2f}%>={max_range:.2f}%"

        max_change = safe_float(getattr(cfg, "max_quality_change_abs_pct", 18.0), 18.0)
        if abs(change_pct) >= max_change: return f"change overextended {change_pct:.2f}%>={max_change:.2f}%"
        return ""

    def evaluate_futures(self, data: Dict[str, object], market_regime: str = "", macro: Optional[Dict[str, object]] = None, oi_trend: str = "neutral") -> MomentumSignal:
        if not self.enabled: return self._none("disabled")

        price = safe_float(data.get("price"), 0.0)
        atr = safe_float(data.get("atr"), 0.0)
        ema20 = safe_float(data.get("ema20"), 0.0)
        ema50 = safe_float(data.get("ema50"), 0.0)
        recent_high = safe_float(data.get("recent_high"), 0.0)
        recent_low = safe_float(data.get("recent_low"), 0.0)
        rsi = safe_float(data.get("rsi_main"), 50.0)
        vol_ratio = safe_float(data.get("vol_ratio"), 1.0)
        breakout = safe_bool(data.get("breakout"), False)
        breakout_dir = safe_str(data.get("breakout_dir"), "")
        trend_bias_1h = safe_str(data.get("trend_bias_1h"), "neutral")
        trend_4h = safe_str(data.get("trend_4h"), "neutral")

        if price <= 0 or atr <= 0: return self._none("invalid price/atr")

        range_pct = self._range_pct(data, price, atr)
        change_pct = self._change_pct(data, price)

        if range_pct < CONFIG.momentum.min_range_pct: return self._none(f"range too low {range_pct:.2f}%", range_pct, change_pct, vol_ratio)
        if abs(change_pct) < CONFIG.momentum.min_change_abs_pct: return self._none(f"change too low {change_pct:.2f}%", range_pct, change_pct, vol_ratio)
        if vol_ratio < CONFIG.momentum.min_vol_ratio: return self._none(f"vol too low {vol_ratio:.2f}", range_pct, change_pct, vol_ratio)

        side = ""
        direction_reason = ""
        if breakout and breakout_dir == "up": side, direction_reason = "LONG", "breakout up"
        elif breakout and breakout_dir == "down": side, direction_reason = "SHORT", "breakout down"
        elif change_pct >= CONFIG.momentum.min_change_abs_pct: side, direction_reason = "LONG", "positive momentum"
        elif change_pct <= -CONFIG.momentum.min_change_abs_pct: side, direction_reason = "SHORT", "negative momentum"

        if not side: return self._none("momentum no direction", range_pct, change_pct, vol_ratio)

        # --- СЕКЦИЯ НОВЫХ ФИЛЬТРОВ (ФАНДИНГ И OI) ---
        symbol = safe_str(data.get("symbol", ""))
        funding_rate = safe_float(data.get("funding_rate"), 0.0)
        
        if macro and "funding_rates" in macro:
            funding_rate = safe_float(macro["funding_rates"].get(symbol, funding_rate), funding_rate)

        if side == "LONG" and funding_rate >= 0.0015:
            return self._none(f"funding block LONG ({funding_rate*100:.3f}% >= 0.15%)", range_pct, change_pct, vol_ratio)
        if side == "SHORT" and funding_rate <= -0.0008:
            return self._none(f"funding block SHORT ({funding_rate*100:.3f}% <= -0.08%)", range_pct, change_pct, vol_ratio)

        if oi_trend == "down":
            return self._none("OI falling (fake move block)", range_pct, change_pct, vol_ratio)
        # -------------------------------------------

        quality_block = self._quality_block_reason(data, side, price, atr, ema20, rsi, range_pct, change_pct)
        if quality_block: return self._none(f"quality blocked: {quality_block}", range_pct, change_pct, vol_ratio)

        aligned = False
        if side == "LONG": aligned = ((price > ema20 > 0 and (ema50 <= 0 or ema20 >= ema50)) or trend_bias_1h == "up" or trend_4h in {"up", "strong_up"} or rsi >= CONFIG.momentum.long_rsi_min)
        else: aligned = ((price < ema20 and ema20 > 0 and (ema50 <= 0 or ema20 <= ema50)) or trend_bias_1h == "down" or trend_4h in {"down", "strong_down"} or rsi <= CONFIG.momentum.short_rsi_max)

        score = self._base_score(range_pct, change_pct, vol_ratio, breakout)
        if aligned: score += 1

        active = score >= CONFIG.momentum.watch_score
        confirmed = score >= CONFIG.momentum.confirm_score and aligned

        if not active: return self._none(f"score low {score}", range_pct, change_pct, vol_ratio)

        setup_type = "momentum_long" if side == "LONG" else "momentum_short"
        if market_regime == "dead": setup_type = "dead_override_" + setup_type

        if side == "LONG":
            trigger = recent_high if recent_high > price else price + atr * CONFIG.momentum.trigger_atr_buffer
            invalidation = price - atr * CONFIG.momentum.invalidation_atr_mult
        else:
            trigger = recent_low if 0 < recent_low < price else price - atr * CONFIG.momentum.trigger_atr_buffer
            invalidation = price + atr * CONFIG.momentum.invalidation_atr_mult

        reason = f"momentum {direction_reason} | range={range_pct:.2f}% | change={change_pct:.2f}% | vol={vol_ratio:.2f} | score={score}"
        if market_regime == "dead": reason += " | dead override candidate"
        if confirmed: reason += " | momentum_confirmed"
        else: reason += " | watch only"

        return MomentumSignal(True, bool(confirmed), side, int(score), setup_type, reason, trigger, invalidation, range_pct, change_pct, vol_ratio)

    def _none(self, reason: str, range_pct: float = 0.0, change_pct: float = 0.0, vol_ratio: float = 0.0) -> MomentumSignal:
        return MomentumSignal(False, False, "", 0, "", reason, 0.0, 0.0, range_pct, change_pct, vol_ratio)
