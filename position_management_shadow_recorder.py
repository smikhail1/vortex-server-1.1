"""Recorder for VORTEX v1.8.19k shadow position-management decisions."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from position_management_engine import evaluate_position_shadow

OUT_PATH = Path("_runtime/position_management_shadow.jsonl")
STATE_PATH = Path("_runtime/position_management_shadow_state.json")
MIN_LOG_INTERVAL_SEC = 60


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"schema": "vortex.position_management_shadow_state.v1", "schema_version": "1.8.19k", "last_logged": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state is not dict")
        data.setdefault("last_logged", {})
        return data
    except Exception:
        return {"schema": "vortex.position_management_shadow_state.v1", "schema_version": "1.8.19k", "last_logged": {}}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def record_position_management_shadow(position: Dict[str, Any], current_price: float = 0.0) -> Dict[str, Any]:
    """Evaluate and record only non-HOLD shadow actions with rate limiting."""
    decision = evaluate_position_shadow(position, current_price=current_price)
    if decision.get("action") == "HOLD_SHADOW":
        return decision

    now = time.time()
    key = f"{decision.get('symbol')}:{decision.get('side')}:{decision.get('setup_type')}:{decision.get('reason')}"
    state = _load_state()
    last_logged = state.setdefault("last_logged", {})
    last_ts = float(last_logged.get(key) or 0.0)

    if now - last_ts >= MIN_LOG_INTERVAL_SEC:
        _append_jsonl(OUT_PATH, decision)
        last_logged[key] = now
        _save_state(state)

    return decision
