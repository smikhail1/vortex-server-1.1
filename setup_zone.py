import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


SCHEMA = "vortex.setup_zone.v1"
SCHEMA_VERSION = "1.8.21k-b-r2"

LATEST_PATH = Path("_runtime/setup_zone_latest.json")
SUMMARY_PATH = Path("_runtime/setup_zone_summary.jsonl")


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


def _pct_dist(price: float, level: float) -> float:
    if price <= 0 or level <= 0:
        return 999.0
    return round(abs(price - level) / price * 100.0, 4)


def _range_position(price: float, low: float, high: float) -> float:
    if price <= 0 or high <= low:
        return 50.0
    value = (price - low) / (high - low) * 100.0
    return round(max(0.0, min(100.0, value)), 2)


def _zone_thresholds(atr_pct: float) -> Dict[str, float]:
    atr_pct = max(0.0, float(atr_pct or 0.0))
    return {
        "ema_near_pct": max(0.25, min(1.20, atr_pct * 0.45)),
        "level_near_pct": max(0.35, min(1.80, atr_pct * 0.65)),
        "middle_low": 40.0,
        "middle_high": 60.0,
        "high_zone": 78.0,
        "low_zone": 22.0,
    }


def classify_setup_zone(symbol: str, ta: Dict[str, Any]) -> Dict[str, Any]:
    symbol = _safe_str(symbol).upper()
    ta = dict(ta or {})

    price = _safe_float(ta.get("price"), 0.0)
    trend_4h = _safe_str(ta.get("trend_4h"), "").lower()
    ema20 = _safe_float(ta.get("ema20"), 0.0)
    ema50 = _safe_float(ta.get("ema50"), 0.0)
    recent_high = _safe_float(ta.get("recent_high"), 0.0)
    recent_low = _safe_float(ta.get("recent_low"), 0.0)
    atr_pct = _safe_float(ta.get("atr_pct"), 0.0)
    adx = _safe_float(ta.get("adx"), 0.0)
    rsi = _safe_float(ta.get("rsi_main"), 50.0)
    vol_ratio = _safe_float(ta.get("vol_ratio"), 0.0)

    thresholds = _zone_thresholds(atr_pct)

    dist_ema20_pct = _pct_dist(price, ema20)
    dist_ema50_pct = _pct_dist(price, ema50)
    dist_high_pct = _pct_dist(price, recent_high)
    dist_low_pct = _pct_dist(price, recent_low)

    near_ema20 = dist_ema20_pct <= thresholds["ema_near_pct"]
    near_ema50 = dist_ema50_pct <= thresholds["ema_near_pct"]
    near_recent_high = dist_high_pct <= thresholds["level_near_pct"]
    near_recent_low = dist_low_pct <= thresholds["level_near_pct"]

    range_position_pct = _range_position(price, recent_low, recent_high)
    middle_of_range = thresholds["middle_low"] <= range_position_pct <= thresholds["middle_high"]
    high_zone = range_position_pct >= thresholds["high_zone"]
    low_zone = range_position_pct <= thresholds["low_zone"]

    above_ema20 = price > 0 and ema20 > 0 and price >= ema20
    above_ema50 = price > 0 and ema50 > 0 and price >= ema50
    below_ema20 = price > 0 and ema20 > 0 and price < ema20
    below_ema50 = price > 0 and ema50 > 0 and price < ema50

    long_reasons: List[str] = []
    long_warnings: List[str] = []
    short_reasons: List[str] = []
    short_warnings: List[str] = []

    long_score = 0
    short_score = 0

    if trend_4h == "up":
        long_score += 20
        long_reasons.append("4H trend up")
    elif trend_4h == "down":
        long_warnings.append("4H trend down")

    if trend_4h == "down":
        short_score += 20
        short_reasons.append("4H trend down")
    elif trend_4h == "up":
        short_warnings.append("4H trend up")

    if above_ema50:
        long_score += 12
        long_reasons.append("price above EMA50")
    else:
        long_warnings.append("price not above EMA50")

    if below_ema50:
        short_score += 12
        short_reasons.append("price below EMA50")
    else:
        short_warnings.append("price not below EMA50")

    if near_ema20:
        long_score += 18
        short_score += 18
        long_reasons.append("price near EMA20")
        short_reasons.append("price near EMA20")

    if near_ema50:
        long_score += 10
        short_score += 10
        long_reasons.append("price near EMA50")
        short_reasons.append("price near EMA50")

    if near_recent_low:
        long_score += 18
        long_reasons.append("price near recent low/support")
        short_warnings.append("price near support")

    if near_recent_high:
        short_score += 18
        short_reasons.append("price near recent high/resistance")
        long_warnings.append("price near resistance")

    if low_zone:
        long_score += 10
        long_reasons.append("range low zone")
        short_warnings.append("range low zone, short late")
    elif high_zone:
        short_score += 10
        short_reasons.append("range high zone")
        long_warnings.append("range high zone, long late")
    elif middle_of_range:
        long_score -= 8
        short_score -= 8
        long_warnings.append("middle of range")
        short_warnings.append("middle of range")

    if above_ema20:
        long_score += 8
        long_reasons.append("price above EMA20")
    if below_ema20:
        short_score += 8
        short_reasons.append("price below EMA20")

    if vol_ratio >= 0.8:
        long_score += 6
        short_score += 6
    else:
        long_warnings.append("low volume ratio")
        short_warnings.append("low volume ratio")

    if adx >= 25:
        long_score += 5
        short_score += 5

    if rsi >= 70:
        long_warnings.append("RSI extended for long")
    if rsi <= 30:
        short_warnings.append("RSI extended for short")

    if near_recent_high:
        long_score -= 12
    if near_recent_low:
        short_score -= 12

    long_score = max(0, min(100, int(round(long_score))))
    short_score = max(0, min(100, int(round(short_score))))

    if long_score >= 65 and long_score >= short_score + 10:
        preferred_zone = "long_pullback_zone"
    elif short_score >= 65 and short_score >= long_score + 10:
        preferred_zone = "short_pullback_zone"
    elif middle_of_range:
        preferred_zone = "middle_no_trade_zone"
    elif high_zone:
        preferred_zone = "high_zone"
    elif low_zone:
        preferred_zone = "low_zone"
    else:
        preferred_zone = "neutral_zone"

    warnings = []
    if middle_of_range:
        warnings.append("middle_of_range")
    if near_recent_high:
        warnings.append("near_resistance")
    if near_recent_low:
        warnings.append("near_support")
    if vol_ratio < 0.8:
        warnings.append("low_volume")
    if atr_pct <= 0:
        warnings.append("atr_missing_or_zero")

    return {
        "symbol": symbol,
        "price": price,
        "trend_4h": trend_4h,
        "adx": adx,
        "rsi_main": rsi,
        "vol_ratio": vol_ratio,
        "atr_pct": atr_pct,
        "ema20": ema20,
        "ema50": ema50,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "range_position_pct": range_position_pct,
        "dist_ema20_pct": dist_ema20_pct,
        "dist_ema50_pct": dist_ema50_pct,
        "dist_high_pct": dist_high_pct,
        "dist_low_pct": dist_low_pct,
        "near_ema20": near_ema20,
        "near_ema50": near_ema50,
        "near_recent_high": near_recent_high,
        "near_recent_low": near_recent_low,
        "near_support": near_recent_low,
        "near_resistance": near_recent_high,
        "middle_of_range": middle_of_range,
        "high_zone": high_zone,
        "low_zone": low_zone,
        "above_ema20": above_ema20,
        "above_ema50": above_ema50,
        "below_ema20": below_ema20,
        "below_ema50": below_ema50,
        "long_zone_quality": long_score,
        "short_zone_quality": short_score,
        "preferred_zone": preferred_zone,
        "warnings": warnings,
        "long_reasons": long_reasons[:10],
        "long_warnings": long_warnings[:10],
        "short_reasons": short_reasons[:10],
        "short_warnings": short_warnings[:10],
        "thresholds": thresholds,
    }


def build_setup_zone_snapshot(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    market = dashboard.get("market", {}) or {}
    ta_data = market.get("ta_data", {}) or {}
    prices = market.get("prices", {}) or {}

    symbols: List[Dict[str, Any]] = []

    for symbol in sorted(ta_data.keys()):
        ta = dict(ta_data.get(symbol, {}) or {})
        if symbol in prices and "price" not in ta:
            ta["price"] = prices.get(symbol)
        symbols.append(classify_setup_zone(symbol, ta))

    zone_counts = Counter(x.get("preferred_zone") for x in symbols)
    warning_counts = Counter()
    for x in symbols:
        for w in x.get("warnings") or []:
            warning_counts[w] += 1

    top_long = sorted(symbols, key=lambda x: (x["long_zone_quality"], x["adx"], x["vol_ratio"]), reverse=True)[:20]
    top_short = sorted(symbols, key=lambda x: (x["short_zone_quality"], x["adx"], x["vol_ratio"]), reverse=True)[:20]

    summary = {
        "symbols_count": len(symbols),
        "prices_count": len(prices),
        "ta_symbols_count": len(ta_data),
        "zone_counts": dict(zone_counts),
        "warning_counts": dict(warning_counts),
        "long_zone_65_count": len([x for x in symbols if x["long_zone_quality"] >= 65]),
        "short_zone_65_count": len([x for x in symbols if x["short_zone_quality"] >= 65]),
        "middle_of_range_count": len([x for x in symbols if x["middle_of_range"]]),
        "near_support_count": len([x for x in symbols if x["near_support"]]),
        "near_resistance_count": len([x for x in symbols if x["near_resistance"]]),
    }

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "summary": summary,
        "top_long_zones": top_long,
        "top_short_zones": top_short,
        "symbols": symbols,
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
        "top_long": [
            {
                "symbol": x.get("symbol"),
                "long_zone_quality": x.get("long_zone_quality"),
                "preferred_zone": x.get("preferred_zone"),
                "range_position_pct": x.get("range_position_pct"),
                "near_ema20": x.get("near_ema20"),
                "near_support": x.get("near_support"),
                "warnings": x.get("warnings"),
            }
            for x in snapshot.get("top_long_zones", [])[:10]
        ],
        "top_short": [
            {
                "symbol": x.get("symbol"),
                "short_zone_quality": x.get("short_zone_quality"),
                "preferred_zone": x.get("preferred_zone"),
                "range_position_pct": x.get("range_position_pct"),
                "near_ema20": x.get("near_ema20"),
                "near_resistance": x.get("near_resistance"),
                "warnings": x.get("warnings"),
            }
            for x in snapshot.get("top_short_zones", [])[:10]
        ],
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(compact, ensure_ascii=False, sort_keys=True) + "\n")


async def setup_zone_loop(state, logger=None) -> None:
    interval = 60

    while True:
        try:
            dashboard = await state.get_dashboard_state()
            snapshot = build_setup_zone_snapshot(dashboard)

            write_json_atomic(LATEST_PATH, snapshot)
            append_summary(SUMMARY_PATH, snapshot)

            summary = snapshot.get("summary", {})
            try:
                await state.add_sys_log(
                    "🧭 [SETUP_ZONE]",
                    (
                        f"symbols={summary.get('symbols_count')} | "
                        f"long65={summary.get('long_zone_65_count')} | "
                        f"short65={summary.get('short_zone_65_count')} | "
                        f"middle={summary.get('middle_of_range_count')}"
                    ),
                )
            except Exception:
                pass

            if logger:
                logger.info("SETUP_ZONE", "snapshot updated", summary)

        except Exception as exc:
            try:
                await state.add_sys_log("❌ [SETUP_ZONE]", str(exc))
            except Exception:
                pass

            if logger:
                logger.warning("SETUP_ZONE", "setup zone loop failed", {"error": str(exc)})

        await asyncio.sleep(interval)
