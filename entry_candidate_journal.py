import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


SCHEMA = "vortex.entry_candidate_journal.v1"
SCHEMA_VERSION = "1.8.21h-b"

DEFAULT_OUT = "_runtime/entry_candidates.jsonl"


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


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


def write_entry_candidate(record: Dict[str, Any], out_path: str = DEFAULT_OUT) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
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
