import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA = "vortex.persistent_state_guard.v1"
SCHEMA_VERSION = "1.8.21f-a"


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _pos_get(pos: Any, key: str, default: Any = None) -> Any:
    if isinstance(pos, dict):
        return pos.get(key, default)
    try:
        return getattr(pos, key)
    except Exception:
        return default


def load_open_positions_from_state(state_path: str = "trades_state.json") -> Dict[str, Dict[str, Any]]:
    path = Path(state_path)
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}

    open_map = data.get("open") or {}
    if not isinstance(open_map, dict):
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for raw_key, raw_pos in open_map.items():
        if not isinstance(raw_pos, dict):
            continue

        market = _safe_str(raw_pos.get("market"), "").upper()
        symbol = _safe_str(raw_pos.get("symbol"), "").upper()

        if not symbol:
            symbol = _safe_str(raw_key).split("::", 1)[0].upper()

        if not market and "::" in _safe_str(raw_key):
            market = _safe_str(raw_key).split("::", 1)[1].upper()

        pos = dict(raw_pos)
        pos["raw_key"] = _safe_str(raw_key)
        pos["symbol"] = symbol
        pos["market"] = market
        out[_safe_str(raw_key)] = pos

    return out


def get_state_open_futures(state_path: str = "trades_state.json") -> List[Dict[str, Any]]:
    open_map = load_open_positions_from_state(state_path)
    result: List[Dict[str, Any]] = []

    for raw_key, pos in open_map.items():
        market = _safe_str(pos.get("market"), "").upper()
        if market == "FUT" or raw_key.upper().endswith("::FUT"):
            item = dict(pos)
            item["raw_key"] = raw_key
            item["symbol"] = _safe_str(item.get("symbol"), "").upper()
            item["side"] = _safe_str(item.get("side"), "").upper()
            item["entry"] = _safe_float(item.get("entry"), 0.0)
            item["open_time"] = _safe_float(item.get("open_time"), 0.0)
            result.append(item)

    return result


def get_runtime_open_futures(router: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    if router is None:
        return result

    raw = {}

    try:
        if hasattr(router, "get_all_futures_positions"):
            raw = router.get_all_futures_positions() or {}
    except Exception:
        raw = {}

    if not raw:
        try:
            if hasattr(router, "get_futures_position"):
                pos = router.get_futures_position()
                if pos is not None:
                    sym = _safe_str(_pos_get(pos, "symbol", "FUT"), "FUT").upper()
                    raw = {sym: pos}
        except Exception:
            raw = {}

    if isinstance(raw, dict):
        for key, pos in raw.items():
            if pos is None:
                continue
            symbol = _safe_str(_pos_get(pos, "symbol", key), key).upper()
            result.append({
                "symbol": symbol,
                "side": _safe_str(_pos_get(pos, "side", ""), "").upper(),
                "entry": _safe_float(_pos_get(pos, "entry", 0.0), 0.0),
                "open_time": _safe_float(_pos_get(pos, "open_time", 0.0), 0.0),
                "raw_key": _safe_str(key),
            })

    return result


def evaluate_futures_pre_open_guard(
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    router: Any = None,
    state_path: str = "trades_state.json",
    fail_closed: bool = True,
) -> Dict[str, Any]:
    requested_symbol = _safe_str(symbol, "").upper()
    requested_side = _safe_str(side, "").upper()

    try:
        state_fut = get_state_open_futures(state_path)
    except Exception as exc:
        return {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "ts": time.time(),
            "allow": not fail_closed,
            "code": "STATE_GUARD_READ_ERROR",
            "reason": f"state_guard_read_error:{exc}",
            "requested_symbol": requested_symbol,
            "requested_side": requested_side,
            "state_path": state_path,
            "state_fut_count": None,
            "runtime_fut_count": None,
            "state_fut": [],
            "runtime_fut": [],
        }

    try:
        runtime_fut = get_runtime_open_futures(router)
    except Exception:
        runtime_fut = []

    state_fut_count = len(state_fut)
    runtime_fut_count = len(runtime_fut)

    if state_fut_count > 0:
        if runtime_fut_count <= 0:
            code = "STATE_RUNTIME_MISMATCH"
            reason = "persistent_state_has_fut_open_but_runtime_has_none"
        else:
            code = "EXISTING_FUTURES_STATE"
            reason = "persistent_state_has_fut_open"

        return {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "ts": time.time(),
            "allow": False,
            "code": code,
            "reason": reason,
            "requested_symbol": requested_symbol,
            "requested_side": requested_side,
            "state_path": state_path,
            "state_fut_count": state_fut_count,
            "runtime_fut_count": runtime_fut_count,
            "state_fut": state_fut,
            "runtime_fut": runtime_fut,
        }

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "allow": True,
        "code": "OK",
        "reason": "no_persistent_futures_open",
        "requested_symbol": requested_symbol,
        "requested_side": requested_side,
        "state_path": state_path,
        "state_fut_count": state_fut_count,
        "runtime_fut_count": runtime_fut_count,
        "state_fut": state_fut,
        "runtime_fut": runtime_fut,
    }
