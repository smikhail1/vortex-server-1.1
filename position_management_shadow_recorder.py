"""Recorder for VORTEX v1.8.19k-r3 shadow position-management decisions.

Shadow telemetry must be visible even when the engine decides HOLD_SHADOW.
This module still does not close or modify positions. It only records sampled
shadow decisions for analytics.

v1.8.19k-r3 fixes hold-time propagation:
- some runtime position dictionaries reach the recorder with hold_sec=0;
- the dashboard/trades_state can still contain a valid open_time;
- shadow rules such as weak_progress_timeout require real hold_sec.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from position_management_engine import evaluate_position_shadow

OUT_PATH = Path("_runtime/position_management_shadow.jsonl")
STATE_PATH = Path("_runtime/position_management_shadow_state.json")
TRADES_STATE_PATH = Path("trades_state.json")
SCHEMA = "vortex.position_management_shadow_state.v1"
SCHEMA_VERSION = "1.8.19k-r3"

# Non-HOLD decisions are important and should be logged more frequently.
ACTION_LOG_INTERVAL_SEC = 60

# HOLD decisions are a heartbeat: enough to prove the module is alive without
# flooding runtime files.
HOLD_LOG_INTERVAL_SEC = 180


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


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
            "hold_sec_corrected": 0,
            "runtime_state_fallback_used": 0,
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


def _load_runtime_open_position(symbol: str, market: str = "FUT") -> Dict[str, Any]:
    """Best-effort fallback lookup in trades_state.json.

    This is intentionally read-only and used only for analytics enrichment.
    """
    if not symbol or not TRADES_STATE_PATH.exists():
        return {}
    try:
        state = json.loads(TRADES_STATE_PATH.read_text(encoding="utf-8"))
        open_map = state.get("open") or {}
        if not isinstance(open_map, dict):
            return {}
        symbol_u = str(symbol).upper()
        market_u = str(market or "FUT").upper()
        preferred_keys = [f"{symbol_u}::{market_u}", f"{symbol_u}::FUTURES"]
        for key in preferred_keys:
            pos = open_map.get(key)
            if isinstance(pos, dict):
                return pos
        for _key, pos in open_map.items():
            if not isinstance(pos, dict):
                continue
            if str(pos.get("symbol") or "").upper() != symbol_u:
                continue
            pos_market = str(pos.get("market") or "").upper()
            if market_u in {pos_market, "FUT"} or pos_market in {"FUT", "FUTURES"}:
                return pos
    except Exception:
        return {}
    return {}


def _normalize_position(position: Dict[str, Any], now: float) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return position copy with reliable hold_sec plus metadata for records."""
    pos = dict(position or {})
    symbol = str(pos.get("symbol") or "").upper()
    market = str(pos.get("market") or "FUT").upper() or "FUT"

    runtime_pos = _load_runtime_open_position(symbol, market)
    fallback_used = False

    # Fill missing basics from runtime state, but do not overwrite live values
    # unless the live value is empty/zero and the runtime value is meaningful.
    for key in ("open_time", "hold_sec", "setup_type", "entry", "pnl_net", "max_pnl_net", "tp0_hit", "tp1_hit", "breakeven", "side", "market"):
        current = pos.get(key)
        runtime_value = runtime_pos.get(key) if isinstance(runtime_pos, dict) else None
        if runtime_value in (None, ""):
            continue
        if current in (None, ""):
            pos[key] = runtime_value
            fallback_used = True
        elif key == "hold_sec" and _safe_float(current) <= 0 and _safe_float(runtime_value) > 0:
            pos[key] = runtime_value
            fallback_used = True
        elif key in {"setup_type", "side", "market"} and not str(current).strip():
            pos[key] = runtime_value
            fallback_used = True

    source_hold_sec = _safe_float(pos.get("hold_sec"), 0.0)
    open_time = _safe_float(pos.get("open_time"), 0.0)
    calculated_hold_sec = int(max(0.0, now - open_time)) if open_time > 0 else 0

    effective_hold_sec = int(source_hold_sec)
    hold_sec_source = "position_hold_sec"

    # Critical fix: if the live position says hold_sec=0 but open_time says the
    # trade is old, use calculated value so shadow timeout rules can fire.
    if calculated_hold_sec > effective_hold_sec:
        effective_hold_sec = calculated_hold_sec
        hold_sec_source = "calculated_from_open_time"

    pos["hold_sec"] = effective_hold_sec

    meta = {
        "open_time": open_time,
        "source_hold_sec": int(source_hold_sec),
        "calculated_hold_sec": int(calculated_hold_sec),
        "effective_hold_sec": int(effective_hold_sec),
        "hold_sec_source": hold_sec_source,
        "runtime_state_fallback_used": bool(fallback_used),
    }
    return pos, meta


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
    now = time.time()
    normalized_position, meta = _normalize_position(position or {}, now=now)

    decision = evaluate_position_shadow(normalized_position, current_price=current_price, now=now)
    action = str(decision.get("action") or "UNKNOWN")
    is_hold = action == "HOLD_SHADOW"
    interval = HOLD_LOG_INTERVAL_SEC if is_hold else ACTION_LOG_INTERVAL_SEC

    state = _load_state()
    _safe_counter_inc(state, "total_seen")
    _safe_counter_inc(state, "hold_seen" if is_hold else "action_seen")
    if meta.get("hold_sec_source") == "calculated_from_open_time":
        _safe_counter_inc(state, "hold_sec_corrected")
    if meta.get("runtime_state_fallback_used"):
        _safe_counter_inc(state, "runtime_state_fallback_used")

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
        row.update(meta)

        _append_jsonl(OUT_PATH, row)
        last_logged[key] = now
        _safe_counter_inc(state, "total_written")
        _safe_counter_inc(state, "hold_written" if is_hold else "action_written")

    state["last_seen_at"] = now
    state["last_effective_hold_sec"] = int(meta.get("effective_hold_sec") or 0)
    state["last_hold_sec_source"] = str(meta.get("hold_sec_source") or "")
    _save_state(state)
    return decision
