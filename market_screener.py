import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from config import CONFIG
from futures_validator import FuturesSymbolValidator
from validators import (
    is_ascii_asset_code,
    is_leveraged_or_service_asset,
    is_tradable_universe_symbol,
    normalize_symbol,
    safe_float,
    safe_str,
    split_usdt_symbol,
)


class MarketScreener:
    """
    VORTEX 1.5 Dynamic Market Screener.

    Public contract:
    - class MarketScreener
    - await refresh()
    - await refresh_market_buckets()
    - await get_debug_info()
    - await get_market_buckets()
    - get_symbol_metrics(symbol, market)

    Fixes:
    - normalized rank score: volume no longer dominates range/change;
    - stricter crypto universe filtering;
    - stores 24h metrics for TA/Momentum enrichment.
    """

    def __init__(self, fallback_symbols: Optional[List[str]] = None, logger=None) -> None:
        self.logger = logger
        self.futures_validator = FuturesSymbolValidator(logger=logger)
        self.fallback_symbols: List[str] = fallback_symbols or list(CONFIG.universe.fallback_symbols)
        self.dynamic_enabled: bool = bool(getattr(CONFIG.universe, "dynamic_enabled", True))
        self.top_n: int = int(CONFIG.universe.top_n)
        self.fut_pool_size: int = int(CONFIG.universe.fut_pool_size)
        self.spot_pool_size: int = int(CONFIG.universe.spot_pool_size)
        self.min_quote_volume_usdt: float = float(CONFIG.universe.min_quote_volume_usdt)
        self.min_last_price: float = float(CONFIG.universe.min_last_price)
        self.max_last_price: float = float(CONFIG.universe.max_last_price)
        self.min_24h_range_pct: float = float(CONFIG.universe.min_24h_range_pct)
        self.max_24h_range_pct: float = float(CONFIG.universe.max_24h_range_pct)
        self.min_24h_change_abs_pct: float = float(CONFIG.universe.min_24h_change_abs_pct)
        self.blacklisted_symbols = {normalize_symbol(x) for x in CONFIG.universe.blacklisted_symbols}

        self.last_refresh_ts: float = 0.0
        self.last_source: str = "init"
        self.last_debug: Dict[str, Any] = {}
        self.cache_futures: List[str] = []
        self.cache_spot: List[str] = []
        self.metrics_futures: Dict[str, Dict[str, Any]] = {}
        self.metrics_spot: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def _fetch_json(self, url: str, timeout_sec: int = 8, params: Optional[dict] = None) -> Any:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params or {}) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"http status {resp.status} for {url}: {text[:240]}")
                try:
                    return await resp.json(content_type=None)
                except Exception as exc:
                    raise RuntimeError(f"json parse failed for {url}: {exc} | body={text[:240]}")

    def _extract_payload_items(self, payload: Any, market: str) -> List[dict]:
        if not isinstance(payload, dict):
            raise RuntimeError(f"{market} payload is not dict: {type(payload).__name__}")
        code = str(payload.get("code", ""))
        if code and code != "00000":
            raise RuntimeError(f"{market} bad code={payload.get('code')} msg={payload.get('msg')}")

        def find_lists(obj: Any, depth: int = 0) -> List[List[dict]]:
            if depth > 5:
                return []
            found: List[List[dict]] = []
            if isinstance(obj, list):
                dicts = [x for x in obj if isinstance(x, dict)]
                if dicts:
                    found.append(dicts)
            elif isinstance(obj, dict):
                preferred = ("list", "items", "tickers", "result", "data", "rows")
                for key in preferred:
                    if key in obj:
                        found.extend(find_lists(obj.get(key), depth + 1))
                for key, value in obj.items():
                    if key not in preferred:
                        found.extend(find_lists(value, depth + 1))
            return found

        lists = find_lists(payload.get("data")) or find_lists(payload)
        if not lists:
            return []
        lists.sort(key=len, reverse=True)
        return lists[0]

    async def _fetch_bitget_futures_tickers(self) -> List[dict]:
        attempts = [
            ("https://api.bitget.com/api/v2/mix/market/tickers", {"productType": "USDT-FUTURES"}),
            ("https://api.bitget.com/api/v2/mix/market/tickers", {"productType": "usdt-futures"}),
            ("https://api.bitget.com/api/mix/v1/market/tickers", {"productType": "umcbl"}),
        ]
        errors: List[str] = []
        for url, params in attempts:
            try:
                payload = await self._fetch_json(url, params=params)
                items = self._extract_payload_items(payload, "fut")
                if items:
                    return items
                errors.append(f"{url} params={params} returned 0 items")
            except Exception as exc:
                errors.append(f"{url} params={params}: {exc}")
        if self.logger:
            try:
                self.logger.error("SCREENER", "empty futures source", {"errors": errors[-5:]})
            except Exception:
                pass
        return []

    async def _fetch_bitget_spot_tickers(self) -> List[dict]:
        payload = await self._fetch_json("https://api.bitget.com/api/v2/spot/market/tickers")
        return self._extract_payload_items(payload, "spot")

    def _symbol_from_item(self, item: dict) -> str:
        raw = (item.get("symbol") or item.get("instId") or item.get("instrumentId") or item.get("symbolName") or item.get("baseCoin") or "")
        sym = normalize_symbol(raw)
        for suffix in ("_SPBL", "_UMCBL", "_CMCBL", "_DMCBL", "-SPBL", "-UMCBL", "-CMCBL", "-DMCBL"):
            if sym.endswith(suffix):
                sym = sym[: -len(suffix)]
        return sym

    def _price_from_item(self, item: dict) -> float:
        return safe_float(
            item.get("lastPr") or item.get("last") or item.get("close") or item.get("lastPrice") or item.get("price"),
            0.0,
        )

    def _quote_volume_from_item(self, item: dict) -> float:
        quote_volume = safe_float(
            item.get("quoteVolume") or item.get("quoteVol") or item.get("usdtVolume") or item.get("usdtVol")
            or item.get("turnover") or item.get("turnover24h") or item.get("volCcy24h")
            or item.get("quoteVolume24h") or item.get("amount24h"),
            0.0,
        )
        if quote_volume > 0:
            return quote_volume
        price = self._price_from_item(item)
        base_volume = safe_float(
            item.get("baseVolume") or item.get("baseVol") or item.get("volume") or item.get("vol")
            or item.get("size24h"),
            0.0,
        )
        if price > 0 and base_volume > 0:
            return base_volume * price
        return 0.0

    def _high_from_item(self, item: dict, price: float) -> float:
        return safe_float(item.get("high24h") or item.get("high24") or item.get("high") or item.get("highPrice"), price)

    def _low_from_item(self, item: dict, price: float) -> float:
        return safe_float(item.get("low24h") or item.get("low24") or item.get("low") or item.get("lowPrice"), price)

    def _change_from_item(self, item: dict) -> float:
        raw = (
            item.get("priceChangePercent")
            or item.get("change24h")
            or item.get("changeUtc24h")
            or item.get("chgUtc")
            or item.get("change")
            or item.get("priceChange")
            or 0.0
        )
        value = safe_float(raw, 0.0)
        if -1.0 < value < 1.0 and value != 0.0:
            value *= 100.0
        return value

    def _is_blacklisted(self, symbol: str) -> bool:
        return normalize_symbol(symbol) in self.blacklisted_symbols

    def _is_tradable_symbol(self, symbol: str) -> bool:
        symbol = normalize_symbol(symbol)
        if not symbol.endswith("USDT"):
            return False
        if self._is_blacklisted(symbol):
            return False
        if not is_tradable_universe_symbol(symbol):
            return False
        base, quote = split_usdt_symbol(symbol)
        if quote != "USDT":
            return False
        if not is_ascii_asset_code(base):
            return False
        if is_leveraged_or_service_asset(base):
            return False
        return True

    def _rank_score(self, quote_volume: float, range_pct: float, change_pct: float) -> float:
        volume_m = quote_volume / 1_000_000.0
        vol_score = min(100.0, volume_m / 100.0)       # cap around 10B turnover
        range_score = min(100.0, range_pct * 10.0)
        change_score = min(100.0, abs(change_pct) * 15.0)
        return (
            vol_score * CONFIG.universe.rank_weight_volume
            + range_score * CONFIG.universe.rank_weight_range
            + change_score * CONFIG.universe.rank_weight_change
        )

    def _build_candidate(self, item: dict, market: str) -> Tuple[Optional[Dict[str, Any]], str]:
        symbol = self._symbol_from_item(item)
        if not symbol:
            return None, "bad_symbol"
        if self._is_blacklisted(symbol):
            return None, "blacklisted"
        if not self._is_tradable_symbol(symbol):
            return None, "not_tradable_symbol"

        price = self._price_from_item(item)
        if price < self.min_last_price or price > self.max_last_price:
            return None, "price_filter"

        quote_volume = self._quote_volume_from_item(item)
        if quote_volume < self.min_quote_volume_usdt:
            return None, "volume_filter"

        high = self._high_from_item(item, price)
        low = self._low_from_item(item, price)
        if high <= 0 or low <= 0 or high < low:
            return None, "bad_range"

        mid = max(price, (high + low) / 2.0)
        range_pct = ((high - low) / mid * 100.0) if mid > 0 else 0.0
        if range_pct < self.min_24h_range_pct:
            return None, "range_too_low"
        if range_pct > self.max_24h_range_pct:
            return None, "range_too_high"

        change_pct = self._change_from_item(item)
        if abs(change_pct) < self.min_24h_change_abs_pct and symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
            return None, "change_too_low"

        vol_ratio_24h = max(0.1, min(5.0, quote_volume / max(1.0, self.min_quote_volume_usdt)))
        rank_score = self._rank_score(quote_volume, range_pct, change_pct)

        candidate = {
            "symbol": symbol,
            "market": market,
            "price": round(price, 8),
            "quote_volume": round(quote_volume, 2),
            "high_24h": round(high, 8),
            "low_24h": round(low, 8),
            "range_pct": round(range_pct, 4),
            "change_pct": round(change_pct, 4),
            "vol_ratio": round(vol_ratio_24h, 4),
            "vol_ratio_24h": round(vol_ratio_24h, 4),
            "rank_score": round(rank_score, 4),
        }
        return candidate, "accepted"

    def _fallback_universe(self, limit: Optional[int] = None) -> List[str]:
        result: List[str] = []
        seen = set()
        for raw in self.fallback_symbols:
            sym = normalize_symbol(raw)
            if self._is_tradable_symbol(sym) and sym not in seen:
                result.append(sym)
                seen.add(sym)
        return result[:limit] if limit else result

    def _fallback_metrics(self, market: str, limit: int) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, Any]]:
        symbols = self._fallback_universe(limit=limit)
        metrics = {
            sym: {
                "symbol": sym,
                "market": market,
                "price": 0.0,
                "quote_volume": 0.0,
                "high_24h": 0.0,
                "low_24h": 0.0,
                "range_pct": 0.0,
                "change_pct": 0.0,
                "vol_ratio": 1.0,
                "vol_ratio_24h": 1.0,
                "rank_score": 0.0,
                "fallback": True,
            }
            for sym in symbols
        }
        debug = {
            "source_count": 0,
            "accepted_count": len(symbols),
            "reject_counts": {},
            "reject_samples": {},
            "accepted_preview": list(metrics.values())[:12],
            "selected_count": len(symbols),
            "selected": symbols,
            "market": market,
            "source": "fallback",
        }
        return symbols, metrics, debug

    def _screen_items(self, items: List[dict], market: str, limit: int) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, Any]]:
        reject_counts: Dict[str, int] = {}
        reject_samples: Dict[str, List[str]] = {}
        accepted: List[Dict[str, Any]] = []

        for item in items[: max(self.top_n * 5, 100)]:
            symbol = self._symbol_from_item(item) or "UNKNOWN"
            candidate, reason = self._build_candidate(item, market)
            if candidate is None:
                reject_counts[reason] = reject_counts.get(reason, 0) + 1
                reject_samples.setdefault(reason, [])
                if len(reject_samples[reason]) < 8:
                    reject_samples[reason].append(symbol)
                continue
            accepted.append(candidate)

        accepted.sort(key=lambda x: safe_float(x.get("rank_score"), 0.0), reverse=True)
        selected_candidates = accepted[:limit]
        selected_symbols = [safe_str(x.get("symbol")).upper() for x in selected_candidates]
        metrics = {safe_str(x.get("symbol")).upper(): x for x in selected_candidates}
        debug = {
            "source_count": len(items),
            "accepted_count": len(accepted),
            "reject_counts": reject_counts,
            "reject_samples": reject_samples,
            "accepted_preview": [
                {
                    "symbol": x["symbol"],
                    "price": x["price"],
                    "quote_volume": x["quote_volume"],
                    "range_pct": x["range_pct"],
                    "change_pct": x["change_pct"],
                    "vol_ratio_24h": x["vol_ratio_24h"],
                    "rank_score": x["rank_score"],
                }
                for x in accepted[:12]
            ],
            "selected_count": len(selected_symbols),
            "selected": selected_symbols,
            "market": market,
        }
        return selected_symbols, metrics, debug

    async def refresh_market_buckets(self) -> Dict[str, List[str]]:
        try:
            if not self.dynamic_enabled:
                fut_symbols, fut_metrics, fut_debug = self._fallback_metrics("fut", self.fut_pool_size)
                spot_symbols, spot_metrics, spot_debug = self._fallback_metrics("spot", self.spot_pool_size)
                source = "fallback_disabled"
            else:
                fut_items = await self._fetch_bitget_futures_tickers()
                spot_items = await self._fetch_bitget_spot_tickers()
                fut_symbols, fut_metrics, fut_debug = self._screen_items(fut_items, "fut", self.fut_pool_size)
                spot_symbols, spot_metrics, spot_debug = self._screen_items(spot_items, "spot", self.spot_pool_size)
                if not fut_symbols:
                    if self.logger:
                        try:
                            self.logger.error("SCREENER", "futures screener empty; fallback used", {"source_count": len(fut_items), "debug": fut_debug})
                        except Exception:
                            pass
                    fut_symbols, fut_metrics, fut_debug = self._fallback_metrics("fut", self.fut_pool_size)
                    fut_debug["fallback_reason"] = "empty_dynamic_futures"
                    fut_debug["dynamic_source_count"] = len(fut_items)
                if not spot_symbols:
                    spot_symbols, spot_metrics, spot_debug = self._fallback_metrics("spot", self.spot_pool_size)
                    spot_debug["fallback_reason"] = "empty_dynamic_spot"
                    spot_debug["dynamic_source_count"] = len(spot_items)
                source = "bitget"
        except Exception as exc:
            fut_symbols, fut_metrics, fut_debug = self._fallback_metrics("fut", self.fut_pool_size)
            spot_symbols, spot_metrics, spot_debug = self._fallback_metrics("spot", self.spot_pool_size)
            fut_debug["error"] = str(exc)
            spot_debug["error"] = str(exc)
            source = "fallback_error"
            if self.logger:
                try:
                    self.logger.error("SCREENER", "refresh failed; fallback used", {"error": str(exc)})
                except Exception:
                    pass

        try:
            validator = getattr(self, "futures_validator", None) or FuturesSymbolValidator(logger=self.logger)
            validated_fut_symbols, validator_debug = await validator.filter_valid_symbols(
                symbols=fut_symbols,
                target_size=self.fut_pool_size,
                fallback_symbols=self.fallback_symbols,
            )
            if validated_fut_symbols:
                fut_symbols = list(validated_fut_symbols)[: self.fut_pool_size]
                fut_metrics = {
                    sym: dict(fut_metrics.get(sym, {
                        "symbol": sym,
                        "market": "fut",
                        "price": 0.0,
                        "quote_volume": 0.0,
                        "high_24h": 0.0,
                        "low_24h": 0.0,
                        "range_pct": 0.0,
                        "change_pct": 0.0,
                        "vol_ratio": 1.0,
                        "vol_ratio_24h": 1.0,
                        "rank_score": 0.0,
                        "validator_only": True,
                    }))
                    for sym in fut_symbols
                }
                fut_debug["validator"] = validator_debug
            else:
                fut_debug["validator"] = validator_debug
                fut_debug["validator_warning"] = "validator returned zero symbols; keeping screener output"
            if self.logger:
                self.logger.info("VALIDATOR", "futures pool filtered", {"selected": fut_symbols, "validator": fut_debug.get("validator", {})})
        except Exception as exc:
            try:
                fut_debug["validator_error"] = str(exc)
            except Exception:
                pass
            if self.logger:
                try:
                    self.logger.error("VALIDATOR", "futures validator failed; keeping screener output", {"error": str(exc)})
                except Exception:
                    pass

        async with self._lock:
            self.cache_futures = fut_symbols
            self.cache_spot = spot_symbols
            self.metrics_futures = fut_metrics
            self.metrics_spot = spot_metrics
            self.last_refresh_ts = time.time()
            self.last_source = source
            self.last_debug = {"source": source, "futures": fut_debug, "spot": spot_debug, "ts": self.last_refresh_ts}
        if self.logger:
            self.logger.info("SCREENER", "market buckets updated", {
                "fut_candidates": fut_symbols, "spot_candidates": spot_symbols,
                "fut_debug": {"selected_count": fut_debug.get("selected_count", 0), "source_count": fut_debug.get("source_count", 0), "reject_counts": fut_debug.get("reject_counts", {}), "source": fut_debug.get("source", source), "fallback_reason": fut_debug.get("fallback_reason", "")},
                "spot_debug": {"selected_count": spot_debug.get("selected_count", 0), "source_count": spot_debug.get("source_count", 0), "reject_counts": spot_debug.get("reject_counts", {}), "source": spot_debug.get("source", source), "fallback_reason": spot_debug.get("fallback_reason", "")},
            })
        return {"fut": list(fut_symbols), "spot": list(spot_symbols)}

    async def refresh(self) -> List[str]:
        buckets = await self.refresh_market_buckets()
        return buckets.get("fut", [])

    async def get_market_buckets(self) -> Dict[str, List[str]]:
        async with self._lock:
            return {"fut": list(self.cache_futures), "spot": list(self.cache_spot)}

    async def get_debug_info(self) -> Dict[str, Any]:
        async with self._lock:
            return {**dict(self.last_debug), "last_refresh_ts": self.last_refresh_ts, "last_source": self.last_source}

    async def get_debug_payload(self) -> Dict[str, Any]:
        return await self.get_debug_info()

    def get_debug_snapshot(self) -> Dict[str, Any]:
        return {**dict(self.last_debug), "last_refresh_ts": self.last_refresh_ts, "last_source": self.last_source}

    def get_symbol_metrics(self, symbol: str, market: str = "fut") -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        mkt = safe_str(market).lower()
        if mkt in {"spot", "sp"}:
            return dict(self.metrics_spot.get(sym, {}))
        return dict(self.metrics_futures.get(sym, {}))

    def get_all_symbol_metrics(self, market: str = "fut") -> Dict[str, Dict[str, Any]]:
        mkt = safe_str(market).lower()
        return dict(self.metrics_spot if mkt in {"spot", "sp"} else self.metrics_futures)

    async def run(self) -> None:
        while True:
            await self.refresh_market_buckets()
            await asyncio.sleep(max(5, int(CONFIG.universe.refresh_sec)))