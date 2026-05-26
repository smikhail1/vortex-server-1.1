import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA = "vortex.ea_verdict_bridge.v1"
SCHEMA_VERSION = "1.8.21l-a-r2"

DEDUP_STATE_PATH = Path("_runtime/entry_candidate_dedup_state.json")
ENTRY_CANDIDATES_PATH = Path("_runtime/entry_candidates.jsonl")
LATEST_PATH = Path("_runtime/ea_verdict_bridge_latest.json")


def _safe_str(value: Any, default: str = "") -> str:
    try:
        return default if value is None else str(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(default) if value is None else float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(default) if value is None else int(float(value))
    except Exception:
        return int(default)


def _safe_upper(value: Any) -> str:
    return _safe_str(value).strip().upper()


def verdict_key(symbol: str, side: str = "", setup_type: str = "") -> str:
    return "|".join([_safe_upper(symbol), _safe_upper(side), _safe_str(setup_type).strip()])


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        if not Path(path).exists():
            return {}
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _iter_jsonl_tail(path: Path, max_lines: int = 5000) -> List[Dict[str, Any]]:
    try:
        if not Path(path).exists():
            return []
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        out: List[Dict[str, Any]] = []
        for line in lines[-max_lines:]:
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    out.append(item)
            except Exception:
                continue
        return out
    except Exception:
        return []


def _record_key(record: Dict[str, Any]) -> str:
    return verdict_key(record.get("symbol"), record.get("side"), record.get("setup_type"))


def _compact_record(record: Dict[str, Any], *, source: str, seen_count: int = 0, suppressed_count: int = 0, written_count: int = 0) -> Dict[str, Any]:
    ea = record.get("ea") or {}
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "ts": _safe_float(record.get("ts"), 0.0),
        "symbol": _safe_upper(record.get("symbol")),
        "side": _safe_upper(record.get("side")),
        "setup_type": _safe_str(record.get("setup_type")),
        "args_text": _safe_str(record.get("args_text")),
        "ea": {
            "present": bool(ea.get("present")),
            "grade": _safe_upper(ea.get("grade")),
            "score": _safe_int(ea.get("score"), 0),
            "label": _safe_upper(ea.get("label")),
            "raw": _safe_str(ea.get("raw")),
        },
        "policy": {
            "allow": record.get("policy_allow"),
            "code": record.get("policy_code"),
            "reason": record.get("policy_reason"),
        },
        "router": {
            "final_action": record.get("final_action"),
            "result_code": record.get("router_result_code"),
            "result_msg": record.get("router_result_msg"),
        },
        "dedup": {
            "seen_count": int(seen_count or 0),
            "suppressed_count": int(suppressed_count or 0),
            "written_count": int(written_count or 0),
        },
    }


def _prefer_record(new: Dict[str, Any], old: Optional[Dict[str, Any]]) -> bool:
    if old is None:
        return True
    new_ts = _safe_float(new.get("ts"), 0.0)
    old_ts = _safe_float(old.get("ts"), 0.0)
    if new_ts != old_ts:
        return new_ts > old_ts
    new_ea = new.get("ea") or {}
    old_ea = old.get("ea") or {}
    if bool(new_ea.get("present")) != bool(old_ea.get("present")):
        return bool(new_ea.get("present"))
    return _safe_int((new.get("dedup") or {}).get("seen_count"), 0) > _safe_int((old.get("dedup") or {}).get("seen_count"), 0)


def build_ea_verdict_index(*, dedup_state_path: Path = DEDUP_STATE_PATH, entry_candidates_path: Path = ENTRY_CANDIDATES_PATH, jsonl_tail_lines: int = 5000) -> Dict[str, Any]:
    index: Dict[str, Dict[str, Any]] = {}
    source_counts: Dict[str, int] = {}

    state = _load_json(Path(dedup_state_path))
    keys = state.get("keys") or {}
    if isinstance(keys, dict):
        for item in keys.values():
            if not isinstance(item, dict):
                continue
            record = item.get("last_record") or {}
            if not isinstance(record, dict):
                continue
            compact = _compact_record(
                record,
                source="dedup_state",
                seen_count=_safe_int(item.get("seen_count"), 0),
                suppressed_count=_safe_int(item.get("suppressed_count"), 0),
                written_count=_safe_int(item.get("written_count"), 0),
            )
            key = _record_key(compact)
            if not key.strip("|"):
                continue
            if _prefer_record(compact, index.get(key)):
                index[key] = compact
                source_counts["dedup_state"] = source_counts.get("dedup_state", 0) + 1

    for record in _iter_jsonl_tail(Path(entry_candidates_path), max_lines=jsonl_tail_lines):
        compact = _compact_record(record, source="entry_candidates_jsonl")
        key = _record_key(compact)
        if not key.strip("|"):
            continue
        if _prefer_record(compact, index.get(key)):
            index[key] = compact
            source_counts["entry_candidates_jsonl"] = source_counts.get("entry_candidates_jsonl", 0) + 1

    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for item in index.values():
        sym = _safe_upper(item.get("symbol"))
        if sym:
            by_symbol.setdefault(sym, []).append(item)

    for items in by_symbol.values():
        items.sort(key=lambda x: (_safe_float(x.get("ts"), 0.0), _safe_int((x.get("ea") or {}).get("score"), 0)), reverse=True)

    summary: Dict[str, Any] = {
        "symbols_count": len(by_symbol),
        "verdict_keys_count": len(index),
        "source_counts": source_counts,
        "ea_grade_counts": {},
        "policy_counts": {},
    }
    for item in index.values():
        ea = item.get("ea") or {}
        pol = item.get("policy") or {}
        grade = _safe_upper(ea.get("grade")) or "NO_EA"
        code = _safe_str(pol.get("code") or "NONE")
        summary["ea_grade_counts"][grade] = summary["ea_grade_counts"].get(grade, 0) + 1
        summary["policy_counts"][code] = summary["policy_counts"].get(code, 0) + 1

    return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "ts": time.time(), "summary": summary, "index": index, "by_symbol": by_symbol}


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_latest_bridge(path: Path = LATEST_PATH) -> Dict[str, Any]:
    data = build_ea_verdict_index()
    write_json_atomic(Path(path), data)
    return data


def find_ea_verdict(bridge: Dict[str, Any], *, symbol: str, side: str = "", setup_type: str = "", max_age_sec: int = 3600) -> Optional[Dict[str, Any]]:
    now = time.time()
    symbol = _safe_upper(symbol)
    side = _safe_upper(side)
    setup_type = _safe_str(setup_type)
    if not symbol:
        return None

    index = bridge.get("index") or {}
    exact = index.get(verdict_key(symbol, side, setup_type))
    if isinstance(exact, dict) and _safe_float(exact.get("ts"), 0.0) > 0:
        if now - _safe_float(exact.get("ts"), 0.0) <= max_age_sec:
            return exact

    candidates = []
    for item in (bridge.get("by_symbol") or {}).get(symbol, []):
        if side and _safe_upper(item.get("side")) != side:
            continue
        if now - _safe_float(item.get("ts"), 0.0) > max_age_sec:
            continue
        candidates.append(item)

    if candidates:
        candidates.sort(key=lambda x: (_safe_str(x.get("setup_type")) == setup_type, _safe_float(x.get("ts"), 0.0), _safe_int((x.get("ea") or {}).get("score"), 0)), reverse=True)
        return candidates[0]
    return None


def load_or_build_bridge(path: Path = LATEST_PATH) -> Dict[str, Any]:
    data = _load_json(Path(path))
    if data.get("schema") == SCHEMA and isinstance(data.get("index"), dict):
        return data
    return build_ea_verdict_index()
