"""VORTEX v1.8.19k — shadow-only position management engine.

This module must not close positions directly. It only evaluates an open position and
returns a shadow decision that can be recorded and compared against real outcomes.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

SCHEMA = "vortex.position_management_shadow_decision.v1"
SCHEMA_VERSION = "1.8.19k"


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


def evaluate_position_shadow(position: Dict[str, Any], current_price: float = 0.0, now: float | None = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    symbol = str(position.get("symbol") or "").upper()
    side = str(position.get("side") or "").upper()
    setup_type = str(position.get("setup_type") or "UNKNOWN")

    pnl_net = _safe_float(position.get("pnl_net"))
    max_pnl_net = _safe_float(position.get("max_pnl_net"))
    hold_sec = int(_safe_float(position.get("hold_sec")))
    tp0_hit = _safe_bool(position.get("tp0_hit"))
    tp1_hit = _safe_bool(position.get("tp1_hit"))
    breakeven = _safe_bool(position.get("breakeven"))
    entry = _safe_float(position.get("entry"))
    mark_price = _safe_float(position.get("mark_price") or current_price)

    action = "HOLD_SHADOW"
    reason = "no_shadow_management_action"
    confidence = 0
    tags: List[str] = []

    if tp0_hit:
        tags.append("tp0_hit")
    if tp1_hit:
        tags.append("tp1_hit")
    if breakeven:
        tags.append("breakeven")
    if setup_type == "momentum_long":
        tags.append("setup_momentum_long")

    # Rule 1: profit giveback after a useful max profit.
    if max_pnl_net >= 0.08 and pnl_net <= max_pnl_net * 0.40:
        action = "CLOSE_SHADOW"
        reason = "profit_giveback_60pct_after_positive_mfe"
        confidence = 82
        tags.extend(["profit_giveback", "protect_positive_mfe"])

    # Rule 2: after TP0, do not let the trade drift back into negative net.
    elif tp0_hit and pnl_net <= 0.01:
        action = "CLOSE_SHADOW"
        reason = "tp0_small_green_protection"
        confidence = 78
        tags.extend(["tp0_protection", "small_green_protection"])

    # Rule 3: momentum_long should be protected faster once it showed any useful profit.
    elif setup_type == "momentum_long" and hold_sec >= 120 and max_pnl_net >= 0.04 and pnl_net <= 0.0:
        action = "CLOSE_SHADOW"
        reason = "momentum_long_fast_profit_protection"
        confidence = 72
        tags.extend(["momentum_long", "profit_faded"])

    # Rule 4: weak progress timeout. Do not force-close in real mode yet; only record.
    elif hold_sec >= 600 and (not tp0_hit) and max_pnl_net <= 0.03:
        action = "CLOSE_SHADOW"
        reason = "weak_progress_timeout_no_tp0"
        confidence = 65
        tags.extend(["weak_progress", "no_tp0"])

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": now,
        "symbol": symbol,
        "side": side,
        "setup_type": setup_type,
        "action": action,
        "reason": reason,
        "confidence": confidence,
        "tags": sorted(set(tags)),
        "current_price": mark_price,
        "entry": entry,
        "pnl_net": pnl_net,
        "max_pnl_net": max_pnl_net,
        "hold_sec": hold_sec,
        "tp0_hit": tp0_hit,
        "tp1_hit": tp1_hit,
        "breakeven": breakeven,
    }
