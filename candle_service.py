from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import aiohttp

from config import CONFIG
from validators import normalize_symbol, safe_float, safe_int, safe_str

try:
    from vortex_candle_utils import parse_bitget_candles_payload
except Exception:
    def parse_bitget_candles_payload(payload: Any) -> List[Dict[str, float]]:
        data = payload.get("data", []) if isinstance(payload, dict) else payload
        out: List[Dict[str, float]] = []
        if not isinstance(data, list):
            return out
        for c in data:
            try:
                if isinstance(c, (list, tuple)) and len(c) >= 5:
                    item = {
                        "ts": int(float(c[0])),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]) if len(c) > 5 else 0.0,
                        "quote_volume": float(c[6]) if len(c) > 6 else 0.0,
                    }
                    if item["high"] > 0 and item["low"] > 0 and item["close"] > 0:
                        out.append(item)
            except Exception:
                continue
        out.sort(key=lambda x: x.get("ts", 0))
        return out


class CandleService:
    """
    VORTEX v1.6.7.1 CandleService.

    Fixes:
    - keeps TAService public contract: get_symbol_snapshot()
    - uses state fut_pool only
    - loads candles in batches
    - concurrency tuned for 30-symbol pool
    - retry for temporary empty 30m/4H responses
    """

    MIX_CANDLES_URL = "https://api.bitget.com/api/v2/mix/market/candles"

    def __init__(self, state_manager, logger=None) -> None:
        self.state = state_manager
        self.logger = logger
        self.timeout = aiohttp.ClientTimeout(total=safe_float(getattr(CONFIG.candles, "request_timeout_sec", 12), 12))
        self._semaphore = asyncio.Semaphore(max(8, safe_int(getattr(CONFIG.candles, "max_concurrency", 12), 12)))
        self._lock = asyncio.Lock()
        self.cache: Dict[str, Dict[str, List[Dict[str, float]]]] = {}
        self.last_update_ts: float = 0.0
        self.last_error: str = ""
        self.last_symbols: List[str] = []
        self.last_success_count: int = 0

    def _cache_key(self, symbol: str, market: str = "fut") -> str:
        return f"{normalize_symbol(symbol)}::{safe_str(market, 'fut').lower()}"

    def _normalize_granularity(self, timeframe: str) -> str:
        tf = safe_str(timeframe, "30m").strip()
        low = tf.lower()
        if low in {"4h", "4hr", "4hour", "4hours"}:
            return "4H"
        if low in {"30m", "30min", "30mins", "30minute", "30minutes"}:
            return "30m"
        return tf or "30m"

    async def _fetch_json(self, session: aiohttp.ClientSession, params: Dict[str, Any]) -> Dict[str, Any]:
        async with self._semaphore:
            async with session.get(self.MIX_CANDLES_URL, params=params) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"http {resp.status}: {text[:240]}")
                try:
                    return await resp.json(content_type=None)
                except Exception as exc:
                    raise RuntimeError(f"json parse failed: {exc} | body={text[:240]}")

    async def _fetch_mix_candles(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        granularity: str,
        limit: int,
    ) -> List[Dict[str, float]]:
        sym = normalize_symbol(symbol)
        if not sym:
            return []

        params = {
            "symbol": sym,
            "productType": "USDT-FUTURES",
            "granularity": self._normalize_granularity(granularity),
            "limit": str(max(20, safe_int(limit, 120))),
        }

        payload = await self._fetch_json(session, params)

        if str(payload.get("code", "")) != "00000":
            raise RuntimeError(f"bad candle code={payload.get('code')} msg={payload.get('msg')} params={params}")

        candles = parse_bitget_candles_payload(payload)
        candles.sort(key=lambda x: safe_float(x.get("ts"), 0.0))
        return candles

    async def _fetch_with_retry(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        granularity: str,
        limit: int,
        min_bars: int = 20,
    ) -> List[Dict[str, float]]:
        last: List[Dict[str, float]] = []
        for attempt in range(3):
            try:
                candles = await self._fetch_mix_candles(session, symbol, granularity, limit)
                if len(candles) >= min_bars:
                    return candles
                last = candles
            except Exception:
                if attempt >= 2:
                    raise
            await asyncio.sleep(0.25 * (attempt + 1))
        return last

    async def _refresh_symbol(self, session: aiohttp.ClientSession, symbol: str, market: str = "fut") -> bool:
        sym = normalize_symbol(symbol)
        if not sym:
            return False

        interval_30m = safe_str(getattr(CONFIG.candles, "interval_30m", "30m"), "30m")
        interval_4h = safe_str(getattr(CONFIG.candles, "interval_4h", "4H"), "4H")
        limit_30m = safe_int(getattr(CONFIG.candles, "limit_30m", 120), 120)
        limit_4h = safe_int(getattr(CONFIG.candles, "limit_4h", 120), 120)

        candles_30m = await self._fetch_with_retry(session, sym, interval_30m, limit_30m, min_bars=20)
        candles_4h = await self._fetch_with_retry(session, sym, interval_4h, limit_4h, min_bars=20)

        if not candles_30m or not candles_4h:
            raise RuntimeError(f"empty candles 30m={len(candles_30m)} 4h={len(candles_4h)}")

        payload = {
            "30m": list(candles_30m),
            "4h": list(candles_4h),
        }

        async with self._lock:
            self.cache[self._cache_key(sym, market)] = payload
            self.cache[self._cache_key(sym, "fut")] = payload
            self.last_update_ts = time.time()

        return True

    async def _get_pool_symbols(self) -> List[str]:
        try:
            symbols = await self.state.get_pool("fut")
        except Exception:
            symbols = []

        out: List[str] = []
        seen = set()
        for raw in symbols or []:
            sym = normalize_symbol(raw)
            if sym and sym not in seen:
                out.append(sym)
                seen.add(sym)
        return out

    async def refresh_once(self) -> None:
        symbols = await self._get_pool_symbols()

        if not symbols:
            self.last_error = "empty fut_pool"
            if self.logger:
                self.logger.warning("CANDLES", "refresh skipped: empty fut_pool", {})
            return

        errors: List[str] = []
        ok_count = 0
        batch_size = 10

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            for i in range(0, len(symbols), batch_size):
                chunk = symbols[i:i + batch_size]
                results = await asyncio.gather(
                    *[self._refresh_symbol(session, sym, "fut") for sym in chunk],
                    return_exceptions=True,
                )

                for sym, result in zip(chunk, results):
                    if isinstance(result, Exception):
                        errors.append(f"{sym}:{str(result)[:160]}")
                        if self.logger:
                            self.logger.warning("CANDLES", "symbol candles failed", {
                                "symbol": sym,
                                "error": str(result)[:300],
                            })
                    elif result:
                        ok_count += 1

                await asyncio.sleep(0.15)

        async with self._lock:
            self.last_symbols = list(symbols)
            self.last_error = " | ".join(errors[:5])
            self.last_success_count = ok_count
            if ok_count > 0:
                self.last_update_ts = time.time()

        if self.logger:
            self.logger.info("CANDLES", "FULL REFRESH", {
                "symbols": len(symbols),
                "ok": ok_count,
                "errors": len(errors),
                "cached_symbols": len(self.cache),
                "last_error": " | ".join(errors[:3]),
            })

    def get_candles(self, symbol: str, market: str = "fut", timeframe: str = "30m") -> List[Dict[str, float]]:
        tf = safe_str(timeframe, "30m").lower()
        tf_key = "4h" if tf in {"4h", "4hr", "4hour", "4hours"} else "30m"

        for market_key in (market, "fut"):
            key = self._cache_key(symbol, market_key)
            bucket = self.cache.get(key, {})
            candles = bucket.get(tf_key, [])
            if candles:
                return list(candles)

        return []

    def get_symbol_snapshot(self, symbol: str, market: str = "fut") -> Dict[str, Any]:
        return {
            "symbol": normalize_symbol(symbol),
            "market": safe_str(market, "fut").lower(),
            "candles_30m": self.get_candles(symbol, market, "30m"),
            "candles_4h": self.get_candles(symbol, market, "4h"),
        }

    def get_debug_snapshot(self) -> Dict[str, Any]:
        sample = {}
        for key, val in list(self.cache.items())[:10]:
            sample[key] = {
                "30m": len(val.get("30m", [])),
                "4h": len(val.get("4h", [])),
            }

        return {
            "enabled": bool(getattr(CONFIG.candles, "enabled", True)),
            "cached_symbols": len(self.cache),
            "last_update_ts": self.last_update_ts,
            "last_error": self.last_error,
            "last_symbols": list(self.last_symbols),
            "last_success_count": self.last_success_count,
            "sample": sample,
        }

    async def loop(self) -> None:
        while True:
            try:
                if bool(getattr(CONFIG.candles, "enabled", True)):
                    await self.refresh_once()
            except Exception as exc:
                self.last_error = str(exc)
                try:
                    await self.state.add_sys_log("❌ [CANDLES]", str(exc))
                except Exception:
                    pass
                if self.logger:
                    self.logger.error("CANDLES", "loop failed", {"error": str(exc)})

            await asyncio.sleep(max(10, safe_int(getattr(CONFIG.candles, "refresh_sec", 60), 60)))
