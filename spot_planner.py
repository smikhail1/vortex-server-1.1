import json
import time
from pathlib import Path
from typing import Any, Dict, List

from config import CONFIG
from validators import safe_float, safe_int, safe_str


# VORTEX v1.8.24-g planner quality metadata layer.
# These helpers enrich Planner output only. They never block entries.
LIQUIDITY_SHADOW_PATH = Path("_runtime/coin_liquidity_latest.json")


def planner_rr_grade(rr_ratio: float) -> str:
    if rr_ratio < 1.2:
        return "bad"
    if rr_ratio < 1.8:
        return "acceptable"
    if rr_ratio < 2.5:
        return "good"
    return "excellent"


def planner_distance_to_zone_pct(price: float, zone_top: float, zone_bottom: float) -> float:
    if price <= 0 or zone_top <= 0 or zone_bottom <= 0:
        return 0.0
    if zone_bottom <= price <= zone_top:
        return 0.0
    closest = zone_bottom if price < zone_bottom else zone_top
    return round(abs(price - closest) / price * 100.0, 4)


def planner_liquidity_shadow() -> Dict[str, Dict[str, Any]]:
    try:
        data = json.loads(LIQUIDITY_SHADOW_PATH.read_text(encoding="utf-8"))
        return {
            safe_str(item.get("symbol")).upper(): item
            for item in (data.get("items") or [])
            if isinstance(item, dict) and item.get("symbol")
        }
    except Exception:
        return {}


def planner_liquidity_alignment(item: Dict[str, Any]) -> str:
    if not item or item.get("available") is False or item.get("stale") is True:
        return "unknown"
    bias = safe_str(item.get("liquidity_bias")).lower()
    if bias in {"long", "mild_long", "strong_long"}:
        return "supportive"
    if bias in {"short", "mild_short", "strong_short"}:
        return "against"
    return "neutral"


class SpotPlannerEngine:
    """
    Planner:
    - показывает сильные идеи, даже если входить сейчас рано
    - planner != terminal watchlist
    - planner отвечает за широкую картину, зоны и RR
    """

    def __init__(self, logger=None) -> None:
        self.logger = logger

    @staticmethod
    def _trend_label(price: float, ema20: float, ema50: float) -> str:
        if price > ema20 > ema50:
            return "uptrend"
        if price < ema20 < ema50:
            return "downtrend"
        return "range"

    @staticmethod
    def _structure_label(price: float, recent_high: float, recent_low: float) -> str:
        mid = (recent_high + recent_low) / 2 if recent_high > recent_low else price
        if price >= mid * 1.01:
            return "HH/HL"
        if price <= mid * 0.99:
            return "LH/LL"
        return "RANGE"

    @staticmethod
    def _confidence_band(score: int) -> str:
        if score >= 85:
            return "A"
        if score >= 72:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    @staticmethod
    def _risk_grade(atr_pct: float) -> str:
        if atr_pct <= 3.5:
            return "Низкий риск"
        if atr_pct <= 6.5:
            return "Средний риск"
        return "Высокий риск"

    @staticmethod
    def _readiness(price: float, zone_top: float, zone_bottom: float) -> str:
        if zone_bottom <= price <= zone_top:
            return "HIGH"

        zone_height = max(abs(zone_top - zone_bottom), price * 0.01)
        dist = min(abs(price - zone_top), abs(price - zone_bottom))

        if dist <= zone_height * 0.5:
            return "MID"

        return "LOW"

    @staticmethod
    def _status_label(price: float, zone_top: float, zone_bottom: float) -> str:
        if zone_bottom <= price <= zone_top:
            return "В зоне"

        zone_height = max(abs(zone_top - zone_bottom), price * 0.01)
        dist = min(abs(price - zone_top), abs(price - zone_bottom))

        if dist <= zone_height * 0.5:
            return "Рядом с зоной"

        if price < zone_bottom:
            return "Глубоко"

        return "Выше зоны"

    def _score_symbol(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        d1 = metrics.get("d1", {})
        w1 = metrics.get("w1", {})
        h4 = metrics.get("h4", {})

        score = 0
        reasons: List[str] = []

        trend_d1 = self._trend_label(safe_float(d1.get("price")), safe_float(d1.get("ema20")), safe_float(d1.get("ema50")))
        trend_w1 = self._trend_label(safe_float(w1.get("price")), safe_float(w1.get("ema20")), safe_float(w1.get("ema50")))
        structure_4h = self._structure_label(safe_float(h4.get("price")), safe_float(h4.get("recent_high")), safe_float(h4.get("recent_low")))

        if trend_d1 == "uptrend":
            score += 25
            reasons.append("D1 тренд вверх")
        elif trend_d1 == "range":
            score += 10
            reasons.append("D1 в диапазоне")
        else:
            score += 2
            reasons.append("D1 слабый")

        if trend_w1 == "uptrend":
            score += 22
            reasons.append("W1 поддерживает")
        elif trend_w1 == "range":
            score += 10
            reasons.append("W1 нейтрален")
        else:
            score += 4
            reasons.append("W1 слабый")

        if structure_4h == "HH/HL":
            score += 18
            reasons.append("4H структура роста")
        elif structure_4h == "RANGE":
            score += 10
            reasons.append("4H консолидация")
        else:
            score += 3
            reasons.append("4H слабая структура")

        vol_ratio = safe_float(h4.get("vol_ratio"), 1.0)
        if vol_ratio >= 1.2:
            score += 12
            reasons.append("Объем выше среднего")
        elif vol_ratio >= 0.9:
            score += 6
            reasons.append("Объем нормальный")

        atr_pct = safe_float(h4.get("atr_pct"), 0.0)
        if 2.0 <= atr_pct <= 8.0:
            score += 10
            reasons.append("Волатильность рабочая")
        elif atr_pct < 2.0:
            score += 4
            reasons.append("Волатильность низкая")
        else:
            score += 6
            reasons.append("Волатильность высокая")

        score = min(score, 99)

        return {
            "score": score,
            "reasons": reasons[:6],
            "trend_d1": trend_d1,
            "trend_w1": trend_w1,
            "structure_4h": structure_4h,
            "atr_pct": atr_pct,
            "vol_ratio": vol_ratio,
        }

    def _build_entries(self, zone_top: float, zone_bottom: float) -> List[Dict[str, Any]]:
        mid = (zone_top + zone_bottom) / 2
        return [
            {"allocation_pct": 40, "price": round(zone_top, 8)},
            {"allocation_pct": 35, "price": round(mid, 8)},
            {"allocation_pct": 25, "price": round(zone_bottom, 8)},
        ]

    def _build_targets(self, avg_entry: float, atr: float) -> List[Dict[str, Any]]:
        tp1 = avg_entry + atr * 2.5
        tp2 = avg_entry + atr * 4.5
        tp3 = avg_entry + atr * 7.0
        return [
            {"price": round(tp1, 8), "close_pct": 30},
            {"price": round(tp2, 8), "close_pct": 35},
            {"price": round(tp3, 8), "close_pct": 35},
        ]

    def _build_idea(self, symbol: str, payload: Dict[str, Any], macro: Dict[str, Any], rank: int, liquidity_by_symbol: Dict[str, Dict[str, Any]] = None) -> Dict[str, Any]:
        # [БЕЗОПАСНОЕ ИЗВЛЕЧЕНИЕ]
        metrics = payload.get("metrics", payload)
        d1 = metrics.get("d1", {})
        w1 = metrics.get("w1", {})
        h4 = metrics.get("h4", {})

        if not d1 or not h4:
            raise ValueError(f"Missing required timeframe data for {symbol}")

        scored = self._score_symbol(metrics)

        current_price = safe_float(payload.get("price"), 0.0)
        if current_price <= 0:
             current_price = safe_float(h4.get("price"), 0.0) # фоллбек

        atr = safe_float(h4.get("atr"), 0.0)
        atr_pct = safe_float(h4.get("atr_pct"), 0.0)

        zone_top = min(safe_float(h4.get("ema20")), current_price * 0.99)
        zone_bottom = min(safe_float(h4.get("ema50")), zone_top * 0.992)

        if zone_bottom <= 0:
            zone_bottom = current_price * 0.95
        if zone_top <= 0:
            zone_top = current_price * 0.98
        if zone_bottom > zone_top:
            zone_bottom, zone_top = zone_top, zone_bottom

        avg_entry = round((zone_top + zone_bottom) / 2, 8)
        invalidation = round(max(zone_bottom - atr * 1.2, zone_bottom * 0.985), 8)

        targets = self._build_targets(avg_entry, atr if atr > 0 else current_price * 0.03)
        rr_denom = max(avg_entry - invalidation, avg_entry * 0.01)
        rr_ratio = (targets[1]["price"] - avg_entry) / rr_denom if rr_denom > 0 else 0.0

        readiness = self._readiness(current_price, zone_top, zone_bottom)
        status = self._status_label(current_price, zone_top, zone_bottom)
        confidence_band = self._confidence_band(scored["score"])
        risk_grade = self._risk_grade(atr_pct)

        risk_state = safe_str(macro.get("risk_state"), "neutral")
        global_filter = safe_str(macro.get("global_filter"), "allow_all")

        blocked_reason = None
        if global_filter == "block_longs":
            blocked_reason = "macro risk-off"
        elif risk_state == "risk_off":
            blocked_reason = "macro risk-off"

        ready = readiness == "HIGH" and blocked_reason is None

        if ready:
            action_label = "Набор в зоне"
            action_hint = "Цена в рабочей зоне. Можно набирать позицию."
        elif readiness == "MID":
            action_label = "Подготовка к набору"
            action_hint = "Цена рядом с зоной. Ждем подхода."
        else:
            action_label = "Наблюдение"
            action_hint = "Пока рано. Идея сильная, но цена еще не в зоне."

        expected_return_base_pct = ((targets[0]["price"] - avg_entry) / avg_entry) * 100 if avg_entry > 0 else 0.0
        expected_return_bull_pct = ((targets[2]["price"] - avg_entry) / avg_entry) * 100 if avg_entry > 0 else 0.0

        tier = "A" if scored["score"] >= 80 else ("B" if scored["score"] >= 68 else "C")
        horizon = "Среднесрок 1–4 недели" if scored["trend_w1"] != "downtrend" else "Наблюдение"

        thesis = list(scored["reasons"])
        if blocked_reason:
            thesis.append(blocked_reason)

        # VORTEX v1.8.24-g planner quality metadata layer.
        # The fields below are advisory and snapshot-ready. Existing Planner
        # selection and ready behavior intentionally remain unchanged.
        distance_to_zone_pct = planner_distance_to_zone_pct(current_price, zone_top, zone_bottom)
        rr_grade = planner_rr_grade(rr_ratio)
        too_late = bool(zone_top > 0 and current_price > zone_top * 1.03)
        bad_rr = rr_grade == "bad"
        if zone_bottom <= current_price <= zone_top:
            zone_quality = "in_zone"
        elif distance_to_zone_pct <= 1.0:
            zone_quality = "near_zone"
        elif too_late:
            zone_quality = "too_late"
        else:
            zone_quality = "outside_zone"

        regime = safe_str(macro.get("regime") or macro.get("risk_state"), "neutral").lower()
        if global_filter == "block_longs" or regime in {"risk_off", "risk_off_bearish"}:
            market_alignment = "against"
        elif regime in {"risk_on", "risk_on_bullish", "mild_risk_on"}:
            market_alignment = "supportive"
        else:
            market_alignment = "neutral"

        liquidity_item = (liquidity_by_symbol or {}).get(symbol.upper(), {})
        liquidity_alignment = planner_liquidity_alignment(liquidity_item)
        warnings = []
        if bad_rr:
            warnings.append("bad_rr")
        if too_late:
            warnings.append("price_too_far_above_zone")
        if market_alignment == "against":
            warnings.append("macro_market_against_buy")
        if liquidity_alignment == "against":
            warnings.append("liquidity_shadow_against_buy")

        if current_price < invalidation:
            advisor_status = "INVALIDATED"
        elif bad_rr:
            advisor_status = "BAD_RR"
        elif too_late:
            advisor_status = "TOO_LATE"
        elif market_alignment == "against":
            advisor_status = "MARKET_AGAINST"
        elif liquidity_alignment == "against":
            advisor_status = "LIQUIDITY_CONFLICT"
        elif zone_quality == "in_zone":
            advisor_status = "WAIT_CONFIRMATION"
        elif zone_quality == "near_zone":
            advisor_status = "NEAR_ZONE"
        else:
            advisor_status = "IDEA_ONLY"

        advisor_verdict = {
            "INVALIDATED": "idea_invalidation_breached",
            "BAD_RR": "bad_risk_reward",
            "TOO_LATE": "price_above_entry_zone",
            "MARKET_AGAINST": "macro_market_against_buy",
            "LIQUIDITY_CONFLICT": "liquidity_shadow_conflict",
            "WAIT_CONFIRMATION": "valid_idea_wait_confirmation",
            "NEAR_ZONE": "valid_idea_near_zone",
        }.get(advisor_status, "idea_only_wait_zone")
        generated_at = int(time.time())
        position_plan = {
            "source": "planner",
            "plan_type": "planner_swing_spot",
            "plan_version": "1.8.24-g",
            "management_profile": "planner_swing_spot_v1",
            "entry_mode": "single_entry_first",
            "tp1": targets[0]["price"],
            "tp1_close_pct": 30,
            "tp2": targets[1]["price"],
            "tp2_close_pct": 35,
            "runner_pct": 35,
            "invalidation": invalidation,
            "breakeven_after_tp1": True,
            "trail_atr_mult": 1.8,
            "timeout_sec": 2419200,
            "weak_progress_sec": 604800,
        }

        return {
            "symbol": symbol,
            "tier": tier,
            "score": safe_int(scored["score"]),
            "priority_rank": rank,
            "confidence_score": safe_int(scored["score"]),
            "confidence_band": confidence_band,
            "horizon": horizon,
            "risk_grade": risk_grade,
            "status": status,
            "readiness": readiness,
            "rr_ratio": round(rr_ratio, 2),
            "current_price": round(current_price, 8),
            "accumulation_zone": {
                "top": round(zone_top, 8),
                "bottom": round(zone_bottom, 8),
            },
            "avg_entry": avg_entry,
            "entries": self._build_entries(zone_top, zone_bottom),
            "targets": targets,
            "invalidation": invalidation,
            "expected_return_base_pct": round(expected_return_base_pct, 2),
            "expected_return_bull_pct": round(expected_return_bull_pct, 2),
            "trend_d1": scored["trend_d1"],
            "trend_w1": scored["trend_w1"],
            "structure_4h": scored["structure_4h"],
            "action_label": action_label,
            "action_hint": action_hint,
            "thesis": thesis[:8],
            "blocked_reason": blocked_reason,
            "ready": ready,
            "setup_type": "spot_pullback",
            "action": action_label,
            "entry_zone": [round(zone_top, 8), round(zone_bottom, 8)],
            "rr": round(rr_ratio, 2),
            "confidence": safe_int(scored["score"]),
            "risk": "low" if risk_grade == "Низкий риск" else ("medium" if risk_grade == "Средний риск" else "high"),
            "invalid_level": invalidation,
            "tp_base": targets[0]["price"],
            "tp_bull": targets[2]["price"],
            "reasons": thesis[:8],
            "plan_type": "planner_swing_spot",
            "plan_version": "1.8.24-g",
            "idea_id": f"planner:{symbol}:{generated_at}",
            "generated_at": generated_at,
            "captured_at": None,
            "management_profile": "planner_swing_spot_v1",
            "advisor_status": advisor_status,
            "advisor_verdict": advisor_verdict,
            "zone_quality": zone_quality,
            "zone_grade": zone_quality,
            "rr_grade": rr_grade,
            "market_alignment": market_alignment,
            "liquidity_alignment": liquidity_alignment,
            "distance_to_zone_pct": distance_to_zone_pct,
            "too_late": too_late,
            "bad_rr": bad_rr,
            "quality_notes": warnings[:],
            "warnings": warnings[:],
            "position_plan": position_plan,
        }

    def build(self, planner_market_data: Dict[str, Any], macro: Dict[str, Any]) -> Dict[str, Any]:
        symbols_map = planner_market_data.get("symbols", {}) if isinstance(planner_market_data, dict) else {}
        ideas: List[Dict[str, Any]] = []
        # Shadow-only context: absence or corruption must never break Planner.
        liquidity_by_symbol = planner_liquidity_shadow()

        for symbol, payload in symbols_map.items():
            try:
                idea = self._build_idea(symbol, payload, macro or {}, rank=0, liquidity_by_symbol=liquidity_by_symbol)
                ideas.append(idea)
            except Exception as exc:
                if self.logger:
                    self.logger.error("PLANNER", "idea build failed", {
                        "symbol": symbol,
                        "error": str(exc),
                    })

        readiness_rank = {
            "HIGH": 3,
            "MID": 2,
            "LOW": 1,
        }

        ideas.sort(
            key=lambda x: (
                readiness_rank.get(x.get("readiness", "LOW"), 0),
                x.get("score", 0),
                x.get("rr_ratio", 0.0),
            ),
            reverse=True,
        )

        for index, idea in enumerate(ideas, start=1):
            idea["priority_rank"] = index

        ideas = ideas[:CONFIG.planner.max_ideas]
        generated_at = int(time.time())

        payload = {
            "ideas": ideas,
            "spot_ideas": ideas,
            "generated_at": generated_at,
            "last_update_ts": generated_at,
            "mode": "PLANNER",
            "status": "OK" if ideas else "EMPTY",
        }

        if self.logger:
            self.logger.info("PLANNER", "planner payload built", {
                "ideas_count": len(ideas),
                "generated_at": generated_at,
            })

        return payload