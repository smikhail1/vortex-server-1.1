import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCHEMA = "vortex.coin_liquidity.shadow.v1"
SCHEMA_VERSION = "1.8.24-e"
LATEST_PATH = Path("_runtime/coin_liquidity_latest.json")
MAX_SYMBOLS = 20
LOOP_INTERVAL_SEC = 60
TAKER_REQUEST_PAUSE_SEC = 1.05
HTTP_TIMEOUT_SEC = 8

MIX_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"
SPOT_TICKERS_URL = "https://api.bitget.com/api/v2/spot/market/tickers"
OPEN_INTEREST_URL = "https://api.bitget.com/api/v2/mix/market/open-interest"
TAKER_BUY_SELL_URL = "https://api.bitget.com/api/v2/mix/market/taker-buy-sell"


class NoDataError(RuntimeError):
    pass


def _safe_str(value: Any, default: str = "") -> str:
    try:
        return default if value is None else str(value)
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return default if value in (None, "") else float(value)
    except Exception:
        return default


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _ticker_map(items: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        symbol = _safe_str(item.get("symbol")).upper()
        if symbol:
            out[symbol] = item
    return out


def _previous_oi(snapshot: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for item in snapshot.get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = _safe_str(item.get("symbol")).upper()
        value = _safe_float(item.get("oi_value"), None)
        if symbol and value is not None and value > 0:
            out[symbol] = value
    return out


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous <= 0:
        return None
    return round((current - previous) / previous * 100.0, 4)


def _select_symbols(dashboard: Dict[str, Any], limit: int = MAX_SYMBOLS) -> List[str]:
    terminal = dashboard.get("terminal") if isinstance(dashboard.get("terminal"), dict) else {}
    system = dashboard.get("system") if isinstance(dashboard.get("system"), dict) else {}
    items = terminal.get("watchlist_mini") if isinstance(terminal.get("watchlist_mini"), list) else []
    ranked: List[Tuple[float, str]] = []
    seen = set()

    for item in items:
        if not isinstance(item, dict) or _safe_str(item.get("market")).lower() != "fut":
            continue
        symbol = _safe_str(item.get("symbol")).upper()
        price = _safe_float(item.get("price"), 0.0) or 0.0
        trigger = _safe_float(item.get("trigger_price") or item.get("trigger"), 0.0) or 0.0
        distance = abs((price - trigger) / trigger * 100.0) if price > 0 and trigger > 0 else 9999.0
        if symbol and symbol not in seen:
            ranked.append((distance, symbol))
            seen.add(symbol)

    ranked.sort(key=lambda row: row[0])
    symbols = [symbol for _, symbol in ranked[:limit]]
    for raw in system.get("fut_pool") or []:
        symbol = _safe_str(raw).upper()
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
        if len(symbols) >= limit:
            break
    return symbols[:limit]


def _get_json_sync(url: str, params: Dict[str, str]) -> Dict[str, Any]:
    query = urlencode(params)
    target = f"{url}?{query}" if query else url
    request = Request(target, headers={"User-Agent": "VORTEX-coin-liquidity-shadow/1.8.24-e"})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SEC) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except Exception:
            raise
        if _safe_str(data.get("code")) == "40054":
            raise NoDataError("bitget_no_data") from exc
        raise
    if not isinstance(data, dict) or _safe_str(data.get("code")) != "00000":
        raise RuntimeError(f"bitget_error:{data}")
    return data


async def _get_json(url: str, params: Dict[str, str]) -> Dict[str, Any]:
    return await asyncio.to_thread(_get_json_sync, url, params)


def _extract_oi(payload: Dict[str, Any]) -> Optional[float]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rows = data.get("openInterestList") if isinstance(data.get("openInterestList"), list) else []
    if not rows or not isinstance(rows[0], dict):
        return None
    return _safe_float(rows[0].get("size"), None)


def _extract_taker(payload: Dict[str, Any]) -> Tuple[float, float]:
    rows = payload.get("data") if isinstance(payload.get("data"), list) else []
    buy = 0.0
    sell = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        buy += _safe_float(row.get("buyVolume"), 0.0) or 0.0
        sell += _safe_float(row.get("sellVolume"), 0.0) or 0.0
    return buy, sell


def _classify(
    *,
    price_change_pct: float,
    oi_change_pct: Optional[float],
    taker_delta_norm: float,
) -> str:
    price_up = price_change_pct >= 0.5
    price_down = price_change_pct <= -0.5
    oi_up = oi_change_pct is not None and oi_change_pct >= 1.0
    oi_down = oi_change_pct is not None and oi_change_pct <= -1.0
    buy_pressure = taker_delta_norm >= 0.12
    sell_pressure = taker_delta_norm <= -0.12

    if price_up and oi_up and buy_pressure:
        return "bullish_participation_expansion"
    if price_down and oi_up and sell_pressure:
        return "bearish_participation_expansion"
    if price_up and oi_down and buy_pressure:
        return "short_squeeze_like"
    if price_down and oi_down and sell_pressure:
        return "long_liquidation_like"
    if abs(price_change_pct) < 0.5 and abs(taker_delta_norm) < 0.12:
        return "weak_drift"
    if (price_up and sell_pressure) or (price_down and buy_pressure):
        return "flow_conflict"
    return "unclear"


def build_shadow_item(
    *,
    symbol: str,
    futures_ticker: Dict[str, Any],
    spot_ticker: Dict[str, Any],
    oi_value: Optional[float],
    previous_oi: Optional[float],
    taker_buy_volume: float,
    taker_sell_volume: float,
    taker_available: bool = True,
) -> Dict[str, Any]:
    symbol = _safe_str(symbol).upper()
    futures_price = _safe_float(futures_ticker.get("lastPr"), 0.0) or 0.0
    spot_price = _safe_float(spot_ticker.get("lastPr"), 0.0) or 0.0
    funding_rate = _safe_float(futures_ticker.get("fundingRate"), 0.0) or 0.0
    price_change_pct = (_safe_float(futures_ticker.get("change24h"), 0.0) or 0.0) * 100.0
    basis_pct = round((futures_price - spot_price) / spot_price * 100.0, 4) if futures_price > 0 and spot_price > 0 else None
    oi_change_pct = _pct_change(oi_value, previous_oi)

    total = max(0.0, taker_buy_volume) + max(0.0, taker_sell_volume)
    buy_pct = taker_buy_volume / total * 100.0 if total > 0 else None
    sell_pct = taker_sell_volume / total * 100.0 if total > 0 else None
    taker_delta_norm = (taker_buy_volume - taker_sell_volume) / total if total > 0 else None
    flow_delta = taker_delta_norm or 0.0
    state = _classify(
        price_change_pct=price_change_pct,
        oi_change_pct=oi_change_pct,
        taker_delta_norm=flow_delta,
    )

    directional = flow_delta
    if oi_change_pct is not None:
        directional += max(-0.2, min(0.2, oi_change_pct / 20.0))
    if basis_pct is not None:
        directional += max(-0.1, min(0.1, basis_pct / 5.0))
    directional += max(-0.05, min(0.05, funding_rate * 100.0))

    if directional >= 0.35:
        bias = "strong_long"
    elif directional >= 0.12:
        bias = "mild_long"
    elif directional <= -0.35:
        bias = "strong_short"
    elif directional <= -0.12:
        bias = "mild_short"
    else:
        bias = "neutral"

    confidence_floor = 0.35 if taker_available else 0.2
    confidence = round(min(0.95, confidence_floor + abs(directional) * 0.8), 2)
    warnings: List[str] = []
    if oi_change_pct is None:
        warnings.append("oi_history_warmup")
    if not taker_available:
        warnings.append("taker_data_unavailable")
    elif flow_delta >= 0.12:
        warnings.append("taker_buy_pressure")
    elif flow_delta <= -0.12:
        warnings.append("taker_sell_pressure")
    if state == "flow_conflict":
        warnings.append("price_flow_conflict")
    if spot_price <= 0:
        warnings.append("spot_pair_unavailable")

    if bias in {"strong_long", "mild_long"}:
        advice = "long_supportive_shadow"
    elif bias in {"strong_short", "mild_short"}:
        advice = "short_supportive_shadow"
    else:
        advice = "neutral_observe"

    return {
        "symbol": symbol,
        "market": "fut",
        "available": bool(futures_price > 0 and (oi_value is not None or total > 0)),
        "partial": not taker_available,
        "read_only": True,
        "futures_price": futures_price,
        "spot_price": spot_price or None,
        "price_change_pct_24h": round(price_change_pct, 4),
        "taker_available": taker_available,
        "taker_buy_pct": round(buy_pct, 2) if buy_pct is not None else None,
        "taker_sell_pct": round(sell_pct, 2) if sell_pct is not None else None,
        "taker_delta_norm": round(taker_delta_norm, 4) if taker_delta_norm is not None else None,
        "oi_value": oi_value,
        "oi_change_pct": oi_change_pct,
        "basis_pct": basis_pct,
        "funding_rate": funding_rate,
        "liquidity_bias": bias,
        "confidence": confidence,
        "state": state,
        "warnings": warnings,
        "advice": advice,
        "block_longs": False,
        "block_shorts": False,
    }


async def build_snapshot(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    started = time.time()
    previous = _read_json(LATEST_PATH)
    previous_oi = _previous_oi(previous)
    symbols = _select_symbols(dashboard)
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    mix_payload, spot_payload = await asyncio.gather(
        _get_json(MIX_TICKERS_URL, {"productType": "USDT-FUTURES"}),
        _get_json(SPOT_TICKERS_URL, {}),
    )
    mix = _ticker_map(mix_payload.get("data"))
    spot = _ticker_map(spot_payload.get("data"))

    for index, symbol in enumerate(symbols):
        try:
            oi_result, taker_result = await asyncio.gather(
                _get_json(OPEN_INTEREST_URL, {"symbol": symbol, "productType": "USDT-FUTURES"}),
                _get_json(TAKER_BUY_SELL_URL, {
                    "symbol": symbol,
                    "productType": "USDT-FUTURES",
                    "period": "5m",
                }),
                return_exceptions=True,
            )
            oi_value = None
            if isinstance(oi_result, Exception):
                errors.append(f"{symbol}:oi:{oi_result}")
            else:
                oi_value = _extract_oi(oi_result)

            taker_available = not isinstance(taker_result, Exception)
            if isinstance(taker_result, Exception):
                if not isinstance(taker_result, NoDataError):
                    errors.append(f"{symbol}:taker:{taker_result}")
                buy_volume, sell_volume = 0.0, 0.0
            else:
                buy_volume, sell_volume = _extract_taker(taker_result)
            items.append(build_shadow_item(
                symbol=symbol,
                futures_ticker=mix.get(symbol, {}),
                spot_ticker=spot.get(symbol, {}),
                oi_value=oi_value,
                previous_oi=previous_oi.get(symbol),
                taker_buy_volume=buy_volume,
                taker_sell_volume=sell_volume,
                taker_available=taker_available,
            ))
        except Exception as exc:
            errors.append(f"{symbol}:{exc}")
        if index + 1 < len(symbols):
            await asyncio.sleep(TAKER_REQUEST_PAUSE_SEC)

    bias_counts = Counter(item.get("liquidity_bias") for item in items)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "source_ts": time.time(),
        "age_sec": 0.0,
        "stale": False,
        "read_only": True,
        "available": bool(items),
        "symbols_requested": len(symbols),
        "symbols_count": len(items),
        "bias_counts": dict(bias_counts),
        "items": items,
        "errors": errors[:30],
        "duration_sec": round(time.time() - started, 3),
    }


def _stale_snapshot(previous: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
    previous = dict(previous or {})
    source_ts = _safe_float(previous.get("source_ts") or previous.get("ts"), time.time()) or time.time()
    previous.update({
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "source_ts": source_ts,
        "age_sec": round(max(0.0, time.time() - source_ts), 3),
        "stale": True,
        "read_only": True,
        "available": bool(previous.get("items")),
        "errors": [f"observer_loop_error:{exc}"] + list(previous.get("errors") or [])[:29],
    })
    return previous


async def coin_liquidity_observer_loop(state, logger=None) -> None:
    while True:
        try:
            dashboard = await state.get_dashboard_state()
            snapshot = await build_snapshot(dashboard)
            _write_json_atomic(LATEST_PATH, snapshot)
            if logger:
                logger.info("COIN_LIQUIDITY", "shadow snapshot updated", {
                    "read_only": True,
                    "symbols_count": snapshot.get("symbols_count"),
                    "bias_counts": snapshot.get("bias_counts"),
                    "errors_count": len(snapshot.get("errors") or []),
                    "duration_sec": snapshot.get("duration_sec"),
                })
        except Exception as exc:
            snapshot = _stale_snapshot(_read_json(LATEST_PATH), exc)
            _write_json_atomic(LATEST_PATH, snapshot)
            if logger:
                logger.warning("COIN_LIQUIDITY", "shadow observer failed soft", {
                    "read_only": True,
                    "error": str(exc),
                    "stale": True,
                })
        await asyncio.sleep(LOOP_INTERVAL_SEC)
