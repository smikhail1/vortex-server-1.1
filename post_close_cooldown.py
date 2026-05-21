import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

STATE_PATH = Path("_runtime/post_close_cooldown_state.json")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def _cfg(name: str, default: Any) -> Any:
    try:
        from config import CONFIG
        return getattr(getattr(CONFIG, "risk", object()), name, default)
    except Exception:
        return default


def _load_state() -> Dict[str, Any]:
    try:
        if STATE_PATH.exists():
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("blocks", [])
                return data
    except Exception:
        pass
    return {"schema": "vortex.post_close_cooldown.v1", "schema_version": "1.8.19j-r2", "blocks": []}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _cleanup(state: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else float(now)
    blocks = state.get("blocks") or []
    if not isinstance(blocks, list):
        blocks = []
    state["blocks"] = [b for b in blocks if _safe_float((b or {}).get("expires_at")) > now]
    return state


def _duration_for_reason(reason: str, pnl_net: float) -> int:
    reason = _safe_str(reason).upper()
    if reason == "BU":
        return int(_cfg("post_close_cooldown_after_bu_sec", 900))
    if reason == "SL":
        return int(_cfg("post_close_cooldown_after_sl_sec", 1800))
    if reason == "STALL":
        if pnl_net >= 0:
            return int(_cfg("post_close_cooldown_after_stall_win_sec", 300))
        return int(_cfg("post_close_cooldown_after_stall_loss_sec", 900))
    if reason == "TP2":
        return int(_cfg("post_close_cooldown_after_tp2_sec", 300))
    return int(_cfg("post_close_cooldown_default_sec", 300))


def _norm_symbol(symbol: Any) -> str:
    return _safe_str(symbol).upper().strip()


def _norm_side(side: Any) -> str:
    return _safe_str(side).upper().strip()


def _norm_setup(setup_type: Any) -> str:
    return _safe_str(setup_type, "UNKNOWN").strip() or "UNKNOWN"


def _extract_arg_float(analysis: Dict[str, Any], key: str, fallback: float = 0.0) -> float:
    if not isinstance(analysis, dict):
        return fallback

    aliases = {
        "range_pct": ["range_pct", "range", "range_percent"],
        "change_pct": ["change_pct", "change", "change_percent"],
        "volume_ratio": ["volume_ratio", "vol", "volume"],
        "score": ["score"],
    }.get(key, [key])

    for k in aliases:
        v = analysis.get(k)
        if isinstance(v, (int, float)):
            return float(v)

    args_text = _safe_str(analysis.get("args_text"))
    patterns = {
        "range_pct": r"range\s*=\s*([-+]?\d+(?:\.\d+)?)\s*%",
        "change_pct": r"change\s*=\s*([-+]?\d+(?:\.\d+)?)\s*%",
        "volume_ratio": r"vol\s*=\s*([-+]?\d+(?:\.\d+)?)",
        "score": r"score\s*=\s*([-+]?\d+(?:\.\d+)?)",
    }
    m = re.search(patterns.get(key, ""), args_text, flags=re.I)
    if m:
        return _safe_float(m.group(1), fallback)
    return fallback


def register_futures_close(symbol: str, side: str, setup_type: str, reason: str, pnl_net: float, ts: Optional[float] = None) -> Dict[str, Any]:
    if not bool(_cfg("post_close_cooldown_enabled", True)):
        return {"registered": False, "reason": "disabled"}

    now = time.time() if ts is None else float(ts)
    symbol = _norm_symbol(symbol)
    side = _norm_side(side)
    setup_type = _norm_setup(setup_type)
    reason = _safe_str(reason, "CLOSE").upper()
    pnl_net = _safe_float(pnl_net)

    if not symbol:
        return {"registered": False, "reason": "empty_symbol"}

    base_sec = max(0, _duration_for_reason(reason, pnl_net))
    mult = _safe_float(_cfg("post_close_same_setup_cooldown_multiplier", 2.0), 2.0)
    setup_sec = max(base_sec, int(base_sec * mult))

    state = _cleanup(_load_state(), now)
    blocks = state.setdefault("blocks", [])

    if base_sec > 0:
        blocks.append({
            "scope": "symbol",
            "key": f"FUT:{symbol}",
            "symbol": symbol,
            "side": side,
            "setup_type": setup_type,
            "reason": reason,
            "pnl_net": pnl_net,
            "created_at": now,
            "expires_at": now + base_sec,
            "duration_sec": base_sec,
        })

    if setup_sec > 0:
        blocks.append({
            "scope": "symbol_side_setup",
            "key": f"FUT:{symbol}:{side}:{setup_type}",
            "symbol": symbol,
            "side": side,
            "setup_type": setup_type,
            "reason": reason,
            "pnl_net": pnl_net,
            "created_at": now,
            "expires_at": now + setup_sec,
            "duration_sec": setup_sec,
        })

    _save_state(state)
    return {"registered": True, "symbol": symbol, "side": side, "setup_type": setup_type, "reason": reason, "base_sec": base_sec, "setup_sec": setup_sec}


def _cooldown_decision(symbol: str, side: str, setup_type: str, now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else float(now)
    symbol = _norm_symbol(symbol)
    side = _norm_side(side)
    setup_type = _norm_setup(setup_type)

    state = _cleanup(_load_state(), now)
    _save_state(state)

    keys = {f"FUT:{symbol}", f"FUT:{symbol}:{side}:{setup_type}"}
    active = []
    for b in state.get("blocks") or []:
        if (b or {}).get("key") in keys:
            left = int(max(0, _safe_float((b or {}).get("expires_at")) - now))
            active.append((left, b))

    if not active:
        return {"allow": True, "reason": "no_post_close_cooldown"}

    left, block = sorted(active, key=lambda x: x[0], reverse=True)[0]
    return {
        "allow": False,
        "reason": f"post_close_cooldown:{block.get('scope')}:{block.get('reason')}:left={left}s",
        "cooldown_left_sec": left,
        "block": block,
    }


def _distance_guards(symbol: str, side: str, price: float, ladder: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(_cfg("futures_preopen_distance_guard_enabled", True)):
        return {"allow": True, "reason": "distance_guard_disabled"}

    price = _safe_float(price)
    if price <= 0:
        return {"allow": False, "reason": "invalid_price_for_distance_guard"}

    sl = _safe_float((ladder or {}).get("sl"))
    tp0 = _safe_float((ladder or {}).get("tp0"))

    min_sl_pct = _safe_float(_cfg("min_futures_stop_distance_pct", 0.25), 0.25)
    min_tp0_pct = _safe_float(_cfg("min_futures_tp0_distance_pct", 0.15), 0.15)

    if sl > 0 and min_sl_pct > 0:
        sl_dist_pct = abs(price - sl) / price * 100.0
        if sl_dist_pct < min_sl_pct:
            return {"allow": False, "reason": f"stop_too_close:{sl_dist_pct:.4f}%<{min_sl_pct:.4f}%", "sl_dist_pct": sl_dist_pct}

    if tp0 > 0 and min_tp0_pct > 0:
        tp0_dist_pct = abs(tp0 - price) / price * 100.0
        if tp0_dist_pct < min_tp0_pct:
            return {"allow": False, "reason": f"tp0_too_close:{tp0_dist_pct:.4f}%<{min_tp0_pct:.4f}%", "tp0_dist_pct": tp0_dist_pct}

    return {"allow": True, "reason": "distance_guard_ok"}


def _momentum_long_guard(setup_type: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(_cfg("momentum_long_strict_enabled", True)):
        return {"allow": True, "reason": "momentum_long_guard_disabled"}

    setup = _norm_setup(setup_type).lower()
    if setup != "momentum_long":
        return {"allow": True, "reason": "not_momentum_long"}

    score = _extract_arg_float(analysis, "score", 0.0)
    volume_ratio = _extract_arg_float(analysis, "volume_ratio", 0.0)
    change_pct = _extract_arg_float(analysis, "change_pct", 0.0)
    range_pct = _extract_arg_float(analysis, "range_pct", 0.0)

    min_score = _safe_float(_cfg("momentum_long_min_score", 10), 10)
    min_vol = _safe_float(_cfg("momentum_long_min_volume_ratio", 2.0), 2.0)
    max_change = _safe_float(_cfg("momentum_long_max_change_pct", 14.0), 14.0)
    max_range = _safe_float(_cfg("momentum_long_max_range_pct", 16.0), 16.0)

    if score < min_score:
        return {"allow": False, "reason": f"momentum_long_score_low:{score:g}<{min_score:g}"}
    if volume_ratio < min_vol:
        return {"allow": False, "reason": f"momentum_long_volume_low:{volume_ratio:g}<{min_vol:g}"}
    if change_pct > max_change:
        return {"allow": False, "reason": f"momentum_long_change_extended:{change_pct:g}>{max_change:g}"}
    if range_pct > max_range:
        return {"allow": False, "reason": f"momentum_long_range_extended:{range_pct:g}>{max_range:g}"}

    return {"allow": True, "reason": "momentum_long_guard_ok"}


def can_open_futures(symbol: str, side: str, setup_type: str, analysis: Dict[str, Any], price: float, ladder: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(_cfg("post_close_cooldown_enabled", True)):
        return {"allow": True, "reason": "post_close_guard_disabled"}

    checks = [
        _cooldown_decision(symbol, side, setup_type),
        _distance_guards(symbol, side, price, ladder or {}),
        _momentum_long_guard(setup_type, analysis or {}),
    ]

    for dec in checks:
        if not dec.get("allow", True):
            return dec
    return {"allow": True, "reason": "preopen_guard_ok"}
