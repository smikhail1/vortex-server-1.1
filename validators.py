import re
from typing import Any, Dict, List, Optional

from config import CONFIG


ASCII_BASE_RE = re.compile(r"^[A-Z0-9]{2,10}$")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "TRUE", "yes", "YES", "on", "ON"):
        return True
    if value in (0, "0", "false", "FALSE", "no", "NO", "off", "OFF"):
        return False
    return default


def normalize_symbol(symbol: Any) -> str:
    s = safe_str(symbol).strip().upper()
    return s.replace("-", "").replace("_", "").replace("/", "")


def clamp(value: float, min_value: float, max_value: float) -> float:
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def ensure_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def split_usdt_symbol(symbol: str) -> tuple[str, str]:
    sym = normalize_symbol(symbol)
    if sym.endswith("USDT") and len(sym) > 4:
        return sym[:-4], "USDT"
    return sym, ""


def is_usdt_symbol(symbol: Any) -> bool:
    sym = normalize_symbol(symbol)
    return sym.endswith("USDT") and len(sym) > 4


def is_ascii_asset_code(base_asset: str) -> bool:
    return bool(ASCII_BASE_RE.match(base_asset))


def is_leveraged_or_service_asset(base_asset: str) -> bool:
    suffix_blacklist = (
        "UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S", "2L", "2S",
    )
    for suffix in suffix_blacklist:
        if base_asset.endswith(suffix):
            return True
    return False


def is_stable_or_service_symbol(symbol: Any) -> bool:
    base, quote = split_usdt_symbol(safe_str(symbol))
    if quote != "USDT":
        return True

    excluded = {x.upper() for x in CONFIG.universe.excluded_base_assets}
    excluded.update({
        # stable / quasi-stable
        "USD1", "PYUSD", "USDE", "USDD", "FRAX", "MIM",
        # metals / synthetic commodities
        "XAUT", "PAXG",
        # явный мусор / service / старые тикеры
        "BARD", "BTTOLD", "BCC", "VEN", "NPXS", "BTCST",
        "1000BONK", "1000FLOKI", "1000LUNC", "1000SHIB",
    })

    if base in excluded:
        return True

    if is_leveraged_or_service_asset(base):
        return True

    if not is_ascii_asset_code(base):
        return True

    return False


def is_tradable_universe_symbol(symbol: Any) -> bool:
    sym = normalize_symbol(symbol)
    if not is_usdt_symbol(sym):
        return False
    if CONFIG.universe.exclude_stables and is_stable_or_service_symbol(sym):
        return False
    return True


def validate_market_price(symbol: Any, price: Any) -> Optional[Dict[str, Any]]:
    sym = normalize_symbol(symbol)
    px = safe_float(price, default=-1.0)
    if not sym or px <= 0:
        return None
    return {
        "symbol": sym,
        "price": px,
    }


def validate_symbol_health(symbol: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    sym = normalize_symbol(symbol)
    data = payload or {}
    status = safe_str(data.get("status"), "UNKNOWN").upper()
    market_type = safe_str(data.get("market_type"), "")
    error = safe_str(data.get("error"), "")
    fails = safe_int(data.get("fails"), 0)
    last_update = safe_float(data.get("last_update"), 0.0)

    return {
        "symbol": sym,
        "status": status,
        "market_type": market_type,
        "error": error,
        "fails": max(0, fails),
        "last_update": last_update,
    }


def validate_ta_item(symbol: Any, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sym = normalize_symbol(symbol)
    if not sym or not isinstance(payload, dict):
        return None

    item = {
        "price": safe_float(payload.get("price")),
        "rsi": safe_float(payload.get("rsi"), 50.0),
        "rsi_main": safe_float(payload.get("rsi_main"), 50.0),
        "atr_pct": safe_float(payload.get("atr_pct")),
        "dist_to_support": safe_float(payload.get("dist_to_support")),
        "dist_to_resistance": safe_float(payload.get("dist_to_resistance")),
        "atr": safe_float(payload.get("atr")),
        "imbalance": safe_float(payload.get("imbalance"), 1.0),
        "trend_4h": safe_str(payload.get("trend_4h"), "neutral"),
        "trend_bias_30m": safe_str(payload.get("trend_bias_30m"), "neutral"),
        "market_regime": safe_str(payload.get("market_regime"), "range"),
        "ema20": safe_float(payload.get("ema20")),
        "ema50": safe_float(payload.get("ema50")),
        "vol_ratio": safe_float(payload.get("vol_ratio"), 1.0),
        "vol_spike": safe_bool(payload.get("vol_spike")),
        "near_support": safe_bool(payload.get("near_support")),
        "near_resistance": safe_bool(payload.get("near_resistance")),
        "breakout": safe_bool(payload.get("breakout")),
        "breakout_dir": safe_str(payload.get("breakout_dir"), ""),
        "breakout_level": safe_float(payload.get("breakout_level")),
        "pullback_long_ready": safe_bool(payload.get("pullback_long_ready")),
        "pullback_short_ready": safe_bool(payload.get("pullback_short_ready")),
        "retest_long_ready": safe_bool(payload.get("retest_long_ready")),
        "retest_short_ready": safe_bool(payload.get("retest_short_ready")),
        "setup_zone": safe_str(payload.get("setup_zone"), "-"),
    }

    if item["price"] <= 0:
        return None

    return item


def validate_ta_payload(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    if not isinstance(payload, dict):
        return result

    for symbol, item in payload.items():
        normalized = validate_ta_item(symbol, item)
        if normalized is not None:
            result[normalize_symbol(symbol)] = normalized

    return result


def validate_watchlist_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None

    symbol = normalize_symbol(item.get("symbol"))
    if not symbol:
        return None

    market = safe_str(item.get("market"), "").lower()
    if market not in {"fut", "spot"}:
        return None

    status = safe_str(item.get("status"), "watch")
    if status not in {"near_entry", "watch", "blocked", "ready", "expired"}:
        status = "watch"

    return {
        "symbol": symbol,
        "price": safe_float(item.get("price")),
        "market": market,
        "side": safe_str(item.get("side")),
        "score": safe_int(item.get("score")),
        "setup_type": safe_str(item.get("setup_type"), "-"),
        "args_text": safe_str(item.get("args_text")),
        "status": status,
        "waiting_for": safe_str(item.get("waiting_for")),
        "trigger_price": safe_float(item.get("trigger_price")),
        "invalidation_price": safe_float(item.get("invalidation_price")),
        "created_at": safe_float(item.get("created_at")),
        "updated_at": safe_float(item.get("updated_at")),
        "expires_at": safe_float(item.get("expires_at")),
        "expires_in_sec": safe_int(item.get("expires_in_sec")),
        "confirmed": safe_bool(item.get("confirmed")),
        "confirmation_reason": safe_str(item.get("confirmation_reason")),
    }


def validate_watchlist_payload(items: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in ensure_list(items):
        valid = validate_watchlist_item(item)
        if valid:
            result.append(valid)
    return result


def validate_planner_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}

    ideas_out: List[Dict[str, Any]] = []
    for raw in ensure_list(data.get("ideas") or data.get("spot_ideas")):
        if not isinstance(raw, dict):
            continue

        symbol = normalize_symbol(raw.get("symbol"))
        if not symbol:
            continue

        entries = []
        for entry in ensure_list(raw.get("entries")):
            if not isinstance(entry, dict):
                continue
            entries.append({
                "allocation_pct": safe_int(entry.get("allocation_pct")),
                "price": safe_float(entry.get("price")),
            })

        targets = []
        for target in ensure_list(raw.get("targets")):
            if not isinstance(target, dict):
                continue
            targets.append({
                "price": safe_float(target.get("price")),
                "close_pct": safe_int(target.get("close_pct")),
            })

        accumulation_zone = raw.get("accumulation_zone") or {}
        if not isinstance(accumulation_zone, dict):
            accumulation_zone = {}

        idea = {
            "symbol": symbol,
            "tier": safe_str(raw.get("tier"), ""),
            "score": safe_int(raw.get("score")),
            "priority_rank": safe_int(raw.get("priority_rank")),
            "confidence_score": safe_int(raw.get("confidence_score")),
            "confidence_band": safe_str(raw.get("confidence_band"), ""),
            "horizon": safe_str(raw.get("horizon"), ""),
            "risk_grade": safe_str(raw.get("risk_grade"), ""),
            "status": safe_str(raw.get("status"), ""),
            "readiness": safe_str(raw.get("readiness"), ""),
            "rr_ratio": safe_float(raw.get("rr_ratio")),
            "current_price": safe_float(raw.get("current_price")),
            "accumulation_zone": {
                "top": safe_float(accumulation_zone.get("top")),
                "bottom": safe_float(accumulation_zone.get("bottom")),
            },
            "avg_entry": safe_float(raw.get("avg_entry")),
            "entries": entries,
            "targets": targets,
            "invalidation": safe_float(raw.get("invalidation")),
            "expected_return_base_pct": safe_float(raw.get("expected_return_base_pct")),
            "expected_return_bull_pct": safe_float(raw.get("expected_return_bull_pct")),
            "trend_d1": safe_str(raw.get("trend_d1"), ""),
            "trend_w1": safe_str(raw.get("trend_w1"), ""),
            "structure_4h": safe_str(raw.get("structure_4h"), ""),
            "action_label": safe_str(raw.get("action_label"), ""),
            "action_hint": safe_str(raw.get("action_hint"), ""),
            "thesis": [safe_str(x) for x in ensure_list(raw.get("thesis")) if safe_str(x)],
        }
        ideas_out.append(idea)

    return {
        "ideas": ideas_out,
        "spot_ideas": ideas_out,
        "generated_at": safe_int(data.get("generated_at") or data.get("last_update_ts")),
        "last_update_ts": safe_int(data.get("last_update_ts") or data.get("generated_at")),
        "mode": safe_str(data.get("mode"), "PLANNER"),
        "status": safe_str(data.get("status"), "ok"),
    }


def validate_position_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    return {
        "entry": safe_float(data.get("entry"), 0.0) if data.get("entry") is not None else None,
        "avg_price": safe_float(data.get("avg_price"), 0.0) if data.get("avg_price") is not None else None,
        "sl": safe_float(data.get("sl"), 0.0) if data.get("sl") is not None else None,
        "tp": safe_float(data.get("tp"), 0.0) if data.get("tp") is not None else None,
        "tp1": safe_float(data.get("tp1"), 0.0) if data.get("tp1") is not None else None,
        "tp2": safe_float(data.get("tp2"), 0.0) if data.get("tp2") is not None else None,
        "side": safe_str(data.get("side")) if data.get("side") is not None else None,
        "leverage": safe_float(data.get("leverage"), 0.0) if data.get("leverage") is not None else None,
        "liq_price": safe_float(data.get("liq_price"), 0.0) if data.get("liq_price") is not None else None,
        "pnl": safe_float(data.get("pnl"), 0.0) if data.get("pnl") is not None else None,
        "pnl_net": safe_float(data.get("pnl_net"), 0.0) if data.get("pnl_net") is not None else None,
        "fills_count": safe_int(data.get("fills_count"), 0) if data.get("fills_count") is not None else None,
        "tp1_hit": safe_bool(data.get("tp1_hit")) if data.get("tp1_hit") is not None else None,
        "breakeven": safe_bool(data.get("breakeven")) if data.get("breakeven") is not None else None,
        "status_label": safe_str(data.get("status_label")) if data.get("status_label") is not None else None,
    }