import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


SCHEMA = "vortex.entry_candidate_journal.v1"
SCHEMA_VERSION = "1.8.21j-a-r2"

DEFAULT_OUT = "_runtime/entry_candidates.jsonl"
DEDUP_STATE_PATH = Path("_runtime/entry_candidate_dedup_state.json")
DEDUP_SUMMARY_PATH = Path("_runtime/entry_candidate_dedup_summary.json")
DEFAULT_DEDUP_WINDOW_SEC = int(os.getenv("VORTEX_ENTRY_CANDIDATE_DEDUP_SEC", "300"))


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _extract_arg(args: Tuple[Any, ...], kwargs: Dict[str, Any], name: str, index: Optional[int] = None, default: Any = None) -> Any:
    if name in kwargs:
        return kwargs.get(name)
    if index is not None and index < len(args):
        return args[index]
    return default


def _extract_args_text(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
    direct = kwargs.get("args_text")
    if direct:
        return _safe_str(direct)

    strings = [_safe_str(x) for x in args if isinstance(x, str)]
    ea_like = [s for s in strings if "EA:" in s or "score=" in s or "momentum" in s or "ADX:" in s]
    if ea_like:
        return max(ea_like, key=len)
    return ""


def parse_ea(args_text: str) -> Dict[str, Any]:
    text = _safe_str(args_text)
    m = re.search(r"\bEA:([A-D])\/(\d+)\s+([A-Z_]+)", text)
    if not m:
        return {
            "present": False,
            "grade": "",
            "score": 0,
            "label": "NO_EA",
            "raw": "",
        }

    return {
        "present": True,
        "grade": m.group(1).upper(),
        "score": int(m.group(2)),
        "label": m.group(3).upper(),
        "raw": m.group(0),
    }


def build_candidate_record(
    *,
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
    policy: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    final_action: str = "",
) -> Dict[str, Any]:
    kwargs = dict(kwargs or {})
    policy = dict(policy or {})
    result = dict(result or {})

    symbol = _safe_str(_extract_arg(args, kwargs, "symbol", 0, "")).upper()
    side = _safe_str(_extract_arg(args, kwargs, "side", 1, "")).upper()
    setup_type = _safe_str(_extract_arg(args, kwargs, "setup_type", None, "")).strip()
    args_text = _extract_args_text(args, kwargs)
    ea = parse_ea(args_text)

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "symbol": symbol,
        "side": side,
        "setup_type": setup_type,
        "args_text": args_text,
        "ea": ea,
        "policy_allow": policy.get("allow"),
        "policy_code": policy.get("code"),
        "policy_reason": policy.get("reason"),
        "final_action": final_action,
        "router_result_code": result.get("code"),
        "router_result_msg": result.get("msg"),
    }


def _dedup_key(record: Dict[str, Any]) -> str:
    ea = record.get("ea") or {}
    return "|".join([
        _safe_str(record.get("symbol")).upper(),
        _safe_str(record.get("side")).upper(),
        _safe_str(record.get("setup_type")),
        _safe_str(record.get("policy_code") or "NONE"),
        _safe_str(ea.get("grade") or "NO_EA"),
        str(_safe_int(ea.get("score"), 0)),
        _safe_str(ea.get("label") or "NO_LABEL"),
        _safe_str(record.get("final_action")),
    ])


def _initial_state() -> Dict[str, Any]:
    return {
        "schema": "vortex.entry_candidate_dedup_state.v1",
        "schema_version": SCHEMA_VERSION,
        "dedup_window_sec": DEFAULT_DEDUP_WINDOW_SEC,
        "total_seen": 0,
        "total_written": 0,
        "total_suppressed": 0,
        "keys": {},
    }


def _load_state(path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(path or DEDUP_STATE_PATH)
    if not path.exists():
        return _initial_state()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _initial_state()
        data.setdefault("schema", "vortex.entry_candidate_dedup_state.v1")
        data["schema_version"] = SCHEMA_VERSION
        data.setdefault("dedup_window_sec", DEFAULT_DEDUP_WINDOW_SEC)
        data.setdefault("total_seen", 0)
        data.setdefault("total_written", 0)
        data.setdefault("total_suppressed", 0)
        data.setdefault("keys", {})
        return data
    except Exception:
        return _initial_state()


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _top_counter(items: Dict[str, int], limit: int = 15) -> Dict[str, int]:
    return dict(sorted(items.items(), key=lambda kv: kv[1], reverse=True)[:limit])


def _build_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    by_policy: Dict[str, int] = {}
    by_symbol: Dict[str, int] = {}
    by_setup: Dict[str, int] = {}
    by_ea_grade: Dict[str, int] = {}

    for item in (state.get("keys") or {}).values():
        rec = item.get("last_record") or {}
        ea = rec.get("ea") or {}
        seen = int(item.get("seen_count") or 0)

        policy = _safe_str(rec.get("policy_code") or "NONE")
        symbol = _safe_str(rec.get("symbol") or "UNKNOWN")
        setup = _safe_str(rec.get("setup_type") or "UNKNOWN")
        grade = _safe_str(ea.get("grade") or "NO_EA")

        by_policy[policy] = by_policy.get(policy, 0) + seen
        by_symbol[symbol] = by_symbol.get(symbol, 0) + seen
        by_setup[setup] = by_setup.get(setup, 0) + seen
        by_ea_grade[grade] = by_ea_grade.get(grade, 0) + seen

    return {
        "schema": "vortex.entry_candidate_dedup_summary.v1",
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "dedup_window_sec": state.get("dedup_window_sec", DEFAULT_DEDUP_WINDOW_SEC),
        "total_seen": state.get("total_seen", 0),
        "total_written": state.get("total_written", 0),
        "total_suppressed": state.get("total_suppressed", 0),
        "unique_keys": len(state.get("keys") or {}),
        "top_policy": _top_counter(by_policy),
        "top_symbol": _top_counter(by_symbol),
        "top_setup": _top_counter(by_setup),
        "top_ea_grade": _top_counter(by_ea_grade),
    }


def _write_summary(state: Dict[str, Any], summary_path: Optional[Path] = None) -> None:
    _write_json_atomic(Path(summary_path or DEDUP_SUMMARY_PATH), _build_summary(state))


def should_write_candidate(
    record: Dict[str, Any],
    *,
    now: Optional[float] = None,
    window_sec: int = DEFAULT_DEDUP_WINDOW_SEC,
    state_path: Optional[Path] = None,
    summary_path: Optional[Path] = None,
) -> Tuple[bool, Dict[str, Any], str]:
    now = float(now if now is not None else time.time())
    state_path = Path(state_path or DEDUP_STATE_PATH)
    summary_path = Path(summary_path or DEDUP_SUMMARY_PATH)

    state = _load_state(state_path)
    state["dedup_window_sec"] = int(window_sec)
    state["total_seen"] = int(state.get("total_seen") or 0) + 1

    key = _dedup_key(record)
    keys = state.setdefault("keys", {})
    item = keys.get(key)

    if not item:
        keys[key] = {
            "first_ts": now,
            "last_ts": now,
            "last_written_ts": now,
            "seen_count": 1,
            "written_count": 1,
            "suppressed_count": 0,
            "last_record": record,
        }
        state["total_written"] = int(state.get("total_written") or 0) + 1
        _write_json_atomic(state_path, state)
        _write_summary(state, summary_path)
        return True, state, key

    item["last_ts"] = now
    item["seen_count"] = int(item.get("seen_count") or 0) + 1
    item["last_record"] = record

    last_written_ts = float(item.get("last_written_ts") or 0.0)
    should_write = (now - last_written_ts) >= int(window_sec)

    if should_write:
        item["last_written_ts"] = now
        item["written_count"] = int(item.get("written_count") or 0) + 1
        state["total_written"] = int(state.get("total_written") or 0) + 1
    else:
        item["suppressed_count"] = int(item.get("suppressed_count") or 0) + 1
        state["total_suppressed"] = int(state.get("total_suppressed") or 0) + 1

    _write_json_atomic(state_path, state)
    _write_summary(state, summary_path)
    return should_write, state, key


def write_entry_candidate(record: Dict[str, Any], out_path: str = DEFAULT_OUT) -> None:
    out_path = Path(out_path)
    state_path = out_path.parent / "entry_candidate_dedup_state.json"
    summary_path = out_path.parent / "entry_candidate_dedup_summary.json"

    should_write, state, key = should_write_candidate(
        record,
        state_path=state_path,
        summary_path=summary_path,
    )
    if not should_write:
        return

    item = (state.get("keys") or {}).get(key) or {}
    record = dict(record)
    record["dedup"] = {
        "key": key,
        "window_sec": state.get("dedup_window_sec", DEFAULT_DEDUP_WINDOW_SEC),
        "seen_count": item.get("seen_count", 1),
        "written_count": item.get("written_count", 1),
        "suppressed_count": item.get("suppressed_count", 0),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def log_entry_candidate(
    *,
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
    policy: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    final_action: str = "",
    out_path: str = DEFAULT_OUT,
) -> Dict[str, Any]:
    record = build_candidate_record(
        args=args,
        kwargs=kwargs,
        policy=policy,
        result=result,
        final_action=final_action,
    )
    write_entry_candidate(record, out_path=out_path)
    return record
