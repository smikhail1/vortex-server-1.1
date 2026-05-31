#!/usr/bin/env python3
"""Read-only Spot position management advisor.

This module intentionally has no execution dependency. It reports what a
future PAPER manager could do, without mutating positions or balances.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


SCHEMA = "vortex.spot_position_advisor.shadow.v1"
SNAPSHOTS_PATH = Path("_runtime/trade_snapshots.jsonl")


def _dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_latest_planner_snapshots(path: Path = SNAPSHOTS_PATH, max_bytes: int = 1024 * 1024) -> Dict[str, Dict[str, Any]]:
    """Read a bounded tail of the append-only recorder and keep latest Spot plans."""
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            raw = handle.read().decode("utf-8", errors="ignore")
        out: Dict[str, Dict[str, Any]] = {}
        for line in reversed(raw.splitlines()):
            try:
                item = json.loads(line)
            except Exception:
                continue
            symbol = str(item.get("symbol") or "").upper()
            planner = _dict(item.get("planner_snapshot"))
            if symbol and str(item.get("market") or "").upper() == "SPOT" and planner and symbol not in out:
                out[symbol] = planner
        return out
    except Exception:
        return {}


def _liquidity_by_symbol(payload: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(item.get("symbol") or "").upper(): item
        for item in (payload.get("items") or [])
        if isinstance(item, dict) and item.get("symbol")
    }


def _current_price(symbol: str, position: Mapping[str, Any], ta_data: Mapping[str, Any]) -> float:
    current = _dict(ta_data.get(symbol))
    return _float(current.get("price"), _float(position.get("mark_price"), _float(position.get("avg_price"), _float(position.get("entry")))))


def build_spot_position_advisor(
    *,
    positions: Any,
    ta_data: Optional[Mapping[str, Any]] = None,
    planner_snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None,
    liquidity_payload: Optional[Mapping[str, Any]] = None,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    now_ts = float(now_ts if now_ts is not None else time.time())
    ta_data = ta_data or {}
    planner_snapshots = planner_snapshots or {}
    liquidity = _liquidity_by_symbol(liquidity_payload or {})
    raw_positions = positions if isinstance(positions, dict) else {}
    items = []

    for symbol_raw, raw_position in raw_positions.items():
        position = _dict(raw_position)
        symbol = str(position.get("symbol") or symbol_raw or "").upper()
        planner = _dict(planner_snapshots.get(symbol))
        plan = _dict(planner.get("position_plan"))
        current_price = _current_price(symbol, position, ta_data)
        entry = _float(position.get("avg_price"), _float(position.get("entry")))
        qty = _float(position.get("qty"))
        open_time = _float(position.get("open_time"), _float(position.get("opened_at"), now_ts))
        hold_sec = max(0, int(now_ts - open_time))
        current_pnl_net = _float(position.get("pnl_net"), (current_price - entry) * qty if current_price and entry else 0.0)
        max_pnl_net = _float(position.get("max_pnl_net"), current_pnl_net)
        tp1 = _float(plan.get("tp1"), _float(planner.get("tp1")))
        tp2 = _float(plan.get("tp2"), _float(planner.get("tp2")))
        invalidation = _float(plan.get("invalidation"), _float(planner.get("invalidation")))
        weak_progress_sec = int(_float(plan.get("weak_progress_sec"), 604800))
        advisor_status = str(planner.get("advisor_status") or "")
        liquidity_item = liquidity.get(symbol, {})
        liquidity_bias = str(liquidity_item.get("liquidity_bias") or "")
        liquidity_against = liquidity_bias in {"short", "mild_short", "strong_short"}
        tp1_hit = bool(tp1 > 0 and current_price >= tp1)
        tp2_hit = bool(tp2 > 0 and current_price >= tp2)
        weak_progress = bool(hold_sec > weak_progress_sec and max_pnl_net < 0.10 and current_pnl_net < 0.03)
        setup_died = bool(advisor_status in {"INVALIDATED", "MARKET_AGAINST"} and current_pnl_net <= 0)

        would_action = "HOLD"
        would_reason = "plan_active"
        if invalidation > 0 and current_price < invalidation:
            would_action, would_reason = "WOULD_EXIT_INVALIDATION", "planner_invalidation_breached"
        elif tp2_hit:
            would_action, would_reason = "WOULD_TP2_PARTIAL", "planner_tp2_reached"
        elif tp1_hit:
            would_action, would_reason = "WOULD_TP1_PARTIAL", "planner_tp1_reached"
        elif setup_died:
            would_action, would_reason = "WOULD_TIGHTEN_SETUP_DIED", "planner_setup_died"
        elif weak_progress:
            would_action, would_reason = "WOULD_REVIEW_WEAK_PROGRESS", "weak_progress"
        elif liquidity_against:
            would_action, would_reason = "WOULD_TIGHTEN_LIQUIDITY", "liquidity_shadow_against_buy"

        warnings = []
        if not planner:
            warnings.append("planner_snapshot_missing")
        if liquidity_against:
            warnings.append("liquidity_shadow_against_buy")
        if weak_progress:
            warnings.append("weak_progress")
        if setup_died:
            warnings.append("planner_setup_died")

        items.append({
            "symbol": symbol,
            "market": "SPOT",
            "read_only": True,
            "position_state": "OPENED",
            "would_action": would_action,
            "would_reason": would_reason,
            "current_price": current_price,
            "entry": entry,
            "qty": qty,
            "hold_sec": hold_sec,
            "current_pnl_net": round(current_pnl_net, 8),
            "max_pnl_net": round(max_pnl_net, 8),
            "tp1_hit_shadow": tp1_hit,
            "tp2_hit_shadow": tp2_hit,
            "breakeven_shadow": tp1_hit,
            "trail_shadow": invalidation,
            "weak_progress": weak_progress,
            "setup_died": setup_died,
            "liquidity_against": liquidity_against,
            "planner_snapshot_present": bool(planner),
            "idea_id": planner.get("idea_id"),
            "management_profile": planner.get("management_profile"),
            "warnings": warnings,
        })

    return {
        "ok": True,
        "schema": SCHEMA,
        "read_only": True,
        "items_len": len(items),
        "items": items,
    }


__all__ = ["SCHEMA", "build_spot_position_advisor", "load_latest_planner_snapshots"]
