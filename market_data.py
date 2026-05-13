import asyncio
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp

from config import CONFIG
from validators import normalize_symbol, safe_float


class MarketDataStream:
    """
    Market price stream.

    VORTEX fix:
    - futures prices are fetched through Bitget bulk endpoint;
    - spot prices are fetched through Bitget bulk endpoint;
    - bulk fetch failures do NOT poison every symbol as failed;
    - parser accepts several Bitget field variants;
    - logs include useful error class/repr instead of empty string.
    """

    FUTURES_URL = "https://api.bitget.com/api/v2/mix/market/tickers"
    SPOT_URL = "https://api.bitget.com/api/v2/spot/market/tickers"

    def __init__(self, state, logger=None) -> None:
        self.state = state
        self.logger = logger
        self.fail_counts: Dict[Tuple[str, str], int] = {}
        self.quarantine: Set[Tuple[str, str]] = set()
        self.timeout = aiohttp.ClientTimeout(total=12)
        self._last_good_bulk: Dict[str, Dict[str, float]] = {
            "fut": {},
            "spot": {},
        }

    # ==========================================================
    # Logging
    # ==========================================================

    def _exc_text(self, exc: BaseException) -> str:
        text = str(exc)
        if text:
            return text
        return f"{exc.__class__.__name__}: {repr(exc)}"

    async def _sys_log(self, tag: str, message: str) -> None:
        try:
            await self.state.add_sys_log(tag, message)
        except Exception:
            pass

    def _log_error(self, category: str, message: str, extra: Dict[str, Any]) -> None:
        if self.logger:
            try:
                self.logger.error(category, message, extra)
            except Exception:
                pass

    def _log_warning(self, category: str, message: str, extra: Dict[str, Any]) -> None:
        if self.logger:
            try:
                self.logger.warning(category, message, extra)
            except Exception:
                pass

    # ==========================================================
    # HTTP / parsing
    # ==========================================================

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str, params: Optional[dict] = None) -> dict:
        async with session.get(url, params=params or {}) as resp:
            text = await resp.text()

            if resp.status != 200:
                raise RuntimeError(f"http {resp.status}: {text[:300]}")

            try:
                return await resp.json(content_type=None)
            except Exception as exc:
                raise RuntimeError(f"json parse failed: {self._exc_text(exc)} | body={text[:300]}")

    def _extract_items(self, payload: Dict[str, Any], market: str) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            raise RuntimeError(f"{market} payload is not dict")

        code = str(payload.get("code", ""))
        if code != "00000":
            raise RuntimeError(f"bad code={payload.get('code')} msg={payload.get('msg')}")

        data = payload.get("data")

        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]

        if isinstance(data, dict):
            # Defensive support for wrapped response shapes.
            for key in ("list", "items", "tickers", "result", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]

        raise RuntimeError(f"empty or unsupported {market} bulk data shape: {type(data).__name__}")

    def _extract_symbol(self, item: Dict[str, Any]) -> str:
        raw = (
            item.get("symbol")
            or item.get("instId")
            or item.get("instrumentId")
            or item.get("symbolName")
        )

        sym = normalize_symbol(raw)

        # Defensive cleanup for old Bitget / connector symbol suffixes.
        for suffix in ("_SPBL", "_UMCBL", "_CMCBL", "_DMCBL"):
            if sym.endswith(suffix):
                sym = sym[: -len(suffix)]

        return sym

    def _extract_price(self, item: Dict[str, Any]) -> float:
        for key in (
            "lastPr",
            "last",
            "close",
            "lastPrice",
            "price",
            "markPrice",
            "indexPrice",
            "bidPr",
            "askPr",
        ):
            price = safe_float(item.get(key), 0.0)
            if price > 0:
                return price

        return 0.0

    async def _fetch_bulk_mapping(
        self,
        session: aiohttp.ClientSession,
        market: str,
        url: str,
        params: Optional[dict] = None,
    ) -> Tuple[Dict[str, float], float, bool]:
        """
        Returns: mapping, timestamp, ok.
        ok=False means bulk source failed. Caller must NOT mark every symbol as failed.
        """
        ts = time.time()

        try:
            payload = await self._fetch_json(session, url, params=params)
            items = self._extract_items(payload, market)

            mapping: Dict[str, float] = {}

            for item in items:
                symbol = self._extract_symbol(item)
                price = self._extract_price(item)

                if symbol and price > 0:
                    mapping[symbol] = price

            if not mapping:
                raise RuntimeError(f"{market} bulk parsed zero prices from {len(items)} items")

            self._last_good_bulk[market] = mapping
            return mapping, ts, True

        except Exception as exc:
            err = self._exc_text(exc)
            await self._sys_log("❌ [DATA]", f"{market}:bulk {err}")
            self._log_error(
                "MARKET_DATA",
                f"{market} bulk failed",
                {
                    "error": err,
                    "url": url,
                    "params": params or {},
                    "last_good_count": len(self._last_good_bulk.get(market, {})),
                },
            )

            # Fallback: if the latest bulk request fails once, continue using
            # last good mapping so the whole bot does not go blind for one API hiccup.
            fallback = self._last_good_bulk.get(market, {})
            if fallback:
                self._log_warning(
                    "MARKET_DATA",
                    f"{market} bulk fallback to last good mapping",
                    {"count": len(fallback)},
                )
                return dict(fallback), ts, True

            return {}, ts, False

    async def fetch_futures_all(self, session: aiohttp.ClientSession) -> Tuple[Dict[str, float], float, bool]:
        return await self._fetch_bulk_mapping(
            session=session,
            market="fut",
            url=self.FUTURES_URL,
            params={"productType": "USDT-FUTURES"},
        )

    async def fetch_spot_all(self, session: aiohttp.ClientSession) -> Tuple[Dict[str, float], float, bool]:
        return await self._fetch_bulk_mapping(
            session=session,
            market="spot",
            url=self.SPOT_URL,
            params=None,
        )

    # ==========================================================
    # State apply
    # ==========================================================

    async def _apply_prices(
        self,
        market: str,
        symbols: List[str],
        mapping: Dict[str, float],
        ts: float,
        bulk_ok: bool,
    ) -> None:
        active_keys = set()

        if not bulk_ok:
            # Important:
            # Bulk-source failure is not a symbol failure. Do not increment
            # every symbol fail counter and do not quarantine the whole pool.
            self._log_warning(
                "MARKET_DATA",
                f"{market} apply skipped because bulk is unavailable",
                {"symbols": symbols[:20], "symbols_count": len(symbols)},
            )
            return

        for symbol in symbols:
            sym = normalize_symbol(symbol)

            if not sym:
                continue

            key = (market, sym)
            active_keys.add(key)

            try:
                if key in self.quarantine:
                    # Retry quarantined symbols every loop if they are active again.
                    self.quarantine.remove(key)

                if sym not in mapping:
                    sample = list(mapping.keys())[:12]
                    raise RuntimeError(f"symbol not found in bulk mapping; sample={sample}")

                price = safe_float(mapping.get(sym), 0.0)

                if price <= 0:
                    raise RuntimeError("invalid price")

                await self.state.update_market_price(sym, price, ts)
                await self.state.set_symbol_health(
                    sym,
                    {
                        "status": "OK",
                        "market_type": market,
                        "last_update": ts,
                        "fails": 0,
                        "error": "",
                    },
                )
                self.fail_counts[key] = 0

            except Exception as exc:
                err = self._exc_text(exc)
                self.fail_counts[key] = self.fail_counts.get(key, 0) + 1

                if self.fail_counts[key] >= 10:
                    self.quarantine.add(key)

                await self.state.set_symbol_health(
                    sym,
                    {
                        "status": "FAIL",
                        "market_type": market,
                        "error": err,
                        "fails": self.fail_counts[key],
                        "last_update": time.time(),
                    },
                )

                self._log_warning(
                    "MARKET_DATA",
                    "symbol price failed",
                    {
                        "symbol": sym,
                        "market": market,
                        "error": err,
                        "fails": self.fail_counts[key],
                    },
                )

        # Clear stale quarantine/fails for symbols no longer in the pools.
        for key in list(self.quarantine):
            if key[0] == market and key not in active_keys:
                self.quarantine.remove(key)

        for key in list(self.fail_counts.keys()):
            if key[0] == market and key not in active_keys:
                del self.fail_counts[key]

    async def loop(self) -> None:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            while True:
                fut_pool = await self.state.get_pool("fut")
                spot_pool = await self.state.get_pool("spot")

                futures_mapping, fut_ts, fut_ok = await self.fetch_futures_all(session)
                await self._apply_prices("fut", fut_pool, futures_mapping, fut_ts, fut_ok)

                spot_mapping, spot_ts, spot_ok = await self.fetch_spot_all(session)
                await self._apply_prices("spot", spot_pool, spot_mapping, spot_ts, spot_ok)

                await asyncio.sleep(CONFIG.loops.market_data_sec)
