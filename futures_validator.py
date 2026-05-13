from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple
import aiohttp

from validators import normalize_symbol, safe_int

try:
    from vortex_candle_utils import parse_bitget_candles_payload
except Exception:
    def parse_bitget_candles_payload(payload: Any) -> List[Dict[str, float]]:
        data = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(data, list):
            return []
        out = []
        for c in data:
            try:
                if isinstance(c, (list, tuple)) and len(c) >= 5:
                    out.append({"ts": int(float(c[0])), "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])})
            except Exception:
                pass
        return out


class FuturesSymbolValidator:
    CANDLES_URL = "https://api.bitget.com/api/v2/mix/market/candles"

    def __init__(self, logger=None, min_bars: int = 50, limit: int = 120, max_concurrency: int = 8) -> None:
        self.logger = logger
        self.min_bars = max(20, safe_int(min_bars, 50))
        self.limit = max(60, safe_int(limit, 120))
        self._sem = asyncio.Semaphore(max(1, safe_int(max_concurrency, 8)))

    def _dedupe(self, symbols: List[str]) -> List[str]:
        out = []
        seen = set()
        for raw in symbols or []:
            sym = normalize_symbol(raw)
            if sym and sym.endswith("USDT") and sym not in seen:
                out.append(sym)
                seen.add(sym)
        return out

    async def _fetch_count(self, session: aiohttp.ClientSession, symbol: str, granularity: str) -> int:
        params = {
            "symbol": normalize_symbol(symbol),
            "productType": "USDT-FUTURES",
            "granularity": granularity,
            "limit": str(self.limit),
        }
        async with self._sem:
            async with session.get(self.CANDLES_URL, params=params) as resp:
                payload = await resp.json(content_type=None)
        if str(payload.get("code", "")) != "00000":
            return 0
        return len(parse_bitget_candles_payload(payload))

    async def _validate_one(self, session: aiohttp.ClientSession, symbol: str) -> Tuple[str, bool, Dict[str, Any]]:
        sym = normalize_symbol(symbol)
        try:
            c30, c4h = await asyncio.gather(
                self._fetch_count(session, sym, "30m"),
                self._fetch_count(session, sym, "4H"),
            )
            ok = c30 >= self.min_bars and c4h >= self.min_bars
            return sym, ok, {"symbol": sym, "candles_30m": c30, "candles_4h": c4h, "reason": "ok" if ok else "insufficient_candles"}
        except Exception as exc:
            return sym, False, {"symbol": sym, "candles_30m": 0, "candles_4h": 0, "reason": str(exc)[:200]}

    async def filter_valid_symbols(self, symbols: List[str], target_size: int, fallback_symbols: Optional[List[str]] = None) -> Tuple[List[str], Dict[str, Any]]:
        queue = self._dedupe((symbols or []) + (fallback_symbols or []))
        target_size = max(1, safe_int(target_size, 20))
        accepted: List[str] = []
        rejected: List[Dict[str, Any]] = []

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            results = await asyncio.gather(*[self._validate_one(session, s) for s in queue], return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                rejected.append({"symbol": "UNKNOWN", "reason": str(r)[:200]})
                continue
            sym, ok, debug = r
            if ok and sym not in accepted:
                accepted.append(sym)
                if len(accepted) >= target_size:
                    break
            else:
                rejected.append(debug)

        info = {
            "input_count": len(symbols or []),
            "checked_count": len(queue),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted": accepted,
            "rejected_preview": rejected[:12],
        }
        if self.logger:
            try:
                self.logger.info("VALIDATOR", "futures symbols validated", info)
            except Exception:
                pass
        return accepted, info
