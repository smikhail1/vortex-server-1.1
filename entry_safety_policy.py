import csv
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SCHEMA = "vortex.entry_safety_policy.v1"
SCHEMA_VERSION = "1.8.21h-a"


MIN_EA_SCORE = 70
MAX_FUT_OPENS_PER_DAY = 8
SYMBOL_COOLDOWN_AFTER_BAD_CLOSE_SEC = 4 * 3600

ALLOWED_EA_GRADES = {"B"}
BLOCKED_EA_GRADES = {"C", "D"}

BLACKLIST_SYMBOLS = {
    "VVVUSDT",
    "TONUSDT",
    "XPLUSDT",
    "PENDLEUSDT",
    "HYPEUSDT",
    "INJUSDT",
    "VIRTUALUSDT",
    "CLUSDT",
    "LAYERUSDT",
    "NEARUSDT",
    "LABUSDT",
}

DISABLED_SETUPS_EXACT = {
    "trend_follow_v1.7",
    "trend_short_v1.8.1",
    "dead_override_momentum_long",
    "dead_override_momentum_short",
}

DISABLED_SETUP_PREFIXES = (
    "dead_override_",
    "pullback_",
)

BAD_CLOSE_REASONS = {
    "SL",
    "BU",
    "STALL",
    "FADE",
    "WEAK_PROGRESS",
    "WEAK_PROGRESS_STALE",
}


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

    # fallback: find the longest string-like arg that looks like strategy explanation
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

    grade = m.group(1).upper()
    score = int(m.group(2))
    label = m.group(3).upper()

    return {
        "present": True,
        "grade": grade,
        "score": score,
        "label": label,
        "raw": m.group(0),
    }


def _parse_ts_epoch(ts_text: str) -> float:
    try:
        return datetime.strptime(ts_text.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_today_fut_rows(trades_path: str = "trades.csv", day: Optional[str] = None) -> List[Dict[str, Any]]:
    path = Path(trades_path)
    if not path.exists():
        return []

    day = day or _today_utc()
    rows: List[Dict[str, Any]] = []

    with path.open("r", encoding="utf-8", errors="replace", newline="") as fp:
        reader = csv.reader(fp)
        for parts in reader:
            if len(parts) < 10:
                continue

            ts = parts[0].strip()
            if not ts.startswith(day):
                continue

            symbol = parts[1].strip().upper()
            side = parts[2].strip().upper()
            market = parts[3].strip().upper()
            reason = parts[9].strip().upper()

            if market != "FUT":
                continue

            rows.append({
                "ts": ts,
                "ts_epoch": _parse_ts_epoch(ts),
                "symbol": symbol,
                "side": side,
                "market": market,
                "reason": reason,
                "raw": ",".join(parts),
            })

    return rows


def _setup_disabled(setup_type: str) -> bool:
    st = _safe_str(setup_type).strip()
    if st in DISABLED_SETUPS_EXACT:
        return True
    return any(st.startswith(prefix) for prefix in DISABLED_SETUP_PREFIXES)


def evaluate_entry_safety(
    *,
    args: Tuple[Any, ...] = (),
    kwargs: Optional[Dict[str, Any]] = None,
    trades_path: str = "trades.csv",
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    kwargs = dict(kwargs or {})
    now_ts = float(now_ts or time.time())

    symbol = _safe_str(_extract_arg(args, kwargs, "symbol", 0, "")).upper()
    side = _safe_str(_extract_arg(args, kwargs, "side", 1, "")).upper()
    setup_type = _safe_str(_extract_arg(args, kwargs, "setup_type", None, "")).strip()
    args_text = _extract_args_text(args, kwargs)
    ea = parse_ea(args_text)

    today_rows = load_today_fut_rows(trades_path=trades_path)
    today_opens = [r for r in today_rows if r["reason"] == "OPEN"]
    today_symbol_rows = [r for r in today_rows if r["symbol"] == symbol]
    today_symbol_opens = [r for r in today_symbol_rows if r["reason"] == "OPEN"]

    recent_bad_closes = []
    for r in today_symbol_rows:
        if r["reason"] in BAD_CLOSE_REASONS and (now_ts - _safe_float(r.get("ts_epoch"), 0.0)) <= SYMBOL_COOLDOWN_AFTER_BAD_CLOSE_SEC:
            recent_bad_closes.append(r)

    checks = {
        "symbol": symbol,
        "side": side,
        "setup_type": setup_type,
        "args_text": args_text,
        "ea": ea,
        "today_fut_opens_count": len(today_opens),
        "today_symbol_opens_count": len(today_symbol_opens),
        "recent_bad_closes_count": len(recent_bad_closes),
        "blacklist_symbols": sorted(BLACKLIST_SYMBOLS),
        "min_ea_score": MIN_EA_SCORE,
        "max_fut_opens_per_day": MAX_FUT_OPENS_PER_DAY,
    }

    if not symbol:
        return _decision(False, "BLOCK_NO_SYMBOL", "symbol is empty", checks)

    if symbol in BLACKLIST_SYMBOLS:
        return _decision(False, "BLOCK_SYMBOL_BLACKLIST", f"{symbol} is blacklisted for live futures", checks)

    if not ea["present"]:
        return _decision(False, "BLOCK_NO_EA", "EA verdict is missing; live futures requires EA:B", checks)

    if ea["grade"] in BLOCKED_EA_GRADES:
        return _decision(False, f"BLOCK_EA_{ea['grade']}", f"EA grade {ea['grade']} is not allowed for live futures", checks)

    if ea["grade"] not in ALLOWED_EA_GRADES:
        return _decision(False, "BLOCK_EA_NOT_ALLOWED", f"EA grade {ea['grade']} is not in allowed set", checks)

    if int(ea["score"]) < MIN_EA_SCORE:
        return _decision(False, "BLOCK_EA_SCORE_LOW", f"EA score {ea['score']} < {MIN_EA_SCORE}", checks)

    if _setup_disabled(setup_type):
        return _decision(False, "BLOCK_SETUP_DISABLED", f"setup_type {setup_type} is disabled for live futures", checks)

    if len(today_opens) >= MAX_FUT_OPENS_PER_DAY:
        return _decision(False, "BLOCK_DAILY_FUT_OPEN_LIMIT", f"today FUT opens {len(today_opens)} >= {MAX_FUT_OPENS_PER_DAY}", checks)

    if today_symbol_opens:
        return _decision(False, "BLOCK_SYMBOL_ALREADY_TRADED_TODAY", f"{symbol} already had FUT OPEN today", checks)

    if recent_bad_closes:
        return _decision(False, "BLOCK_RECENT_BAD_CLOSE", f"{symbol} has recent bad close within cooldown", checks)

    return _decision(True, "ALLOW_ENTRY_SAFETY", "entry passed safety policy", checks)


def _decision(allow: bool, code: str, reason: str, checks: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "allow": bool(allow),
        "code": code,
        "reason": reason,
        "checks": checks,
    }
