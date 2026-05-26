import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from config import CONFIG

try:
    from validators import normalize_symbol, safe_float, safe_int, safe_str
except Exception:
    def safe_str(value: Any, default: str = "") -> str:
        try:
            return default if value is None else str(value)
        except Exception:
            return default

    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(default) if value is None else float(value)
        except Exception:
            return float(default)

    def safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(default) if value is None else int(float(value))
        except Exception:
            return int(default)

    def normalize_symbol(value: Any) -> str:
        return safe_str(value).strip().upper()


SCHEMA = "vortex.ichimoku_context.v1"
SCHEMA_VERSION = "1.8.21l-c"

LATEST_PATH = Path("_runtime/ichimoku_context_latest.json")
SUMMARY_PATH = Path("_runtime/ichimoku_context_summary.jsonl")


def _midpoint(values_high: List[float], values_low: List[float]) -> float:
    if not values_high or not values_low:
        return 0.0
    return (max(values_high) + min(values_low)) / 2.0


def _clean_candles(candles: List[Dict[str, Any]]) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    for c in candles or []:
        try:
            item = {
                "ts": safe_int(c.get("ts"), 0),
                "open": safe_float(c.get("open"), 0.0),
                "high": safe_float(c.get("high"), 0.0),
                "low": safe_float(c.get("low"), 0.0),
                "close": safe_float(c.get("close"), 0.0),
                "volume": safe_float(c.get("volume"), 0.0),
                "quote_volume": safe_float(c.get("quote_volume"), 0.0),
            }
            if item["high"] > 0 and item["low"] > 0 and item["close"] > 0 and item["high"] >= item["low"]:
                out.append(item)
        except Exception:
            continue
    out.sort(key=lambda x: x.get("ts", 0))
    return out


def calculate_ichimoku(
    candles: List[Dict[str, Any]],
    *,
    timeframe: str = "30m",
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
) -> Dict[str, Any]:
    clean = _clean_candles(candles)
    min_bars = max(tenkan_period, kijun_period, senkou_b_period)

    fallback = {
        "available": False,
        "timeframe": timeframe,
        "bars": len(clean),
        "reason": "not_enough_candles",
        "price": 0.0,
        "tenkan": 0.0,
        "kijun": 0.0,
        "senkou_a": 0.0,
        "senkou_b": 0.0,
        "cloud_top": 0.0,
        "cloud_bottom": 0.0,
        "cloud_state": "no_data",
        "tk_state": "no_data",
        "cloud_bias": "no_data",
        "trend_bias": "no_data",
        "long_support": "no_data",
        "short_support": "no_data",
        "quality": 0,
        "warnings": ["not_enough_candles"],
    }

    if len(clean) < min_bars:
        return fallback

    latest = clean[-1]
    price = safe_float(latest.get("close"), 0.0)
    if price <= 0:
        fallback["reason"] = "invalid_price"
        fallback["warnings"] = ["invalid_price"]
        return fallback

    h9 = [x["high"] for x in clean[-tenkan_period:]]
    l9 = [x["low"] for x in clean[-tenkan_period:]]
    h26 = [x["high"] for x in clean[-kijun_period:]]
    l26 = [x["low"] for x in clean[-kijun_period:]]
    h52 = [x["high"] for x in clean[-senkou_b_period:]]
    l52 = [x["low"] for x in clean[-senkou_b_period:]]

    tenkan = _midpoint(h9, l9)
    kijun = _midpoint(h26, l26)
    senkou_a = (tenkan + kijun) / 2.0
    senkou_b = _midpoint(h52, l52)

    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)

    if price > cloud_top:
        cloud_state = "above_cloud"
    elif price < cloud_bottom:
        cloud_state = "below_cloud"
    else:
        cloud_state = "inside_cloud"

    if tenkan > kijun:
        tk_state = "bullish"
    elif tenkan < kijun:
        tk_state = "bearish"
    else:
        tk_state = "neutral"

    if senkou_a > senkou_b:
        cloud_bias = "bullish"
    elif senkou_a < senkou_b:
        cloud_bias = "bearish"
    else:
        cloud_bias = "neutral"

    if cloud_state == "above_cloud" and tk_state == "bullish":
        trend_bias = "bullish"
    elif cloud_state == "below_cloud" and tk_state == "bearish":
        trend_bias = "bearish"
    elif cloud_state == "inside_cloud":
        trend_bias = "neutral"
    else:
        trend_bias = "mixed"

    warnings: List[str] = []
    if cloud_state == "inside_cloud":
        warnings.append("inside_cloud")

    kijun_dist_pct = abs(price - kijun) / price * 100.0 if price > 0 and kijun > 0 else 0.0
    if kijun_dist_pct >= 3.0:
        warnings.append("far_from_kijun")

    cloud_thickness_pct = (cloud_top - cloud_bottom) / price * 100.0 if price > 0 and cloud_top > 0 and cloud_bottom > 0 else 0.0
    if cloud_thickness_pct < 0.15:
        warnings.append("thin_cloud")

    def support_for_side(side: str) -> str:
        side = side.upper()
        if cloud_state == "inside_cloud":
            return "neutral"
        if side == "LONG":
            if cloud_state == "above_cloud" and tk_state in {"bullish", "neutral"}:
                return "supportive"
            if cloud_state == "below_cloud":
                return "against"
            return "neutral"
        if side == "SHORT":
            if cloud_state == "below_cloud" and tk_state in {"bearish", "neutral"}:
                return "supportive"
            if cloud_state == "above_cloud":
                return "against"
            return "neutral"
        return "neutral"

    long_support = support_for_side("LONG")
    short_support = support_for_side("SHORT")

    quality = 50
    if trend_bias in {"bullish", "bearish"}:
        quality += 12
    elif trend_bias == "mixed":
        quality -= 4
    elif trend_bias == "neutral":
        quality -= 8

    if cloud_bias == trend_bias and trend_bias in {"bullish", "bearish"}:
        quality += 6

    if tk_state in {"bullish", "bearish"}:
        quality += 4

    if "inside_cloud" in warnings:
        quality -= 12
    if "far_from_kijun" in warnings:
        quality -= 5
    if "thin_cloud" in warnings:
        quality -= 3

    quality = max(0, min(100, int(round(quality))))

    return {
        "available": True,
        "timeframe": timeframe,
        "bars": len(clean),
        "reason": "",
        "price": round(price, 8),
        "tenkan": round(tenkan, 8),
        "kijun": round(kijun, 8),
        "senkou_a": round(senkou_a, 8),
        "senkou_b": round(senkou_b, 8),
        "cloud_top": round(cloud_top, 8),
        "cloud_bottom": round(cloud_bottom, 8),
        "cloud_state": cloud_state,
        "tk_state": tk_state,
        "cloud_bias": cloud_bias,
        "trend_bias": trend_bias,
        "long_support": long_support,
        "short_support": short_support,
        "quality": quality,
        "kijun_dist_pct": round(kijun_dist_pct, 3),
        "cloud_thickness_pct": round(cloud_thickness_pct, 3),
        "warnings": warnings,
    }


async def _get_fut_symbols(state) -> List[str]:
    symbols: List[str] = []
    try:
        if hasattr(state, "get_pool"):
            pool = await state.get_pool("fut")
            symbols.extend(pool or [])
    except Exception:
        pass

    if not symbols:
        try:
            dash = await state.get_dashboard_state()
            symbols.extend((dash.get("system", {}) or {}).get("fut_pool", []) or [])
        except Exception:
            pass

    out: List[str] = []
    seen = set()
    for raw in symbols:
        sym = normalize_symbol(raw)
        if sym and sym not in seen:
            out.append(sym)
            seen.add(sym)
    return out


def build_ichimoku_snapshot_for_symbols(*, symbols: List[str], candle_service, market: str = "fut") -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for sym in symbols or []:
        symbol = normalize_symbol(sym)
        if not symbol:
            continue
        try:
            snap = candle_service.get_symbol_snapshot(symbol, market) if candle_service else {}
            c30 = (snap or {}).get("candles_30m", []) or []
            c4h = (snap or {}).get("candles_4h", []) or []

            item_30m = calculate_ichimoku(c30, timeframe="30m")
            item_4h = calculate_ichimoku(c4h, timeframe="4h")

            primary = item_30m
            rows.append({
                "symbol": symbol,
                "market": market,
                "available": bool(primary.get("available")),
                "primary_timeframe": "30m",
                "timeframes": {"30m": item_30m, "4h": item_4h},
                "trend_bias": primary.get("trend_bias"),
                "cloud_state": primary.get("cloud_state"),
                "tk_state": primary.get("tk_state"),
                "cloud_bias": primary.get("cloud_bias"),
                "long_support": primary.get("long_support"),
                "short_support": primary.get("short_support"),
                "quality": primary.get("quality", 0),
                "warnings": list(primary.get("warnings") or []),
            })
        except Exception as exc:
            rows.append({
                "symbol": symbol,
                "market": market,
                "available": False,
                "primary_timeframe": "30m",
                "trend_bias": "error",
                "cloud_state": "error",
                "tk_state": "error",
                "cloud_bias": "error",
                "long_support": "no_data",
                "short_support": "no_data",
                "quality": 0,
                "warnings": [f"error:{safe_str(exc)[:160]}"],
                "timeframes": {},
            })

    status_counts = Counter(x.get("trend_bias") or "unknown" for x in rows)
    cloud_counts = Counter(x.get("cloud_state") or "unknown" for x in rows)
    long_counts = Counter(x.get("long_support") or "unknown" for x in rows)
    short_counts = Counter(x.get("short_support") or "unknown" for x in rows)
    available_count = sum(1 for x in rows if x.get("available"))

    rows_sorted = sorted(rows, key=lambda x: (bool(x.get("available")), safe_int(x.get("quality"), 0), safe_str(x.get("symbol"))), reverse=True)

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "symbols_count": len(rows),
        "available_count": available_count,
        "summary": {
            "symbols_count": len(rows),
            "available_count": available_count,
            "trend_bias_counts": dict(status_counts),
            "cloud_state_counts": dict(cloud_counts),
            "long_support_counts": dict(long_counts),
            "short_support_counts": dict(short_counts),
            "top_quality": [
                {
                    "symbol": x.get("symbol"),
                    "trend_bias": x.get("trend_bias"),
                    "cloud_state": x.get("cloud_state"),
                    "quality": x.get("quality"),
                    "long_support": x.get("long_support"),
                    "short_support": x.get("short_support"),
                    "warnings": x.get("warnings", [])[:4],
                }
                for x in rows_sorted[:20]
            ],
        },
        "symbols": rows,
    }


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


async def ichimoku_context_loop(state, candle_service, logger=None) -> None:
    while True:
        try:
            symbols = await _get_fut_symbols(state)
            snapshot = build_ichimoku_snapshot_for_symbols(symbols=symbols, candle_service=candle_service, market="fut")

            write_json_atomic(LATEST_PATH, snapshot)
            append_jsonl(SUMMARY_PATH, {
                "ts": snapshot.get("ts"),
                "schema_version": SCHEMA_VERSION,
                "summary": snapshot.get("summary", {}),
            })

            if logger:
                logger.info("ICHIMOKU", "context updated", {
                    "symbols": snapshot.get("symbols_count"),
                    "available": snapshot.get("available_count"),
                    "trend_bias_counts": (snapshot.get("summary") or {}).get("trend_bias_counts"),
                    "cloud_state_counts": (snapshot.get("summary") or {}).get("cloud_state_counts"),
                })
        except Exception as exc:
            if logger:
                logger.error("ICHIMOKU", "context loop failed", {"error": safe_str(exc)})
            try:
                await state.add_sys_log("❌ [ICHIMOKU]", safe_str(exc))
            except Exception:
                pass

        await asyncio.sleep(max(15, safe_int(getattr(CONFIG.loops, "ichimoku_sec", 60), 60)))
