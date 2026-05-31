#!/usr/bin/env python3
"""Read-only quality audit for Planner spot ideas."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional


SCHEMA = "vortex.planner_audit.api.v1"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> List[Dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def _rr_grade(rr_ratio: float) -> str:
    if rr_ratio < 1.2:
        return "bad"
    if rr_ratio < 1.8:
        return "acceptable"
    if rr_ratio < 2.5:
        return "good"
    return "excellent"


def _distance_to_zone_pct(price: float, zone_bottom: float, zone_top: float) -> float:
    if price <= 0 or zone_bottom <= 0 or zone_top <= 0:
        return 0.0
    if zone_bottom <= price <= zone_top:
        return 0.0
    closest = zone_bottom if price < zone_bottom else zone_top
    return round(abs(price - closest) / price * 100.0, 4)


def _market_alignment(macro: Mapping[str, Any]) -> str:
    regime = str(macro.get("regime") or "").lower()
    long_permission = str(_dict(macro.get("recommendation")).get("long_permission") or "").lower()
    if regime == "risk_off_bearish" or long_permission in {"blocked", "disabled"}:
        return "against"
    if regime in {"risk_on_bullish", "mild_risk_on"} and long_permission in {"normal", "selective_plus", ""}:
        return "supportive"
    return "neutral"


def _liquidity_alignment(item: Mapping[str, Any]) -> str:
    if not item or item.get("available") is False or item.get("stale") is True:
        return "unknown"
    bias = str(item.get("liquidity_bias") or "").lower()
    if bias in {"long", "mild_long", "strong_long"}:
        return "supportive"
    if bias in {"short", "mild_short", "strong_short"}:
        return "against"
    return "neutral"


def _advisor_status(
    *,
    price: float,
    invalidation: float,
    zone_bottom: float,
    zone_top: float,
    distance_pct: float,
    rr_grade: str,
    market_alignment: str,
    liquidity_alignment: str,
) -> str:
    if invalidation > 0 and price > 0 and price < invalidation:
        return "INVALIDATED"
    if rr_grade == "bad":
        return "BAD_RR"
    if zone_top > 0 and price > zone_top * 1.03:
        return "TOO_LATE"
    if market_alignment == "against":
        return "MARKET_AGAINST"
    if liquidity_alignment == "against":
        return "LIQUIDITY_CONFLICT"
    if zone_bottom > 0 and zone_bottom <= price <= zone_top:
        return "WAIT_CONFIRMATION"
    if distance_pct <= 1.0 and zone_top > 0:
        return "NEAR_ZONE"
    return "IDEA_ONLY"


def _verdict(status: str) -> str:
    return {
        "WAIT_CONFIRMATION": "valid_idea_wait_confirmation",
        "NEAR_ZONE": "valid_idea_near_zone",
        "IN_ZONE": "valid_idea_in_zone",
        "BAD_RR": "bad_risk_reward",
        "TOO_LATE": "price_above_entry_zone",
        "MARKET_AGAINST": "macro_market_against_buy",
        "LIQUIDITY_CONFLICT": "liquidity_shadow_conflict",
        "INVALIDATED": "idea_invalidation_breached",
        "EXPIRED": "idea_expired",
    }.get(status, "idea_only_wait_zone")


def _warning_list(status: str, liquidity_item: Mapping[str, Any]) -> List[str]:
    warnings: List[str] = []
    if status == "BAD_RR":
        warnings.append("rr_below_1_2")
    elif status == "TOO_LATE":
        warnings.append("price_too_far_above_zone")
    elif status == "MARKET_AGAINST":
        warnings.append("macro_market_against_buy")
    elif status == "LIQUIDITY_CONFLICT":
        warnings.append("liquidity_shadow_against_buy")
    if liquidity_item.get("stale") is True:
        warnings.append("liquidity_shadow_stale")
    return warnings


def build_planner_audit(
    dashboard: Optional[Mapping[str, Any]] = None,
    liquidity_payload: Optional[Mapping[str, Any]] = None,
    macro_payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a display-only assessment without mutating Planner or trading state."""
    dashboard = dashboard or {}
    planner = _dict(_dict(dashboard.get("planner")).get("spot_planner"))
    ideas = _items(planner.get("spot_ideas") or planner.get("ideas"))
    macro = _dict(macro_payload) or _dict(dashboard.get("macro_regime"))
    liquidity = _dict(liquidity_payload)
    liquidity_by_symbol = {
        str(item.get("symbol") or "").upper(): item for item in _items(liquidity.get("items"))
    }

    out: List[Dict[str, Any]] = []
    for idea in ideas:
        symbol = str(idea.get("symbol") or "").upper()
        zone = _dict(idea.get("accumulation_zone"))
        zone_top = _float(zone.get("top"), _float((idea.get("entry_zone") or [0])[0] if idea.get("entry_zone") else 0))
        zone_bottom = _float(zone.get("bottom"), _float((idea.get("entry_zone") or [0, 0])[-1] if idea.get("entry_zone") else 0))
        if zone_bottom > zone_top:
            zone_bottom, zone_top = zone_top, zone_bottom
        current_price = _float(idea.get("current_price"))
        invalidation = _float(idea.get("invalidation"), _float(idea.get("invalid_level")))
        rr_ratio = _float(idea.get("rr_ratio"), _float(idea.get("rr")))
        distance_pct = _distance_to_zone_pct(current_price, zone_bottom, zone_top)
        rr_grade = _rr_grade(rr_ratio)
        liquidity_item = liquidity_by_symbol.get(symbol, {})
        market_alignment = _market_alignment(macro)
        liquidity_alignment = _liquidity_alignment(liquidity_item)
        advisor_status = _advisor_status(
            price=current_price,
            invalidation=invalidation,
            zone_bottom=zone_bottom,
            zone_top=zone_top,
            distance_pct=distance_pct,
            rr_grade=rr_grade,
            market_alignment=market_alignment,
            liquidity_alignment=liquidity_alignment,
        )
        zone_grade = idea.get("zone_grade") or idea.get("zone_quality") or (
            "in_zone" if distance_pct == 0.0 and zone_top > 0
            else ("near_zone" if distance_pct <= 1.0 and zone_top > 0 else "outside_zone")
        )
        out.append({
            "symbol": symbol,
            "side": "BUY",
            "setup_type": idea.get("setup_type") or "spot_pullback",
            "score": idea.get("score"),
            "tier": idea.get("tier"),
            "readiness": idea.get("readiness"),
            "status": idea.get("status"),
            "current_price": current_price,
            "zone_top": zone_top,
            "zone_bottom": zone_bottom,
            "distance_to_zone_pct": distance_pct,
            "avg_entry": _float(idea.get("avg_entry")),
            "invalidation": invalidation,
            "tp_base": _float(idea.get("tp_base")),
            "tp_bull": _float(idea.get("tp_bull")),
            "rr_ratio": rr_ratio,
            "rr_grade": rr_grade,
            "zone_grade": zone_grade,
            "zone_quality": zone_grade,
            "market_alignment": market_alignment,
            "liquidity_alignment": liquidity_alignment,
            "advisor_status": idea.get("advisor_status") or advisor_status,
            "advisor_verdict": idea.get("advisor_verdict") or _verdict(advisor_status),
            "plan_type": idea.get("plan_type"),
            "plan_version": idea.get("plan_version"),
            "idea_id": idea.get("idea_id"),
            "management_profile": idea.get("management_profile"),
            "position_plan": _dict(idea.get("position_plan")),
            "warnings": idea.get("warnings") or _warning_list(advisor_status, liquidity_item),
        })

    counts = Counter(str(item.get("advisor_status") or "UNKNOWN").lower() for item in out)
    return {
        "ok": True,
        "schema": SCHEMA,
        "read_only": True,
        "items_len": len(out),
        "items": out,
        "summary": dict(counts),
    }


__all__ = ["SCHEMA", "build_planner_audit"]
