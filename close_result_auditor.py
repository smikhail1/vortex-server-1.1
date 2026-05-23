from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA = "vortex.close_result_audit.v1"
SCHEMA_VERSION = "1.8.21c"
DEFAULT_AUDIT_PATH = "_runtime/close_result_audit.jsonl"


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return str(default)
        return str(value)
    except Exception:
        return str(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_bool(value: Any) -> bool:
    return bool(value)


def _get(data: Dict[str, Any], fallback: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if isinstance(data, dict) and data.get(key) is not None:
            return data.get(key)
        if isinstance(fallback, dict) and fallback.get(key) is not None:
            return fallback.get(key)
    return default


def normalize_close_result(
    data: Optional[Dict[str, Any]] = None,
    fallback_pos: Optional[Dict[str, Any]] = None,
    market: str = "",
    source: str = "",
    result: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a stable audit record from a close/event result.

    This is intentionally read/write-only telemetry. It never changes trading state,
    never closes positions, and never edits trades.csv/trades_state.json.
    """
    d = data if isinstance(data, dict) else {}
    fp = fallback_pos if isinstance(fallback_pos, dict) else {}
    res = result if isinstance(result, dict) else {}

    reason = _safe_str(_get(d, fp, "reason", "event", "last_event", default="CLOSE"), "CLOSE").upper()
    symbol = _safe_str(_get(d, fp, "symbol", default="")).upper()
    side = _safe_str(_get(d, fp, "side", default="")).upper()
    market_u = _safe_str(market or _get(d, fp, "market", default=""), "").upper()

    exit_price = _safe_float(_get(d, fp, "exit_price", "price", "current_price", "mark_price", default=0.0))
    entry = _safe_float(_get(d, fp, "entry", "avg_price", default=0.0))
    pnl = _safe_float(_get(d, fp, "pnl", default=0.0))
    pnl_net = _safe_float(_get(d, fp, "pnl_net", default=0.0))
    hold_sec = int(_safe_float(_get(d, fp, "hold_sec", default=0)))

    closed_flag = _safe_bool(d.get("closed"))
    event_only = _safe_bool(d.get("event_only"))

    record = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "source": _safe_str(source, ""),
        "result_code": _safe_str(res.get("code"), ""),
        "was_close_result": bool(closed_flag or (reason in {
            "SL", "TP1", "TP2", "BU", "BE", "TIMEOUT", "PROFIT_TIMEOUT", "FADE",
            "SETUP_DIED", "STALL", "LIQ", "AGGRESSIVE_BE", "SMART_TIMEOUT_TRAIL",
            "WEAK_PROGRESS", "WEAK_PROGRESS_STALE", "MANUAL",
        } and not event_only)),
        "event_only": event_only,
        "closed": closed_flag,
        "symbol": symbol,
        "market": market_u,
        "side": side,
        "reason": reason,
        "entry": entry,
        "exit_price": exit_price,
        "pnl": pnl,
        "pnl_net": pnl_net,
        "hold_sec": hold_sec,
        "setup_type": _safe_str(_get(d, fp, "setup_type", default="")),
        "args_text": _safe_str(_get(d, fp, "args_text", default="")),
        "trade_logger_attempted": bool((extra or {}).get("trade_logger_attempted", False)),
        "risk_register_attempted": bool((extra or {}).get("risk_register_attempted", False)),
    }
    return record


def write_close_audit(record: Dict[str, Any], path: str = DEFAULT_AUDIT_PATH) -> Dict[str, Any]:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def record_close_result(
    data: Optional[Dict[str, Any]] = None,
    fallback_pos: Optional[Dict[str, Any]] = None,
    market: str = "",
    source: str = "",
    result: Optional[Dict[str, Any]] = None,
    audit_path: str = DEFAULT_AUDIT_PATH,
    **extra: Any,
) -> Dict[str, Any]:
    record = normalize_close_result(
        data=data,
        fallback_pos=fallback_pos,
        market=market,
        source=source,
        result=result,
        extra=extra,
    )
    return write_close_audit(record, path=audit_path)


def read_close_audit(path: str = DEFAULT_AUDIT_PATH, limit: int = 100) -> list[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(limit)):]:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except Exception:
            continue
    return rows


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Read VORTEX close-result audit records")
    parser.add_argument("--path", default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    for row in read_close_audit(path=args.path, limit=args.limit):
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
