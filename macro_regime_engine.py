import asyncio
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA = "vortex.macro_regime.v1"
SCHEMA_VERSION = "1.8.21l-f-r2"

LATEST_PATH = Path("_runtime/macro_regime_latest.json")
SUMMARY_PATH = Path("_runtime/macro_regime_summary.jsonl")
HEATMAP_PATH = Path("_runtime/market_heatmap_latest.json")
ICHIMOKU_PATH = Path("_runtime/ichimoku_context_latest.json")
CONTEXT_FUSION_PATH = Path("_runtime/context_fusion_latest.json")
DEDUP_SUMMARY_PATH = Path("_runtime/entry_candidate_dedup_summary.json")
BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"


def _safe_str(value: Any, default: str = "") -> str:
    try:
        return default if value is None else str(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
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


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


def fetch_bitget_futures_tickers(timeout: float = 6.0) -> Dict[str, Any]:
    params = urllib.parse.urlencode({"productType": "USDT-FUTURES"})
    url = f"{BITGET_TICKERS_URL}?{params}"
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "VORTEX-Macro-Regime/1.8.21l-f-r2"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return {"available": False, "source": "bitget", "error": "unexpected_payload", "items_count": 0, "items": []}
        return {"available": True, "source": "bitget", "error": None, "items_count": len(items), "items": items}
    except Exception as exc:
        return {"available": False, "source": "bitget", "error": _safe_str(exc)[:220], "items_count": 0, "items": []}


def analyze_futures_pressure(tickers_payload: Dict[str, Any]) -> Dict[str, Any]:
    items = tickers_payload.get("items") or []
    if not tickers_payload.get("available") or not isinstance(items, list):
        return {
            "available": False,
            "source": "bitget",
            "error": tickers_payload.get("error"),
            "symbols_count": 0,
            "funding": {},
            "change24h": {},
            "oi": {},
            "pressure": "no_data",
            "warnings": ["futures_tickers_unavailable"],
        }

    funding_values, change_values, holding_values = [], [], []
    positive_funding = negative_funding = positive_change = negative_change = 0

    for x in items:
        if not isinstance(x, dict):
            continue
        if x.get("fundingRate") not in (None, ""):
            funding = _safe_float(x.get("fundingRate"), 0.0)
            funding_values.append(funding)
            if funding > 0:
                positive_funding += 1
            elif funding < 0:
                negative_funding += 1

        ch = _safe_float(x.get("change24h", x.get("chgUtc", x.get("changeUtc", 0.0))), 0.0)
        change_values.append(ch)
        if ch > 0:
            positive_change += 1
        elif ch < 0:
            negative_change += 1

        holding = _safe_float(x.get("holdingAmount", x.get("openInterest", 0.0)), 0.0)
        if holding > 0:
            holding_values.append(holding)

    n = max(1, len(items))
    avg_funding = sum(funding_values) / len(funding_values) if funding_values else 0.0
    avg_change = sum(change_values) / len(change_values) if change_values else 0.0
    pos_change_pct = positive_change / n * 100.0
    neg_change_pct = negative_change / n * 100.0

    warnings = []
    if abs(avg_funding) > 0.0005:
        warnings.append("funding_elevated")
    if pos_change_pct > 65:
        warnings.append("broad_positive_24h")
    if neg_change_pct > 65:
        warnings.append("broad_negative_24h")

    if pos_change_pct >= 60 and avg_funding >= 0:
        pressure = "risk_on_futures"
    elif neg_change_pct >= 60 and avg_funding <= 0:
        pressure = "risk_off_futures"
    elif abs(avg_funding) > 0.0005:
        pressure = "crowded_funding"
    else:
        pressure = "neutral_futures"

    return {
        "available": True,
        "source": "bitget",
        "symbols_count": len(items),
        "funding": {
            "avg": round(avg_funding, 8),
            "positive_count": positive_funding,
            "negative_count": negative_funding,
            "positive_pct": round(positive_funding / n * 100.0, 2),
            "negative_pct": round(negative_funding / n * 100.0, 2),
        },
        "change24h": {
            "avg": round(avg_change, 6),
            "positive_count": positive_change,
            "negative_count": negative_change,
            "positive_pct": round(pos_change_pct, 2),
            "negative_pct": round(neg_change_pct, 2),
        },
        "oi": {
            "symbols_with_holding": len(holding_values),
            "total_holding_raw": round(sum(holding_values), 4),
            "avg_holding_raw": round(sum(holding_values) / len(holding_values), 4) if holding_values else 0.0,
        },
        "pressure": pressure,
        "warnings": warnings,
    }


def _heatmap_context(heatmap_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    s = heatmap_snapshot.get("summary") or {}
    bias = _safe_str(s.get("bias"), "unknown")
    net = _safe_float(s.get("net_bias_score"), 0.0)
    if bias in {"strong_bullish", "mild_bullish"}:
        direction = "bullish"
    elif bias in {"strong_bearish", "mild_bearish"}:
        direction = "bearish"
    elif bias in {"mixed_neutral", "neutral"}:
        direction = "neutral"
    else:
        direction = "unknown"
    return {"available": bool(s), "bias": bias, "direction": direction, "net_bias_score": net, "summary": s}


def _ichimoku_breadth(ichimoku_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    s = ichimoku_snapshot.get("summary") or {}
    available_count = _safe_int(s.get("available_count"), 0)
    cloud_counts = s.get("cloud_state_counts") or {}
    trend_counts = s.get("trend_bias_counts") or {}
    long_counts = s.get("long_support_counts") or {}
    short_counts = s.get("short_support_counts") or {}
    denom = max(1, available_count)

    above_pct = _safe_int(cloud_counts.get("above_cloud"), 0) / denom * 100.0
    below_pct = _safe_int(cloud_counts.get("below_cloud"), 0) / denom * 100.0
    inside_pct = _safe_int(cloud_counts.get("inside_cloud"), 0) / denom * 100.0
    bullish_pct = _safe_int(trend_counts.get("bullish"), 0) / denom * 100.0
    bearish_pct = _safe_int(trend_counts.get("bearish"), 0) / denom * 100.0
    long_support_pct = _safe_int(long_counts.get("supportive"), 0) / denom * 100.0
    short_support_pct = _safe_int(short_counts.get("supportive"), 0) / denom * 100.0

    if bullish_pct >= 55 and above_pct >= 55:
        bias = "bullish_breadth"
    elif bearish_pct >= 55 and below_pct >= 55:
        bias = "bearish_breadth"
    elif inside_pct >= 25:
        bias = "cloud_uncertainty"
    else:
        bias = "mixed_breadth"

    return {
        "available": bool(s),
        "symbols_count": _safe_int(s.get("symbols_count"), 0),
        "available_count": available_count,
        "bias": bias,
        "above_cloud_pct": round(above_pct, 2),
        "below_cloud_pct": round(below_pct, 2),
        "inside_cloud_pct": round(inside_pct, 2),
        "bullish_pct": round(bullish_pct, 2),
        "bearish_pct": round(bearish_pct, 2),
        "long_support_pct": round(long_support_pct, 2),
        "short_support_pct": round(short_support_pct, 2),
        "raw_summary": s,
    }


def _fusion_pressure(context_fusion_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    s = context_fusion_snapshot.get("summary") or {}
    ss = s.get("strategy_summary") or {}
    counts = s.get("final_view_counts") or {}

    ready_allowed = _safe_int(ss.get("ready_allowed_count"), 0)
    ready_blocked = _safe_int(ss.get("ready_blocked_count"), 0)
    raw_no_ea = _safe_int(ss.get("raw_ready_no_ea_count"), 0)
    ea_counts = ss.get("ea_counts") or {}
    ea_b = _safe_int(ea_counts.get("B"), 0)

    active_candidates = (
        _safe_int(counts.get("ENTRY_CANDIDATE_STRONG"), 0)
        + _safe_int(counts.get("RAW_CANDIDATE_WAIT_EA_GOOD_ZONE"), 0)
        + _safe_int(counts.get("POLICY_BLOCKED"), 0)
        + _safe_int(counts.get("RAW_CANDIDATE_WAIT_EA"), 0)
    )

    if ready_allowed > 0:
        pressure = "entry_allowed"
    elif active_candidates >= 5:
        pressure = "candidate_pressure"
    elif ready_blocked > 0 or raw_no_ea > 0:
        pressure = "near_miss_pressure"
    else:
        pressure = "low_entry_pressure"

    return {
        "available": bool(s),
        "pressure": pressure,
        "final_view_counts": counts,
        "ready_allowed_count": ready_allowed,
        "ready_blocked_count": ready_blocked,
        "raw_ready_no_ea_count": raw_no_ea,
        "ea_b_count": ea_b,
        "strategy_summary": ss,
    }


def classify_macro_regime(*, heatmap: Dict[str, Any], ichimoku: Dict[str, Any], futures_pressure: Dict[str, Any], fusion: Dict[str, Any]) -> Dict[str, Any]:
    score = 50
    reasons, warnings = [], []

    if heatmap.get("direction") == "bullish":
        score += 16
        reasons.append(f"heatmap_bullish={heatmap.get('bias')}")
    elif heatmap.get("direction") == "bearish":
        score -= 16
        reasons.append(f"heatmap_bearish={heatmap.get('bias')}")
    elif heatmap.get("direction") == "neutral":
        warnings.append(f"heatmap_neutral={heatmap.get('bias')}")

    if ichimoku.get("bias") == "bullish_breadth":
        score += 14
        reasons.append(f"ichimoku_bullish_breadth={ichimoku.get('bullish_pct')}%")
    elif ichimoku.get("bias") == "bearish_breadth":
        score -= 14
        reasons.append(f"ichimoku_bearish_breadth={ichimoku.get('bearish_pct')}%")
    elif ichimoku.get("bias") == "cloud_uncertainty":
        score -= 4
        warnings.append(f"ichimoku_cloud_uncertainty={ichimoku.get('inside_cloud_pct')}%")
    elif ichimoku.get("bias") == "mixed_breadth":
        warnings.append("ichimoku_mixed_breadth")

    fp = futures_pressure.get("pressure")
    if fp == "risk_on_futures":
        score += 8
        reasons.append("futures_risk_on")
    elif fp == "risk_off_futures":
        score -= 8
        reasons.append("futures_risk_off")
    elif fp == "crowded_funding":
        warnings.append("futures_crowded_funding")

    if fusion.get("pressure") == "entry_allowed":
        reasons.append("vortex_ready_allowed")
    elif fusion.get("pressure") == "candidate_pressure":
        reasons.append("vortex_candidate_pressure")
    elif fusion.get("pressure") == "near_miss_pressure":
        warnings.append("vortex_near_miss_pressure")

    score = max(0, min(100, int(round(score))))

    if score >= 68:
        regime = "risk_on_bullish"
        recommendation = {"long_permission": "normal", "short_permission": "reduced", "risk_mode": "normal"}
    elif score <= 32:
        regime = "risk_off_bearish"
        recommendation = {"long_permission": "reduced", "short_permission": "normal", "risk_mode": "defensive"}
    elif 43 <= score <= 57:
        regime = "mixed_neutral"
        recommendation = {"long_permission": "selective", "short_permission": "selective", "risk_mode": "selective"}
    elif score > 57:
        regime = "mild_risk_on"
        recommendation = {"long_permission": "selective_plus", "short_permission": "reduced", "risk_mode": "normal"}
    else:
        regime = "mild_risk_off"
        recommendation = {"long_permission": "reduced", "short_permission": "selective_plus", "risk_mode": "defensive"}

    return {"regime": regime, "confidence": score, "recommendation": recommendation, "reasons": reasons[:12], "warnings": warnings[:12]}


def build_macro_regime_snapshot(
    *,
    heatmap_snapshot: Optional[Dict[str, Any]] = None,
    ichimoku_snapshot: Optional[Dict[str, Any]] = None,
    context_fusion_snapshot: Optional[Dict[str, Any]] = None,
    dedup_summary: Optional[Dict[str, Any]] = None,
    futures_tickers_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    heatmap_snapshot = heatmap_snapshot if heatmap_snapshot is not None else _load_json(HEATMAP_PATH)
    ichimoku_snapshot = ichimoku_snapshot if ichimoku_snapshot is not None else _load_json(ICHIMOKU_PATH)
    context_fusion_snapshot = context_fusion_snapshot if context_fusion_snapshot is not None else _load_json(CONTEXT_FUSION_PATH)
    dedup_summary = dedup_summary if dedup_summary is not None else _load_json(DEDUP_SUMMARY_PATH)
    futures_tickers_payload = futures_tickers_payload if futures_tickers_payload is not None else fetch_bitget_futures_tickers()

    heatmap = _heatmap_context(heatmap_snapshot)
    ichimoku = _ichimoku_breadth(ichimoku_snapshot)
    futures_pressure = analyze_futures_pressure(futures_tickers_payload)
    fusion = _fusion_pressure(context_fusion_snapshot)
    regime = classify_macro_regime(heatmap=heatmap, ichimoku=ichimoku, futures_pressure=futures_pressure, fusion=fusion)

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "regime": regime.get("regime"),
        "confidence": regime.get("confidence"),
        "recommendation": regime.get("recommendation"),
        "heatmap": heatmap,
        "ichimoku_breadth": ichimoku,
        "futures_pressure": futures_pressure,
        "vortex_pressure": fusion,
        "dedup_summary": {
            "total_seen": (dedup_summary or {}).get("total_seen"),
            "total_written": (dedup_summary or {}).get("total_written"),
            "total_suppressed": (dedup_summary or {}).get("total_suppressed"),
            "unique_keys": (dedup_summary or {}).get("unique_keys"),
            "top_policy": (dedup_summary or {}).get("top_policy"),
        },
        "reasons": regime.get("reasons", []),
        "warnings": regime.get("warnings", []),
    }


async def macro_regime_loop(state=None, logger=None) -> None:
    interval = 120
    while True:
        try:
            tickers_payload = await asyncio.to_thread(fetch_bitget_futures_tickers)
            snapshot = build_macro_regime_snapshot(futures_tickers_payload=tickers_payload)
            _write_json_atomic(LATEST_PATH, snapshot)
            _append_jsonl(SUMMARY_PATH, {
                "ts": snapshot.get("ts"),
                "schema_version": SCHEMA_VERSION,
                "regime": snapshot.get("regime"),
                "confidence": snapshot.get("confidence"),
                "recommendation": snapshot.get("recommendation"),
                "heatmap_bias": (snapshot.get("heatmap") or {}).get("bias"),
                "ichimoku_bias": (snapshot.get("ichimoku_breadth") or {}).get("bias"),
                "futures_pressure": (snapshot.get("futures_pressure") or {}).get("pressure"),
                "vortex_pressure": (snapshot.get("vortex_pressure") or {}).get("pressure"),
                "warnings": snapshot.get("warnings", []),
            })

            if state:
                try:
                    await state.add_sys_log(
                        "🌐 [MACRO_REGIME]",
                        f"{snapshot.get('regime')} conf={snapshot.get('confidence')} | heatmap={(snapshot.get('heatmap') or {}).get('bias')} | ichi={(snapshot.get('ichimoku_breadth') or {}).get('bias')} | fut={(snapshot.get('futures_pressure') or {}).get('pressure')}",
                    )
                except Exception:
                    pass
            if logger:
                logger.info("MACRO_REGIME", "snapshot updated", {"regime": snapshot.get("regime"), "confidence": snapshot.get("confidence")})
        except Exception as exc:
            if logger:
                logger.warning("MACRO_REGIME", "loop failed", {"error": _safe_str(exc)[:220]})
            if state:
                try:
                    await state.add_sys_log("❌ [MACRO_REGIME]", _safe_str(exc)[:220])
                except Exception:
                    pass
        await asyncio.sleep(interval)
