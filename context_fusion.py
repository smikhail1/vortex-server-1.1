import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List
from snapshot_guard import should_write_latest_snapshot


SCHEMA = "vortex.context_fusion.v1"
SCHEMA_VERSION = "1.8.21k-c"

STRATEGY_PATH = Path("_runtime/strategy_observer_latest.json")
HEATMAP_PATH = Path("_runtime/market_heatmap_latest.json")
SETUP_ZONE_PATH = Path("_runtime/setup_zone_latest.json")
DEDUP_SUMMARY_PATH = Path("_runtime/entry_candidate_dedup_summary.json")

LATEST_PATH = Path("_runtime/context_fusion_latest.json")
SUMMARY_PATH = Path("_runtime/context_fusion_summary.jsonl")


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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _index_by_symbol(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for item in items or []:
        sym = _safe_str(item.get("symbol")).upper()
        if sym:
            out[sym] = item
    return out


def _strategy_symbols(strategy_snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return _index_by_symbol(strategy_snapshot.get("symbols") or [])


def _setup_symbols(setup_snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return _index_by_symbol(setup_snapshot.get("symbols") or [])


def _heatmap_symbols(heatmap_snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return _index_by_symbol(heatmap_snapshot.get("symbols") or [])


def _heatmap_support_for_side(side: str, heatmap_summary: Dict[str, Any]) -> Dict[str, Any]:
    side = _safe_str(side).upper()
    bias = _safe_str(heatmap_summary.get("bias"), "unknown")
    net = _safe_float(heatmap_summary.get("net_bias_score"), 0.0)
    long_pressure = _safe_float(heatmap_summary.get("long_pressure"), 0.0)
    short_pressure = _safe_float(heatmap_summary.get("short_pressure"), 0.0)

    if side == "LONG":
        if bias in ("strong_bullish", "mild_bullish"):
            status = "supportive"
        elif bias in ("strong_bearish", "mild_bearish"):
            status = "against"
        else:
            status = "neutral"
        score = max(0, min(100, int(round(50 + net))))
    elif side == "SHORT":
        if bias in ("strong_bearish", "mild_bearish"):
            status = "supportive"
        elif bias in ("strong_bullish", "mild_bullish"):
            status = "against"
        else:
            status = "neutral"
        score = max(0, min(100, int(round(50 - net))))
    else:
        status = "neutral"
        score = 50

    return {
        "bias": bias,
        "net_bias_score": net,
        "long_pressure": long_pressure,
        "short_pressure": short_pressure,
        "support_status": status,
        "support_score": score,
    }


def _setup_support_for_side(side: str, setup: Dict[str, Any]) -> Dict[str, Any]:
    side = _safe_str(side).upper()
    if side == "LONG":
        q = _safe_int(setup.get("long_zone_quality"), 0)
        preferred = _safe_str(setup.get("preferred_zone"))
        if preferred == "long_pullback_zone" and q >= 65:
            status = "supportive"
        elif setup.get("near_resistance") or preferred in ("high_zone", "middle_no_trade_zone"):
            status = "against"
        elif q >= 55:
            status = "neutral_plus"
        else:
            status = "neutral"
    elif side == "SHORT":
        q = _safe_int(setup.get("short_zone_quality"), 0)
        preferred = _safe_str(setup.get("preferred_zone"))
        if preferred == "short_pullback_zone" and q >= 65:
            status = "supportive"
        elif setup.get("near_support") or preferred in ("low_zone", "middle_no_trade_zone"):
            status = "against"
        elif q >= 55:
            status = "neutral_plus"
        else:
            status = "neutral"
    else:
        q = max(_safe_int(setup.get("long_zone_quality"), 0), _safe_int(setup.get("short_zone_quality"), 0))
        preferred = _safe_str(setup.get("preferred_zone"))
        status = "watch"

    return {
        "preferred_zone": _safe_str(setup.get("preferred_zone")),
        "zone_quality": q,
        "support_status": status,
        "range_position_pct": _safe_float(setup.get("range_position_pct"), 50.0),
        "near_support": bool(setup.get("near_support")),
        "near_resistance": bool(setup.get("near_resistance")),
        "near_ema20": bool(setup.get("near_ema20")),
        "warnings": setup.get("warnings") or [],
    }


def _final_view(strategy: Dict[str, Any], setup_support: Dict[str, Any], heatmap_support: Dict[str, Any]) -> Dict[str, Any]:
    state = _safe_str(strategy.get("state"))
    strat = strategy.get("strategy") or {}
    policy = strategy.get("policy") or {}
    side = _safe_str(strat.get("signal")).upper()

    reasons: List[str] = []
    warnings: List[str] = []
    blockers: List[str] = []

    if state:
        reasons.append(f"strategy_state={state}")

    if strat.get("setup_type"):
        reasons.append(f"setup={strat.get('setup_type')}")

    if side:
        reasons.append(f"side={side}")

    if setup_support.get("support_status") == "supportive":
        reasons.append(f"setup_zone_support={setup_support.get('preferred_zone')} q={setup_support.get('zone_quality')}")
    elif setup_support.get("support_status") in ("against",):
        warnings.append(f"setup_zone_against={setup_support.get('preferred_zone')} q={setup_support.get('zone_quality')}")
    elif setup_support.get("support_status") == "neutral_plus":
        reasons.append(f"setup_zone_neutral_plus q={setup_support.get('zone_quality')}")

    if heatmap_support.get("support_status") == "supportive":
        reasons.append(f"heatmap_support={heatmap_support.get('bias')}")
    elif heatmap_support.get("support_status") == "against":
        warnings.append(f"heatmap_against={heatmap_support.get('bias')}")
    else:
        warnings.append(f"heatmap_neutral={heatmap_support.get('bias')}")

    for w in setup_support.get("warnings") or []:
        warnings.append(f"zone_warning={w}")

    policy_code = policy.get("code")
    policy_reason = policy.get("reason")
    if policy_code:
        blockers.append(f"{policy_code}: {policy_reason}")

    if state == "READY_ALLOWED":
        if setup_support.get("support_status") == "supportive" and heatmap_support.get("support_status") != "against":
            view = "ENTRY_CANDIDATE_STRONG"
        else:
            view = "ENTRY_CANDIDATE_WEAK_CONTEXT"
    elif state == "RAW_READY_NO_EA":
        if setup_support.get("support_status") == "supportive" and heatmap_support.get("support_status") != "against":
            view = "RAW_CANDIDATE_WAIT_EA_GOOD_ZONE"
        elif setup_support.get("support_status") == "against" or heatmap_support.get("support_status") == "against":
            view = "RAW_CANDIDATE_BAD_CONTEXT"
        else:
            view = "RAW_CANDIDATE_WAIT_EA"
    elif state == "READY_BLOCKED_BY_POLICY":
        view = "POLICY_BLOCKED"
    elif state == "WAITING":
        if setup_support.get("support_status") == "supportive":
            view = "WATCH_GOOD_ZONE_WAIT_TRIGGER"
        else:
            view = "WATCH_ONLY"
    elif state == "BLOCKED_BY_STRATEGY":
        view = "STRATEGY_BLOCKED"
    elif state == "NO_TA_DATA":
        view = "NO_TA_DATA"
    else:
        view = "UNKNOWN"

    score = 0
    score += _safe_int(strat.get("score"), 0) * 6
    score += _safe_int(setup_support.get("zone_quality"), 0)
    score += _safe_int(heatmap_support.get("support_score"), 50) // 2

    if blockers:
        score -= 25
    if setup_support.get("support_status") == "against":
        score -= 20
    if heatmap_support.get("support_status") == "against":
        score -= 20

    score = max(0, min(100, int(round(score / 2))))

    return {
        "view": view,
        "score": score,
        "reasons": reasons[:12],
        "warnings": warnings[:12],
        "blockers": blockers[:8],
    }


def build_context_fusion_snapshot(
    strategy_snapshot: Dict[str, Any],
    heatmap_snapshot: Dict[str, Any],
    setup_snapshot: Dict[str, Any],
    dedup_summary: Dict[str, Any] = None,
) -> Dict[str, Any]:
    dedup_summary = dedup_summary or {}

    strategy_by_symbol = _strategy_symbols(strategy_snapshot)
    heatmap_by_symbol = _heatmap_symbols(heatmap_snapshot)
    setup_by_symbol = _setup_symbols(setup_snapshot)

    heatmap_summary = heatmap_snapshot.get("summary") or {}

    symbols = sorted(set(strategy_by_symbol) | set(heatmap_by_symbol) | set(setup_by_symbol))

    rows: List[Dict[str, Any]] = []
    for symbol in symbols:
        strategy = strategy_by_symbol.get(symbol) or {"symbol": symbol, "state": "NO_STRATEGY_DATA", "strategy": {}}
        setup = setup_by_symbol.get(symbol) or {"symbol": symbol}
        heat = heatmap_by_symbol.get(symbol) or {"symbol": symbol}

        strat_info = strategy.get("strategy") or {}
        side = _safe_str(strat_info.get("signal")).upper()

        # If strategy has no side but setup zone is very clear, keep symbol as WATCH.
        setup_support = _setup_support_for_side(side, setup)
        heatmap_support = _heatmap_support_for_side(side, heatmap_summary)
        final = _final_view(strategy, setup_support, heatmap_support)

        rows.append({
            "symbol": symbol,
            "strategy_state": strategy.get("state"),
            "side": side,
            "strategy": {
                "score": strat_info.get("score"),
                "setup_type": strat_info.get("setup_type"),
                "args_text": strat_info.get("args_text"),
                "blocked_reason": strat_info.get("blocked_reason"),
            },
            "policy": strategy.get("policy") or {},
            "ea": strategy.get("ea") or {},
            "setup_zone": setup_support,
            "heatmap": {
                "global": heatmap_support,
                "local_bias": heat.get("local_bias"),
                "trend_4h": heat.get("trend_4h"),
                "adx": heat.get("adx"),
                "rsi_main": heat.get("rsi_main"),
                "vol_ratio": heat.get("vol_ratio"),
            },
            "final": final,
        })

    final_counts = {}
    for row in rows:
        view = row.get("final", {}).get("view", "UNKNOWN")
        final_counts[view] = final_counts.get(view, 0) + 1

    important = sorted(
        rows,
        key=lambda x: (
            x.get("final", {}).get("view") in (
                "ENTRY_CANDIDATE_STRONG",
                "RAW_CANDIDATE_WAIT_EA_GOOD_ZONE",
                "WATCH_GOOD_ZONE_WAIT_TRIGGER",
                "POLICY_BLOCKED",
            ),
            x.get("final", {}).get("score", 0),
        ),
        reverse=True,
    )[:30]

    summary = {
        "symbols_count": len(rows),
        "final_view_counts": final_counts,
        "heatmap_bias": heatmap_summary.get("bias"),
        "heatmap_net_bias_score": heatmap_summary.get("net_bias_score"),
        "strategy_summary": strategy_snapshot.get("summary") or {},
        "setup_summary": setup_snapshot.get("summary") or {},
        "dedup_summary": {
            "total_seen": dedup_summary.get("total_seen"),
            "total_written": dedup_summary.get("total_written"),
            "total_suppressed": dedup_summary.get("total_suppressed"),
            "unique_keys": dedup_summary.get("unique_keys"),
            "top_policy": dedup_summary.get("top_policy"),
        },
    }

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "summary": summary,
        "important": important,
        "symbols": rows,
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
        "important": [
            {
                "symbol": x.get("symbol"),
                "side": x.get("side"),
                "strategy_state": x.get("strategy_state"),
                "final_view": (x.get("final") or {}).get("view"),
                "score": (x.get("final") or {}).get("score"),
                "blockers": (x.get("final") or {}).get("blockers"),
                "warnings": (x.get("final") or {}).get("warnings"),
            }
            for x in snapshot.get("important", [])[:12]
        ],
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(compact, ensure_ascii=False, sort_keys=True) + "\n")


def build_latest_snapshot_from_files() -> Dict[str, Any]:
    return build_context_fusion_snapshot(
        strategy_snapshot=_load_json(STRATEGY_PATH),
        heatmap_snapshot=_load_json(HEATMAP_PATH),
        setup_snapshot=_load_json(SETUP_ZONE_PATH),
        dedup_summary=_load_json(DEDUP_SUMMARY_PATH),
    )


async def context_fusion_loop(state, logger=None) -> None:
    interval = 60

    while True:
        try:
            snapshot = build_latest_snapshot_from_files()

            guard = should_write_latest_snapshot(LATEST_PATH, snapshot)
            snapshot["latest_guard"] = guard

            if guard.get("write_latest"):
                write_json_atomic(LATEST_PATH, snapshot)
            else:
                try:
                    await state.add_sys_log(
                        "🛡️ [SNAPSHOT_GUARD]",
                        f"{guard.get('action')} | {guard.get('reason')} | new={guard.get('new_counts')} | old={guard.get('old_counts')}",
                    )
                except Exception:
                    pass

            append_summary(SUMMARY_PATH, snapshot)

            summary = snapshot.get("summary", {})
            try:
                await state.add_sys_log(
                    "🧠 [CONTEXT_FUSION]",
                    (
                        f"symbols={summary.get('symbols_count')} | "
                        f"heatmap={summary.get('heatmap_bias')} | "
                        f"views={summary.get('final_view_counts')}"
                    ),
                )
            except Exception:
                pass

            if logger:
                logger.info("CONTEXT_FUSION", "snapshot updated", summary)

        except Exception as exc:
            try:
                await state.add_sys_log("❌ [CONTEXT_FUSION]", str(exc))
            except Exception:
                pass

            if logger:
                logger.warning("CONTEXT_FUSION", "context fusion loop failed", {"error": str(exc)})

        await asyncio.sleep(interval)
