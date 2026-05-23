"""
VORTEX v1.8.20a Entry Argument Engine (shadow-only).

Purpose:
- build an explicit evidence chain for every confirmed futures entry;
- grade the entry without blocking live trading yet;
- persist decisions for later analytics.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from validators import safe_float, safe_str, safe_bool
except Exception:  # pragma: no cover - defensive fallback
    def safe_float(v: Any, default: float = 0.0) -> float:
        try:
            if v is None or v == "":
                return float(default)
            return float(v)
        except Exception:
            return float(default)

    def safe_str(v: Any, default: str = "") -> str:
        try:
            if v is None:
                return default
            return str(v)
        except Exception:
            return default

    def safe_bool(v: Any, default: bool = False) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return default
        return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


SCHEMA = "vortex.entry_argument_decision.v1"
SCHEMA_VERSION = "1.8.20a"
DEFAULT_PATH = Path("_runtime/entry_argument_decisions.jsonl")


def _round(v: Any, n: int = 6) -> float:
    try:
        return round(float(v), n)
    except Exception:
        return 0.0


def _append_unique(arr: List[str], text: str) -> None:
    text = safe_str(text).strip()
    if text and text not in arr:
        arr.append(text)


def _estimate_range_pct(current: Dict[str, Any], price: float, atr: float) -> float:
    raw = safe_float(
        current.get("range_pct", current.get("range_24h_pct", current.get("h24_range_pct"))),
        0.0,
    )
    if raw > 0:
        return raw
    high = safe_float(current.get("high_24h", current.get("recent_high")), 0.0)
    low = safe_float(current.get("low_24h", current.get("recent_low")), 0.0)
    if high > 0 and low > 0 and high > low:
        mid = max(price, (high + low) / 2.0)
        if mid > 0:
            return abs(high - low) / mid * 100.0
    if price > 0 and atr > 0:
        return atr / price * 100.0
    return 0.0


def _estimate_change_pct(current: Dict[str, Any], price: float) -> float:
    raw = safe_float(
        current.get("change_pct", current.get("change_24h_pct", current.get("h24_change_pct", current.get("price_change_pct")))),
        0.0,
    )
    if raw != 0.0:
        return raw
    open_24h = safe_float(current.get("open_24h"), 0.0)
    if open_24h > 0 and price > 0:
        return (price - open_24h) / open_24h * 100.0
    return 0.0


def _rr_for_ladder(side: str, entry: float, ladder: Optional[Dict[str, Any]]) -> Dict[str, float]:
    if not ladder or entry <= 0:
        return {"tp0_rr": 0.0, "tp1_rr": 0.0, "tp2_rr": 0.0, "risk_abs": 0.0}

    side_u = safe_str(side).upper()
    sl = safe_float(ladder.get("sl"), 0.0)
    tp0 = safe_float(ladder.get("tp0"), 0.0)
    tp1 = safe_float(ladder.get("tp"), 0.0)
    tp2 = safe_float(ladder.get("tp2"), 0.0)

    if side_u == "LONG":
        risk = max(entry - sl, 0.0)
        gains = [max(tp0 - entry, 0.0), max(tp1 - entry, 0.0), max(tp2 - entry, 0.0)]
    else:
        risk = max(sl - entry, 0.0)
        gains = [max(entry - tp0, 0.0), max(entry - tp1, 0.0), max(entry - tp2, 0.0)]

    if risk <= 0:
        return {"tp0_rr": 0.0, "tp1_rr": 0.0, "tp2_rr": 0.0, "risk_abs": 0.0}

    return {
        "tp0_rr": _round(gains[0] / risk, 4),
        "tp1_rr": _round(gains[1] / risk, 4),
        "tp2_rr": _round(gains[2] / risk, 4),
        "risk_abs": _round(risk, 8),
    }


def evaluate_entry_argument(
    symbol: str,
    side: str,
    setup_type: str,
    analysis: Optional[Dict[str, Any]],
    current: Optional[Dict[str, Any]],
    ladder: Optional[Dict[str, Any]] = None,
    macro_filter: str = "allow_all",
    watch: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a structured entry thesis. Shadow-only: never blocks by itself."""

    current = current or {}
    analysis = analysis or {}
    watch = watch or {}
    symbol_u = safe_str(symbol).upper()
    side_u = safe_str(side).upper()
    setup = safe_str(setup_type or analysis.get("setup_type") or watch.get("setup_type"))

    price = safe_float(current.get("price"), safe_float(ladder.get("price") if ladder else 0.0, 0.0))
    atr = safe_float(current.get("atr"), safe_float(ladder.get("atr") if ladder else 0.0, 0.0))
    ema20 = safe_float(current.get("ema20"), 0.0)
    ema50 = safe_float(current.get("ema50"), 0.0)
    rsi = safe_float(current.get("rsi_main"), 50.0)
    slope = safe_float(current.get("rsi_slope"), 0.0)
    adx = safe_float(current.get("adx"), 0.0)
    vol_ratio = safe_float(current.get("vol_ratio"), 1.0)
    trend_4h = safe_str(current.get("trend_4h"), "neutral").lower()
    trend_bias_1h = safe_str(current.get("trend_bias_1h"), "neutral").lower()
    breakout = safe_bool(current.get("breakout"), False)
    breakout_dir = safe_str(current.get("breakout_dir"), "").lower()
    recent_high = safe_float(current.get("recent_high"), 0.0)
    recent_low = safe_float(current.get("recent_low"), 0.0)
    range_pct = _estimate_range_pct(current, price, atr)
    change_pct = _estimate_change_pct(current, price)

    args_for: List[str] = []
    args_against: List[str] = []
    critical_blocks: List[str] = []
    tags: List[str] = []
    confidence = 0

    # Market / direction context
    if side_u == "LONG":
        if trend_4h in {"up", "strong_up", "bull", "bullish"}:
            confidence += 16; _append_unique(args_for, "4H trend aligned LONG")
        elif trend_4h in {"down", "strong_down", "bear", "bearish"}:
            confidence -= 18; _append_unique(args_against, "4H trend against LONG")
        if trend_bias_1h == "up":
            confidence += 8; _append_unique(args_for, "1H bias aligned LONG")
        if price > 0 and ema20 > 0 and price > ema20:
            confidence += 8; _append_unique(args_for, "price above EMA20")
        if ema20 > 0 and ema50 > 0 and ema20 >= ema50:
            confidence += 6; _append_unique(args_for, "EMA20 above/near EMA50")
        if rsi >= 50:
            confidence += 5; _append_unique(args_for, "RSI bullish")
        if rsi >= 78:
            confidence -= 14; _append_unique(args_against, "RSI near long exhaustion")
    elif side_u == "SHORT":
        if trend_4h in {"down", "strong_down", "bear", "bearish"}:
            confidence += 16; _append_unique(args_for, "4H trend aligned SHORT")
        elif trend_4h in {"up", "strong_up", "bull", "bullish"}:
            confidence -= 18; _append_unique(args_against, "4H trend against SHORT")
        if trend_bias_1h == "down":
            confidence += 8; _append_unique(args_for, "1H bias aligned SHORT")
        if price > 0 and ema20 > 0 and price < ema20:
            confidence += 8; _append_unique(args_for, "price below EMA20")
        if ema20 > 0 and ema50 > 0 and ema20 <= ema50:
            confidence += 6; _append_unique(args_for, "EMA20 below/near EMA50")
        if rsi <= 50:
            confidence += 5; _append_unique(args_for, "RSI bearish")
        if rsi <= 22:
            confidence -= 14; _append_unique(args_against, "RSI near short exhaustion")
    else:
        confidence -= 50; _append_unique(critical_blocks, "missing direction")

    if macro_filter == "block_longs" and side_u == "LONG":
        confidence -= 40; _append_unique(critical_blocks, "macro blocks longs")
    if macro_filter == "block_shorts" and side_u == "SHORT":
        confidence -= 40; _append_unique(critical_blocks, "macro blocks shorts")

    # Impulse / momentum quality
    if adx >= 25:
        confidence += 8; _append_unique(args_for, f"ADX trend strength {adx:.1f}")
    elif adx < 15:
        confidence -= 12; _append_unique(args_against, f"flat ADX {adx:.1f}")

    if vol_ratio >= 2.0:
        confidence += 8; _append_unique(args_for, f"volume impulse {vol_ratio:.2f}x")
    elif vol_ratio >= 1.15:
        confidence += 5; _append_unique(args_for, f"volume confirmed {vol_ratio:.2f}x")
    elif vol_ratio < 0.8:
        confidence -= 8; _append_unique(args_against, f"weak volume {vol_ratio:.2f}x")

    if abs(change_pct) >= 3.0:
        confidence += 7; _append_unique(args_for, f"directional move {change_pct:.2f}%")
    if range_pct >= 7.0:
        confidence += 5; _append_unique(args_for, f"range expansion {range_pct:.2f}%")

    # Late / exhaustion risk
    if range_pct >= 18.0:
        confidence -= 12; _append_unique(args_against, f"range overextended {range_pct:.2f}%")
        tags.append("late_risk")
    if abs(change_pct) >= 14.0:
        confidence -= 12; _append_unique(args_against, f"change overextended {change_pct:.2f}%")
        tags.append("late_risk")

    if price > 0 and ema20 > 0:
        ema_dist_pct = abs(price - ema20) / ema20 * 100.0
        if ema_dist_pct <= 1.2:
            confidence += 5; _append_unique(args_for, f"entry near EMA20 {ema_dist_pct:.2f}%")
        elif ema_dist_pct >= 5.0:
            confidence -= 10; _append_unique(args_against, f"entry far from EMA20 {ema_dist_pct:.2f}%")
            tags.append("late_risk")
    else:
        ema_dist_pct = 0.0

    # Structure approximation
    structure_confirmed = False
    if breakout and breakout_dir in {"up", "down"}:
        if (side_u == "LONG" and breakout_dir == "up") or (side_u == "SHORT" and breakout_dir == "down"):
            confidence += 10; structure_confirmed = True; _append_unique(args_for, f"breakout structure {breakout_dir}")
        else:
            confidence -= 12; _append_unique(args_against, f"breakout direction against entry {breakout_dir}")

    invalidation_price = safe_float(analysis.get("invalidation_price"), 0.0)
    invalidation_reason = "analysis invalidation"
    if invalidation_price <= 0 and ladder:
        invalidation_price = safe_float(ladder.get("sl"), 0.0)
        invalidation_reason = "ATR stop invalidation"
    if invalidation_price <= 0:
        if side_u == "LONG" and recent_low > 0:
            invalidation_price = recent_low
            invalidation_reason = "local swing low"
        elif side_u == "SHORT" and recent_high > 0:
            invalidation_price = recent_high
            invalidation_reason = "local swing high"

    if invalidation_price > 0:
        confidence += 5; _append_unique(args_for, f"invalidation defined: {invalidation_reason}")
    else:
        confidence -= 10; _append_unique(args_against, "invalidation not defined")

    # RR quality
    rr = _rr_for_ladder(side_u, price, ladder)
    if rr.get("tp1_rr", 0.0) >= 1.2 and rr.get("tp2_rr", 0.0) >= 1.8:
        confidence += 8; _append_unique(args_for, f"RR acceptable tp1={rr['tp1_rr']:.2f} tp2={rr['tp2_rr']:.2f}")
    elif ladder:
        confidence -= 10; _append_unique(args_against, f"RR weak tp1={rr['tp1_rr']:.2f} tp2={rr['tp2_rr']:.2f}")

    # Setup-specific concerns
    if setup.startswith("momentum") and not structure_confirmed:
        confidence -= 8; _append_unique(args_against, "momentum without explicit structure/retest")
        tags.append("needs_structure")
    if setup.startswith("trend") and (trend_4h in {"neutral", ""}):
        confidence -= 6; _append_unique(args_against, "trend setup without clear 4H context")

    raw_confidence = confidence
    confidence = max(0, min(100, int(round(confidence))))

    if critical_blocks or confidence < 45:
        grade = "D"
        decision = "BLOCK_SHADOW"
    elif confidence < 60:
        grade = "C"
        decision = "SHADOW_ONLY"
    elif confidence < 78:
        grade = "B"
        decision = "ALLOW_SHADOW"
    else:
        grade = "A"
        decision = "STRONG_ALLOW_SHADOW"

    if grade in {"A", "B"}:
        entry_quality = "tradable"
    elif grade == "C":
        entry_quality = "weak_watch_only"
    else:
        entry_quality = "avoid"

    summary = f"EA:{grade}/{confidence} {decision}"
    verdict_reason = "; ".join(args_for[:3] + (["against: " + ", ".join(args_against[:2])] if args_against else []))

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "symbol": symbol_u,
        "side": side_u,
        "setup_type": setup,
        "decision": decision,
        "entry_grade": grade,
        "entry_quality": entry_quality,
        "confidence": confidence,
        "raw_confidence": raw_confidence,
        "summary": summary,
        "arguments_for": args_for,
        "arguments_against": args_against,
        "critical_blocks": critical_blocks,
        "tags": sorted(set(tags)),
        "verdict_reason": verdict_reason,
        "market_context": {
            "macro_filter": macro_filter,
            "trend_4h": trend_4h,
            "trend_bias_1h": trend_bias_1h,
            "adx": _round(adx, 2),
        },
        "timing": {
            "range_pct": _round(range_pct, 4),
            "change_pct": _round(change_pct, 4),
            "ema20_distance_pct": _round(ema_dist_pct, 4),
            "rsi": _round(rsi, 2),
            "rsi_slope": _round(slope, 4),
            "late_risk": "late_risk" in tags,
        },
        "volume": {
            "vol_ratio": _round(vol_ratio, 4),
        },
        "structure": {
            "breakout": bool(breakout),
            "breakout_dir": breakout_dir,
            "structure_confirmed": bool(structure_confirmed),
            "recent_high": _round(recent_high, 8),
            "recent_low": _round(recent_low, 8),
        },
        "invalidation": {
            "price": _round(invalidation_price, 8),
            "reason": invalidation_reason if invalidation_price > 0 else "missing",
        },
        "rr": rr,
        "analysis_score": safe_float(analysis.get("score"), 0.0),
        "analysis_args_text": safe_str(analysis.get("args_text")),
        "watch_confirmation_reason": safe_str(watch.get("confirmation_reason")),
    }


def record_entry_argument(decision: Dict[str, Any], path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n")


def evaluate_and_record_entry_argument(
    symbol: str,
    side: str,
    setup_type: str,
    analysis: Optional[Dict[str, Any]],
    current: Optional[Dict[str, Any]],
    ladder: Optional[Dict[str, Any]] = None,
    macro_filter: str = "allow_all",
    watch: Optional[Dict[str, Any]] = None,
    path: Path = DEFAULT_PATH,
) -> Dict[str, Any]:
    decision = evaluate_entry_argument(
        symbol=symbol,
        side=side,
        setup_type=setup_type,
        analysis=analysis,
        current=current,
        ladder=ladder,
        macro_filter=macro_filter,
        watch=watch,
    )
    record_entry_argument(decision, path=path)
    return decision
