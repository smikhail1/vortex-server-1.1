"""VORTEX v1.8.19l-1 — real weak-progress position guard.

This module converts the proven shadow signal `weak_progress_timeout_no_tp0`
into a real paper-flow close decision for FUT positions only.

Rule is intentionally conservative:
- position must be old enough;
- TP0 must not be hit;
- max positive net PnL must be tiny/absent;
- current net PnL must not be meaningfully positive.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

SCHEMA = "vortex.position_management_live_guard.v1"
SCHEMA_VERSION = "1.8.19l-1"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _risk_value(name: str, default: Any) -> Any:
    try:
        from config import CONFIG  # type: ignore
        return getattr(CONFIG.risk, name, default)
    except Exception:
        return default


def _runtime_position_fallback(symbol: str, market: str = "FUT") -> Dict[str, Any]:
    """Best-effort fallback for stale/incomplete in-memory position dicts."""
    try:
        p = Path("trades_state.json")
        if not p.exists():
            return {}
        state = json.loads(p.read_text(encoding="utf-8"))
        open_map = state.get("open") or {}
        if not isinstance(open_map, dict):
            return {}
        key = f"{symbol.upper()}::{market.upper()}"
        pos = open_map.get(key)
        return pos if isinstance(pos, dict) else {}
    except Exception:
        return {}


def _first_non_empty(position: Dict[str, Any], fallback: Dict[str, Any], key: str, default: Any = None) -> Any:
    v = position.get(key)
    if v not in (None, ""):
        return v
    return fallback.get(key, default)


def evaluate_real_weak_progress(position: Dict[str, Any], current_price: float = 0.0, now: float | None = None) -> Dict[str, Any]:
    now = time.time() if now is None else now

    enabled = bool(_risk_value("position_weak_progress_enabled", True))
    min_hold_sec = int(_risk_value("position_weak_progress_min_hold_sec", 900))
    max_mfe_net = float(_risk_value("position_weak_progress_max_mfe_net", 0.03))
    max_current_pnl_net = float(_risk_value("position_weak_progress_max_current_pnl_net", 0.01))
    close_reason = str(_risk_value("position_weak_progress_close_reason", "WEAK_PROGRESS"))

    symbol = str(position.get("symbol") or "").upper()
    side = str(position.get("side") or "").upper()
    setup_type = str(position.get("setup_type") or "UNKNOWN")

    fallback = _runtime_position_fallback(symbol, "FUT") if symbol else {}

    source_hold_sec = _safe_float(_first_non_empty(position, fallback, "hold_sec", 0.0))
    open_time = _safe_float(_first_non_empty(position, fallback, "open_time", 0.0))
    calculated_hold_sec = int(max(0.0, now - open_time)) if open_time > 0 else 0
    hold_sec = int(max(source_hold_sec, calculated_hold_sec))

    pnl_net = _safe_float(_first_non_empty(position, fallback, "pnl_net", 0.0))
    max_pnl_net = _safe_float(_first_non_empty(position, fallback, "max_pnl_net", 0.0))
    tp0_hit = _safe_bool(_first_non_empty(position, fallback, "tp0_hit", False))
    tp1_hit = _safe_bool(_first_non_empty(position, fallback, "tp1_hit", False))
    entry = _safe_float(_first_non_empty(position, fallback, "entry", 0.0))
    mark_price = _safe_float(position.get("mark_price") or current_price or fallback.get("current_price") or fallback.get("mark_price"), 0.0)

    allow_close = (
        enabled
        and hold_sec >= min_hold_sec
        and not tp0_hit
        and max_pnl_net <= max_mfe_net
        and pnl_net <= max_current_pnl_net
    )

    action = "CLOSE" if allow_close else "HOLD"
    reason = close_reason if allow_close else "no_live_management_action"

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": now,
        "symbol": symbol,
        "side": side,
        "setup_type": setup_type,
        "action": action,
        "reason": reason,
        "shadow_reason": "weak_progress_timeout_no_tp0" if allow_close else "",
        "confidence": 70 if allow_close else 0,
        "enabled": enabled,
        "current_price": mark_price,
        "entry": entry,
        "pnl_net": pnl_net,
        "max_pnl_net": max_pnl_net,
        "hold_sec": hold_sec,
        "source_hold_sec": int(source_hold_sec),
        "calculated_hold_sec": calculated_hold_sec,
        "open_time": open_time,
        "runtime_state_fallback_used": bool(fallback),
        "tp0_hit": tp0_hit,
        "tp1_hit": tp1_hit,
        "thresholds": {
            "min_hold_sec": min_hold_sec,
            "max_mfe_net": max_mfe_net,
            "max_current_pnl_net": max_current_pnl_net,
        },
        "tags": ["weak_progress", "no_tp0", "real_close_guard"] if allow_close else [],
    }
