import asyncio
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import CONFIG
from entry_safety_policy import evaluate_entry_safety

SCHEMA = "vortex.strategy_observer.v1"
SCHEMA_VERSION = "1.8.21i-a-r2"
LATEST_PATH = Path("_runtime/strategy_observer_latest.json")
SUMMARY_PATH = Path("_runtime/strategy_observer_summary.jsonl")

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

def parse_ea(args_text: str) -> Dict[str, Any]:
    text = _safe_str(args_text)
    m = re.search(r"\bEA:([A-D])\/(\d+)\s+([A-Z_]+)", text)
    if not m:
        return {"present": False, "grade": "", "score": 0, "label": "NO_EA", "raw": ""}
    return {"present": True, "grade": m.group(1).upper(), "score": int(m.group(2)), "label": m.group(3).upper(), "raw": m.group(0)}

def _has_real_ta(ta: Dict[str, Any]) -> bool:
    if not isinstance(ta, dict) or not ta:
        return False
    price = _safe_float(ta.get("price"), 0.0)
    adx = _safe_float(ta.get("adx"), 0.0)
    trend = _safe_str(ta.get("trend_4h"), "")
    ema20 = _safe_float(ta.get("ema20"), 0.0)
    ema50 = _safe_float(ta.get("ema50"), 0.0)
    atr = _safe_float(ta.get("atr"), 0.0)
    return price > 0 and (adx > 0 or trend != "" or ema20 > 0 or ema50 > 0 or atr > 0)

def _compact_ta(ta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "price": _safe_float(ta.get("price"), 0.0),
        "adx": _safe_float(ta.get("adx"), 0.0),
        "rsi_main": _safe_float(ta.get("rsi_main"), 50.0),
        "rsi_slope": _safe_float(ta.get("rsi_slope"), 0.0),
        "ema10": _safe_float(ta.get("ema10"), 0.0),
        "ema20": _safe_float(ta.get("ema20"), 0.0),
        "ema50": _safe_float(ta.get("ema50"), 0.0),
        "vol_ratio": _safe_float(ta.get("vol_ratio"), 0.0),
        "atr_pct": _safe_float(ta.get("atr_pct"), 0.0),
        "atr": _safe_float(ta.get("atr"), 0.0),
        "trend_4h": _safe_str(ta.get("trend_4h"), ""),
        "wick_long_danger": bool(ta.get("wick_long_danger")),
        "wick_short_danger": bool(ta.get("wick_short_danger")),
        "recent_high": _safe_float(ta.get("recent_high"), 0.0),
        "recent_low": _safe_float(ta.get("recent_low"), 0.0),
    }

def _classify_state(analysis: Dict[str, Any], ea: Dict[str, Any], policy: Optional[Dict[str, Any]]) -> str:
    if not analysis.get("should_open"):
        return "BLOCKED_BY_STRATEGY" if analysis.get("blocked_reason") else "WAITING"
    if not ea.get("present"):
        return "RAW_READY_NO_EA"
    if policy and policy.get("allow"):
        return "READY_ALLOWED"
    if policy:
        return "READY_BLOCKED_BY_POLICY"
    return "RAW_READY_UNCHECKED"

def build_symbol_observation(*, symbol: str, ta: Dict[str, Any], strategy, macro_filter: str = "allow_all", trades_path: str = "trades.csv") -> Dict[str, Any]:
    symbol = _safe_str(symbol).upper()
    ta = dict(ta or {})
    if not _has_real_ta(ta):
        return {
            "symbol": symbol,
            "state": "NO_TA_DATA",
            "ta": _compact_ta(ta),
            "strategy": {"should_open": False, "signal": None, "score": 0, "setup_type": None, "args_text": "", "blocked_reason": "no usable TA snapshot", "threshold": 0},
            "ea": {"present": False, "grade": "", "score": 0, "label": "NO_EA", "raw": ""},
            "policy": {"allow": None, "code": None, "reason": None},
            "interpretation": "No TA data yet; strategy was not executed for this symbol.",
        }
    try:
        analysis = strategy.analyze_futures(ta, macro_filter=macro_filter)
        if not isinstance(analysis, dict):
            analysis = {"should_open": False, "blocked_reason": "strategy returned non-dict"}
    except Exception as exc:
        analysis = {"should_open": False, "blocked_reason": f"strategy_error:{exc}", "signal": None, "score": 0, "setup_type": None, "args_text": "", "threshold": 0}
    args_text = _safe_str(analysis.get("args_text"), "")
    ea = parse_ea(args_text)
    policy = None
    if analysis.get("should_open"):
        policy = evaluate_entry_safety(kwargs={"symbol": symbol, "side": _safe_str(analysis.get("signal"), "").upper(), "setup_type": _safe_str(analysis.get("setup_type"), ""), "args_text": args_text}, trades_path=trades_path)
    state = _classify_state(analysis, ea, policy)
    if state == "RAW_READY_NO_EA":
        interpretation = "Raw strategy is ready, but EA verdict is missing; final entry is not allowed."
    elif state == "READY_BLOCKED_BY_POLICY":
        interpretation = "Strategy and EA produced a candidate, but entry safety policy blocked it."
    elif state == "READY_ALLOWED":
        interpretation = "Strategy candidate passed entry safety policy."
    elif state == "BLOCKED_BY_STRATEGY":
        interpretation = "Strategy explicitly blocked this symbol."
    elif state == "WAITING":
        interpretation = "TA is valid, but setup is not ready."
    else:
        interpretation = "Observer state classified."
    return {
        "symbol": symbol,
        "state": state,
        "ta": _compact_ta(ta),
        "strategy": {"should_open": bool(analysis.get("should_open")), "signal": analysis.get("signal"), "score": _safe_int(analysis.get("score"), 0), "setup_type": analysis.get("setup_type"), "args_text": args_text, "blocked_reason": analysis.get("blocked_reason"), "threshold": _safe_int(analysis.get("threshold"), 0)},
        "ea": ea,
        "policy": {"allow": policy.get("allow") if isinstance(policy, dict) else None, "code": policy.get("code") if isinstance(policy, dict) else None, "reason": policy.get("reason") if isinstance(policy, dict) else None},
        "interpretation": interpretation,
    }

def build_strategy_observer_snapshot(*, dashboard: Dict[str, Any], strategy, macro_filter: str = "allow_all", trades_path: str = "trades.csv") -> Dict[str, Any]:
    market = dashboard.get("market", {}) or {}
    ta_data = market.get("ta_data", {}) or {}
    prices = market.get("prices", {}) or {}
    observations: List[Dict[str, Any]] = []
    for symbol in sorted(ta_data.keys()):
        ta = dict(ta_data.get(symbol, {}) or {})
        if symbol in prices and "price" not in ta:
            ta["price"] = prices.get(symbol)
        observations.append(build_symbol_observation(symbol=symbol, ta=ta, strategy=strategy, macro_filter=macro_filter, trades_path=trades_path))
    ta_symbols = set(ta_data.keys())
    for symbol in sorted(set(prices.keys()) - ta_symbols):
        observations.append(build_symbol_observation(symbol=symbol, ta={"price": prices.get(symbol)}, strategy=strategy, macro_filter=macro_filter, trades_path=trades_path))
    state_counts = Counter(x.get("state") for x in observations)
    setup_counts = Counter((x.get("strategy") or {}).get("setup_type") or "NONE" for x in observations)
    policy_counts = Counter((x.get("policy") or {}).get("code") or "NONE" for x in observations)
    ea_counts = Counter((x.get("ea") or {}).get("grade") or "NO_EA" for x in observations)
    ready_allowed = [x for x in observations if x.get("state") == "READY_ALLOWED"]
    ready_blocked = [x for x in observations if x.get("state") == "READY_BLOCKED_BY_POLICY"]
    raw_ready_no_ea = [x for x in observations if x.get("state") == "RAW_READY_NO_EA"]
    top_watch = sorted([x for x in observations if x.get("state") != "NO_TA_DATA"], key=lambda x: (_safe_int((x.get("strategy") or {}).get("score"), 0), _safe_float((x.get("ta") or {}).get("adx"), 0.0)), reverse=True)[:20]
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "meta": dashboard.get("meta", {}),
        "counts": dashboard.get("counts", {}),
        "positions": dashboard.get("positions", {}),
        "summary": {"symbols_total": len(observations), "ta_symbols_count": len(ta_data), "prices_count": len(prices), "analyzed_count": len([x for x in observations if x.get("state") != "NO_TA_DATA"]), "no_ta_count": len([x for x in observations if x.get("state") == "NO_TA_DATA"]), "state_counts": dict(state_counts), "setup_counts": dict(setup_counts), "policy_counts": dict(policy_counts), "ea_counts": dict(ea_counts), "ready_allowed_count": len(ready_allowed), "ready_blocked_count": len(ready_blocked), "raw_ready_no_ea_count": len(raw_ready_no_ea)},
        "ready_allowed": ready_allowed[:20],
        "ready_blocked": ready_blocked[:30],
        "raw_ready_no_ea": raw_ready_no_ea[:30],
        "top_watch": top_watch,
        "symbols": observations,
    }

def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)

def append_summary(path: Path, snapshot: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    compact = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": snapshot.get("ts"),
        "summary": snapshot.get("summary"),
        "ready_allowed": [{"symbol": x.get("symbol"), "signal": (x.get("strategy") or {}).get("signal"), "score": (x.get("strategy") or {}).get("score"), "setup_type": (x.get("strategy") or {}).get("setup_type"), "ea": (x.get("ea") or {}).get("raw"), "policy_code": (x.get("policy") or {}).get("code")} for x in snapshot.get("ready_allowed", [])[:10]],
        "ready_blocked": [{"symbol": x.get("symbol"), "signal": (x.get("strategy") or {}).get("signal"), "score": (x.get("strategy") or {}).get("score"), "setup_type": (x.get("strategy") or {}).get("setup_type"), "ea": (x.get("ea") or {}).get("raw"), "policy_code": (x.get("policy") or {}).get("code"), "policy_reason": (x.get("policy") or {}).get("reason")} for x in snapshot.get("ready_blocked", [])[:10]],
        "raw_ready_no_ea": [{"symbol": x.get("symbol"), "signal": (x.get("strategy") or {}).get("signal"), "score": (x.get("strategy") or {}).get("score"), "setup_type": (x.get("strategy") or {}).get("setup_type"), "policy_code": (x.get("policy") or {}).get("code")} for x in snapshot.get("raw_ready_no_ea", [])[:10]],
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(compact, ensure_ascii=False, sort_keys=True) + "\n")

async def strategy_observer_loop(state, strategy, logger=None) -> None:
    interval = int(getattr(getattr(CONFIG, "loops", None), "strategy_observer_sec", 60) or 60)
    while True:
        try:
            dashboard = await state.get_dashboard_state()
            system = dashboard.get("system", {}) or {}
            macro = system.get("macro", {}) or {}
            macro_filter = _safe_str(macro.get("global_filter") or macro.get("filter") or "allow_all", "allow_all")
            snapshot = build_strategy_observer_snapshot(dashboard=dashboard, strategy=strategy, macro_filter=macro_filter, trades_path="trades.csv")
            write_json_atomic(LATEST_PATH, snapshot)
            append_summary(SUMMARY_PATH, snapshot)
            try:
                await state.add_sys_log("🧠 [STRATEGY_OBSERVER]", f"analyzed={snapshot['summary']['analyzed_count']} | no_ta={snapshot['summary']['no_ta_count']} | states={snapshot['summary']['state_counts']} | allowed={snapshot['summary']['ready_allowed_count']} | raw_no_ea={snapshot['summary']['raw_ready_no_ea_count']}")
            except Exception:
                pass
            if logger:
                logger.info("STRATEGY_OBSERVER", "snapshot updated", snapshot.get("summary", {}))
        except Exception as exc:
            try:
                await state.add_sys_log("❌ [STRATEGY_OBSERVER]", str(exc))
            except Exception:
                pass
            if logger:
                logger.warning("STRATEGY_OBSERVER", "observer loop failed", {"error": str(exc)})
        await asyncio.sleep(interval)
