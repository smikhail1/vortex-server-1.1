import json
import time
from pathlib import Path
from typing import Any, Dict, Tuple


SCHEMA = "vortex.snapshot_guard.v1"
SCHEMA_VERSION = "1.8.21k-d"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _summary(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    s = snapshot.get("summary") or {}
    return s if isinstance(s, dict) else {}


def _extract_counts(snapshot: Dict[str, Any]) -> Tuple[int, int, int]:
    s = _summary(snapshot)

    symbols_count = _safe_int(
        s.get("symbols_count", s.get("symbols_total", len(snapshot.get("symbols") or []))),
        0,
    )

    ta_symbols_count = _safe_int(s.get("ta_symbols_count"), -1)

    if ta_symbols_count < 0:
        strategy_summary = s.get("strategy_summary") or {}
        setup_summary = s.get("setup_summary") or {}
        ta_symbols_count = max(
            _safe_int(strategy_summary.get("ta_symbols_count"), 0),
            _safe_int(setup_summary.get("ta_symbols_count"), 0),
        )

    analyzed_count = _safe_int(s.get("analyzed_count"), -1)
    if analyzed_count < 0:
        strategy_summary = s.get("strategy_summary") or {}
        analyzed_count = _safe_int(strategy_summary.get("analyzed_count"), symbols_count)

    return symbols_count, ta_symbols_count, analyzed_count


def is_valid_latest_snapshot(snapshot: Dict[str, Any], *, min_ta_symbols: int = 1, min_symbols: int = 1) -> bool:
    symbols_count, ta_symbols_count, analyzed_count = _extract_counts(snapshot)
    return symbols_count >= min_symbols and ta_symbols_count >= min_ta_symbols and analyzed_count >= min_symbols


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        if not Path(path).exists():
            return {}
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def should_write_latest_snapshot(
    latest_path: Path,
    snapshot: Dict[str, Any],
    *,
    min_ta_symbols: int = 1,
    min_symbols: int = 1,
) -> Dict[str, Any]:
    latest_path = Path(latest_path)
    new_valid = is_valid_latest_snapshot(snapshot, min_ta_symbols=min_ta_symbols, min_symbols=min_symbols)

    old = _load_json(latest_path)
    old_valid = is_valid_latest_snapshot(old, min_ta_symbols=min_ta_symbols, min_symbols=min_symbols)

    new_symbols, new_ta, new_analyzed = _extract_counts(snapshot)
    old_symbols, old_ta, old_analyzed = _extract_counts(old)

    suppress = bool((not new_valid) and old_valid)

    if suppress:
        action = "SKIP_LATEST_KEEP_PREVIOUS"
        reason = "new snapshot has no usable TA while previous latest is valid"
    elif new_valid:
        action = "WRITE_LATEST_VALID"
        reason = "new snapshot has usable TA"
    else:
        action = "WRITE_LATEST_NO_VALID_PREVIOUS"
        reason = "new snapshot is not valid, but no valid previous latest exists"

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "write_latest": not suppress,
        "action": action,
        "reason": reason,
        "new_valid": new_valid,
        "old_valid": old_valid,
        "new_counts": {
            "symbols_count": new_symbols,
            "ta_symbols_count": new_ta,
            "analyzed_count": new_analyzed,
        },
        "old_counts": {
            "symbols_count": old_symbols,
            "ta_symbols_count": old_ta,
            "analyzed_count": old_analyzed,
        },
    }
