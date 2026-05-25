import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
from snapshot_guard import should_write_latest_snapshot


SCHEMA = "vortex.market_heatmap.v1"
SCHEMA_VERSION = "1.8.21k-a"

LATEST_PATH = Path("_runtime/market_heatmap_latest.json")
SUMMARY_PATH = Path("_runtime/market_heatmap_summary.jsonl")


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


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((float(part) / float(total)) * 100.0, 2)


def _classify_symbol(symbol: str, ta: Dict[str, Any]) -> Dict[str, Any]:
    symbol = _safe_str(symbol).upper()
    ta = dict(ta or {})

    price = _safe_float(ta.get("price"), 0.0)
    trend_4h = _safe_str(ta.get("trend_4h"), "").lower()
    adx = _safe_float(ta.get("adx"), 0.0)
    rsi = _safe_float(ta.get("rsi_main"), 50.0)
    rsi_slope = _safe_float(ta.get("rsi_slope"), 0.0)
    ema20 = _safe_float(ta.get("ema20"), 0.0)
    ema50 = _safe_float(ta.get("ema50"), 0.0)
    vol_ratio = _safe_float(ta.get("vol_ratio"), 0.0)
    atr_pct = _safe_float(ta.get("atr_pct"), 0.0)

    above_ema20 = price > 0 and ema20 > 0 and price >= ema20
    above_ema50 = price > 0 and ema50 > 0 and price >= ema50
    below_ema20 = price > 0 and ema20 > 0 and price < ema20
    below_ema50 = price > 0 and ema50 > 0 and price < ema50

    trend_up = trend_4h == "up"
    trend_down = trend_4h == "down"

    bullish = bool(trend_up and above_ema20 and rsi >= 50)
    bearish = bool(trend_down and below_ema20 and rsi <= 50)

    long_context = bool(
        trend_up
        and above_ema20
        and above_ema50
        and rsi >= 50
        and rsi_slope >= -0.3
        and vol_ratio >= 0.8
    )
    short_context = bool(
        trend_down
        and below_ema20
        and below_ema50
        and rsi <= 50
        and rsi_slope <= 0.3
        and vol_ratio >= 0.8
    )

    if long_context:
        local_bias = "long_context"
    elif short_context:
        local_bias = "short_context"
    elif bullish:
        local_bias = "bullish_watch"
    elif bearish:
        local_bias = "bearish_watch"
    elif adx < 18:
        local_bias = "flat_or_chop"
    else:
        local_bias = "mixed"

    return {
        "symbol": symbol,
        "price": price,
        "trend_4h": trend_4h,
        "adx": adx,
        "rsi_main": rsi,
        "rsi_slope": rsi_slope,
        "ema20": ema20,
        "ema50": ema50,
        "vol_ratio": vol_ratio,
        "atr_pct": atr_pct,
        "above_ema20": above_ema20,
        "above_ema50": above_ema50,
        "below_ema20": below_ema20,
        "below_ema50": below_ema50,
        "trend_up": trend_up,
        "trend_down": trend_down,
        "rsi_bullish": rsi >= 55,
        "rsi_bearish": rsi <= 45,
        "volume_ok": vol_ratio >= 0.8,
        "high_adx": adx >= 35,
        "long_context": long_context,
        "short_context": short_context,
        "local_bias": local_bias,
    }


def build_market_heatmap_snapshot(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    market = dashboard.get("market", {}) or {}
    ta_data = market.get("ta_data", {}) or {}
    prices = market.get("prices", {}) or {}

    symbols: List[Dict[str, Any]] = []
    for symbol in sorted(ta_data.keys()):
        ta = dict(ta_data.get(symbol, {}) or {})
        if symbol in prices and "price" not in ta:
            ta["price"] = prices.get(symbol)
        symbols.append(_classify_symbol(symbol, ta))

    total = len(symbols)

    counts = Counter()
    for s in symbols:
        counts["trend_up"] += 1 if s["trend_up"] else 0
        counts["trend_down"] += 1 if s["trend_down"] else 0
        counts["above_ema20"] += 1 if s["above_ema20"] else 0
        counts["above_ema50"] += 1 if s["above_ema50"] else 0
        counts["below_ema20"] += 1 if s["below_ema20"] else 0
        counts["below_ema50"] += 1 if s["below_ema50"] else 0
        counts["rsi_bullish"] += 1 if s["rsi_bullish"] else 0
        counts["rsi_bearish"] += 1 if s["rsi_bearish"] else 0
        counts["volume_ok"] += 1 if s["volume_ok"] else 0
        counts["high_adx"] += 1 if s["high_adx"] else 0
        counts["long_context"] += 1 if s["long_context"] else 0
        counts["short_context"] += 1 if s["short_context"] else 0

    local_bias_counts = dict(Counter(s["local_bias"] for s in symbols))

    long_pressure = (
        _pct(counts["trend_up"], total) * 0.25
        + _pct(counts["above_ema20"], total) * 0.25
        + _pct(counts["above_ema50"], total) * 0.20
        + _pct(counts["rsi_bullish"], total) * 0.15
        + _pct(counts["long_context"], total) * 0.15
    )

    short_pressure = (
        _pct(counts["trend_down"], total) * 0.25
        + _pct(counts["below_ema20"], total) * 0.25
        + _pct(counts["below_ema50"], total) * 0.20
        + _pct(counts["rsi_bearish"], total) * 0.15
        + _pct(counts["short_context"], total) * 0.15
    )

    net_bias_score = round(long_pressure - short_pressure, 2)

    if net_bias_score >= 20:
        bias = "strong_bullish"
    elif net_bias_score >= 8:
        bias = "mild_bullish"
    elif net_bias_score <= -20:
        bias = "strong_bearish"
    elif net_bias_score <= -8:
        bias = "mild_bearish"
    else:
        bias = "mixed_neutral"

    if total == 0:
        bias = "no_data"

    top_long = sorted(
        [s for s in symbols if s["long_context"] or s["local_bias"] == "bullish_watch"],
        key=lambda x: (x["long_context"], x["adx"], x["rsi_main"], x["vol_ratio"]),
        reverse=True,
    )[:20]

    top_short = sorted(
        [s for s in symbols if s["short_context"] or s["local_bias"] == "bearish_watch"],
        key=lambda x: (x["short_context"], x["adx"], 100.0 - x["rsi_main"], x["vol_ratio"]),
        reverse=True,
    )[:20]

    summary = {
        "symbols_count": total,
        "prices_count": len(prices),
        "ta_symbols_count": len(ta_data),
        "bias": bias,
        "net_bias_score": net_bias_score,
        "long_pressure": round(long_pressure, 2),
        "short_pressure": round(short_pressure, 2),
        "trend_up_pct": _pct(counts["trend_up"], total),
        "trend_down_pct": _pct(counts["trend_down"], total),
        "above_ema20_pct": _pct(counts["above_ema20"], total),
        "above_ema50_pct": _pct(counts["above_ema50"], total),
        "below_ema20_pct": _pct(counts["below_ema20"], total),
        "below_ema50_pct": _pct(counts["below_ema50"], total),
        "rsi_bullish_pct": _pct(counts["rsi_bullish"], total),
        "rsi_bearish_pct": _pct(counts["rsi_bearish"], total),
        "volume_ok_pct": _pct(counts["volume_ok"], total),
        "high_adx_pct": _pct(counts["high_adx"], total),
        "long_context_count": int(counts["long_context"]),
        "short_context_count": int(counts["short_context"]),
        "local_bias_counts": local_bias_counts,
    }

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "summary": summary,
        "top_long_context": top_long,
        "top_short_context": top_short,
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
                "adx": x.get("adx"),
                "rsi_main": x.get("rsi_main"),
                "vol_ratio": x.get("vol_ratio"),
                "local_bias": x.get("local_bias"),
            }
            for x in snapshot.get("top_long_context", [])[:10]
        ],
        "top_short": [
            {
                "symbol": x.get("symbol"),
                "adx": x.get("adx"),
                "rsi_main": x.get("rsi_main"),
                "vol_ratio": x.get("vol_ratio"),
                "local_bias": x.get("local_bias"),
            }
            for x in snapshot.get("top_short_context", [])[:10]
        ],
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(compact, ensure_ascii=False, sort_keys=True) + "\n")


async def market_heatmap_loop(state, logger=None) -> None:
    interval = 60

    while True:
        try:
            dashboard = await state.get_dashboard_state()
            snapshot = build_market_heatmap_snapshot(dashboard)

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
                    "🌡️ [MARKET_HEATMAP]",
                    (
                        f"bias={summary.get('bias')} | "
                        f"net={summary.get('net_bias_score')} | "
                        f"long_ctx={summary.get('long_context_count')} | "
                        f"short_ctx={summary.get('short_context_count')} | "
                        f"symbols={summary.get('symbols_count')}"
                    ),
                )
            except Exception:
                pass

            if logger:
                logger.info("MARKET_HEATMAP", "snapshot updated", summary)

        except Exception as exc:
            try:
                await state.add_sys_log("❌ [MARKET_HEATMAP]", str(exc))
            except Exception:
                pass

            if logger:
                logger.warning("MARKET_HEATMAP", "heatmap loop failed", {"error": str(exc)})

        await asyncio.sleep(interval)
