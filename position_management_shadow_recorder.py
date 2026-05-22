"""Recorder for VORTEX v1.8.19k-r2 shadow position-management decisions.

Shadow telemetry must be visible even when the engine decides HOLD_SHADOW.
This module still does not close or modify positions. It only records sampled
shadow decisions for analytics.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from position_management_engine import evaluate_position_shadow

OUT_PATH = Path("_runtime/position_management_shadow.jsonl")
STATE_PATH = Path("_runtime/position_management_shadow_state.json")
SCHEMA = "vortex.position_management_shadow_state.v1"
SCHEMA_VERSION = "1.8.19k-r2"

# Non-HOLD decisions are important and should be logged more frequently.
ACTION_LOG_INTERVAL_SEC = 60

# HOLD decisions are a heartbeat: enough to prove the module is alive without
# flooding runtime files.
HOLD_LOG_INTERVAL_SEC = 180


def _load_state() -> Dict[str, Any]:
    fallback = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "last_logged": {},
        "counters": {
            "total_seen": 0,
            "total_written": 0,
            "hold_seen": 0,
            "hold_written": 0,
            "action_seen": 0,
            "action_written": 0,
        },
    }
    if not STATE_PATH.exists():
        return fallback
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state is not dict")
        data.setdefault("schema", SCHEMA)
        data["schema_version"] = SCHEMA_VERSION
        data.setdefault("last_logged", {})
        counters = data.setdefault("counters", {})
        for key, value in fallback["counters"].items():
            counters.setdefault(key, value)
        return data
    except Exception:
        return fallback


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _safe_counter_inc(state: Dict[str, Any], key: str, amount: int = 1) -> None:
    counters = state.setdefault("counters", {})
    try:
        counters[key] = int(counters.get(key) or 0) + amount
    except Exception:
        counters[key] = amount


def _rate_limit_key(decision: Dict[str, Any]) -> str:
    action = str(decision.get("action") or "UNKNOWN")
    symbol = str(decision.get("symbol") or "UNKNOWN")
    side = str(decision.get("side") or "UNKNOWN")
    setup_type = str(decision.get("setup_type") or "UNKNOWN")
    reason = str(decision.get("reason") or "UNKNOWN")

    # For HOLD heartbeat, reason is usually constant and not analytically
    # important. Keep key stable per open setup.
    if action == "HOLD_SHADOW":
        return f"{symbol}:{side}:{setup_type}:HOLD_SHADOW"
    return f"{symbol}:{side}:{setup_type}:{action}:{reason}"


def record_position_management_shadow(position: Dict[str, Any], current_price: float = 0.0) -> Dict[str, Any]:
    """Evaluate and record sampled shadow position-management decisions.

    Real trading behavior is unchanged. This function only writes analytics rows.
    - HOLD_SHADOW is written as a heartbeat every HOLD_LOG_INTERVAL_SEC.
    - CLOSE_SHADOW and other non-HOLD actions are written every ACTION_LOG_INTERVAL_SEC.
    """
    decision = evaluate_position_shadow(position, current_price=current_price)
    now = time.time()
    action = str(decision.get("action") or "UNKNOWN")
    is_hold = action == "HOLD_SHADOW"
    interval = HOLD_LOG_INTERVAL_SEC if is_hold else ACTION_LOG_INTERVAL_SEC

    state = _load_state()
    _safe_counter_inc(state, "total_seen")
    _safe_counter_inc(state, "hold_seen" if is_hold else "action_seen")

    last_logged = state.setdefault("last_logged", {})
    key = _rate_limit_key(decision)
    last_ts = float(last_logged.get(key) or 0.0)

    if now - last_ts >= interval:
        row = dict(decision)
        row["record_schema"] = "vortex.position_management_shadow_record.v1"
        row["record_schema_version"] = SCHEMA_VERSION
        row["recorded_at"] = now
        row["rate_limit_key"] = key
        row["heartbeat"] = bool(is_hold)
        row["log_interval_sec"] = interval

        _append_jsonl(OUT_PATH, row)
        last_logged[key] = now
        _safe_counter_inc(state, "total_written")
        _safe_counter_inc(state, "hold_written" if is_hold else "action_written")

    state["last_seen_at"] = now
    _save_state(state)
    return decision
