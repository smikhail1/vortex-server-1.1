from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


class FundingAnalyzer:
    """
    Safe Bitget funding analyzer.

    Public methods:
    - fetch(session, symbol)
    - classify(rate)
    """

    BASE = "https://api.bitget.com/api/v2/mix/market/current-fund-rate"

    def __init__(self, config=None, logger=None):
        self.config = config
        self.logger = logger
        self.cache: Dict[str, Dict[str, Any]] = {}

    async def fetch(self, session, symbol: str) -> Optional[float]:
        symbol = _safe_str(symbol).upper()
        if not symbol:
            return None

        params = {"symbol": symbol, "productType": "USDT-FUTURES"}

        try:
            async with session.get(self.BASE, params=params, timeout=8) as resp:
                data = await resp.json(content_type=None)
        except Exception as exc:
            if self.logger:
                try:
                    self.logger.warning("EX_INTEL", "funding fetch failed", {"symbol": symbol, "error": str(exc)})
                except Exception:
                    pass
            return None

        payload = data.get("data") if isinstance(data, dict) else None
        item = None
        if isinstance(payload, list) and payload:
            item = payload[0]
        elif isinstance(payload, dict):
            item = payload

        if not isinstance(item, dict):
            return None

        rate = _safe_float(item.get("fundingRate"), None)
        if rate is None:
            rate = _safe_float(item.get("fundingRateRatio"), None)

        if rate is not None:
            self.cache[symbol] = {
                "ts": time.time(),
                "rate": rate,
                **self.classify(rate),
            }

        return rate

    def classify(self, rate: Optional[float]) -> Dict[str, Any]:
        rate = _safe_float(rate, 0.0)
        rate_pct = rate * 100.0

        extreme_long = _safe_float(getattr(self.config, "funding_extreme_long", 0.003), 0.003) * 100.0
        long_bias = _safe_float(getattr(self.config, "funding_long", 0.001), 0.001) * 100.0
        short_bias = _safe_float(getattr(self.config, "funding_short", -0.0005), -0.0005) * 100.0
        extreme_short = _safe_float(getattr(self.config, "funding_extreme_short", -0.001), -0.001) * 100.0

        if rate_pct >= extreme_long:
            return {"funding_signal": "extreme_long_bias", "funding_pct": round(rate_pct, 5), "funding_action": "avoid_longs"}
        if rate_pct >= long_bias:
            return {"funding_signal": "long_bias", "funding_pct": round(rate_pct, 5), "funding_action": "caution_longs"}
        if rate_pct <= extreme_short:
            return {"funding_signal": "extreme_short_bias", "funding_pct": round(rate_pct, 5), "funding_action": "avoid_shorts"}
        if rate_pct <= short_bias:
            return {"funding_signal": "short_bias", "funding_pct": round(rate_pct, 5), "funding_action": "caution_shorts"}

        return {"funding_signal": "neutral", "funding_pct": round(rate_pct, 5), "funding_action": "allow_all"}


class OIAnalyzer:
    """
    Safe Bitget Open Interest analyzer.

    Public methods:
    - update(session, symbol)
    - analyze(symbol, price_change_pct)
    """

    BASE = "https://api.bitget.com/api/v2/mix/market/open-interest"

    def __init__(self, config=None, logger=None):
        self.config = config
        self.logger = logger
        self.history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=48))

    async def update(self, session, symbol: str) -> Optional[float]:
        symbol = _safe_str(symbol).upper()
        if not symbol:
            return None

        params = {"symbol": symbol, "productType": "USDT-FUTURES"}

        try:
            async with session.get(self.BASE, params=params, timeout=8) as resp:
                data = await resp.json(content_type=None)
        except Exception as exc:
            if self.logger:
                try:
                    self.logger.warning("EX_INTEL", "oi fetch failed", {"symbol": symbol, "error": str(exc)})
                except Exception:
                    pass
            return None

        payload = data.get("data") if isinstance(data, dict) else None

        oi = None

        if isinstance(payload, list) and payload:
            item = payload[0]
            if isinstance(item, dict):
                oi = self._extract_oi(item)

        elif isinstance(payload, dict):
            oi = self._extract_oi(payload)

        if oi is not None and oi > 0:
            self.history[symbol].append({"ts": time.time(), "oi": oi})

        return oi

    def _extract_oi(self, item: Dict[str, Any]) -> Optional[float]:
        for key in ("openInterest", "openInterestAmount", "openInterestUsd", "amount", "size"):
            val = _safe_float(item.get(key), None)
            if val is not None and val > 0:
                return val

        lst = item.get("openInterestList")
        if isinstance(lst, list) and lst:
            first = lst[0]
            if isinstance(first, dict):
                for key in ("size", "amount", "openInterest"):
                    val = _safe_float(first.get(key), None)
                    if val is not None and val > 0:
                        return val

        return None

    def analyze(self, symbol: str, price_change_pct: float = 0.0) -> Dict[str, Any]:
        symbol = _safe_str(symbol).upper()
        hist = list(self.history.get(symbol, []))

        if len(hist) < 4:
            return {
                "oi_signal": "unknown",
                "oi_change_pct": 0.0,
                "oi_current": _safe_float(hist[-1]["oi"], 0.0) if hist else 0.0,
            }

        old = _safe_float(hist[-4].get("oi"), 0.0)
        new = _safe_float(hist[-1].get("oi"), 0.0)

        if old <= 0:
            return {"oi_signal": "unknown", "oi_change_pct": 0.0, "oi_current": new}

        change_pct = (new - old) / old * 100.0
        threshold = _safe_float(getattr(self.config, "oi_change_threshold_pct", 3.0), 3.0)
        price_change_pct = _safe_float(price_change_pct, 0.0)

        if change_pct > threshold and price_change_pct > 1.0:
            signal = "real_trend_up"
        elif change_pct > threshold and price_change_pct < -1.0:
            signal = "real_trend_down"
        elif change_pct < -threshold and price_change_pct > 1.0:
            signal = "short_squeeze"
        elif change_pct < -threshold and price_change_pct < -1.0:
            signal = "long_liquidation"
        else:
            signal = "neutral"

        return {
            "oi_signal": signal,
            "oi_change_pct": round(change_pct, 4),
            "oi_current": new,
        }


class ExchangeIntelligenceService:
    """
    Stable public service for VORTEX v1.6.4.

    Supported constructor:
        ExchangeIntelligenceService(config=None, logger=None)

    Supported methods:
        await update_all(session, symbols, price_changes=None)
        await update(session, symbols, price_changes=None)
        build_context(symbol, price_change_pct=0.0)
        get_context(symbol)
        context_for(symbol)
        snapshot()
    """

    def __init__(self, config=None, logger=None):
        self.config = config
        self.logger = logger
        self.enabled = bool(getattr(config, "enabled", True)) if config is not None else True
        self.oi = OIAnalyzer(config=config, logger=logger)
        self.funding = FundingAnalyzer(config=config, logger=logger)
        self.context_cache: Dict[str, Dict[str, Any]] = {}
        self.last_update_ts = 0.0

    async def update_all(self, session, symbols: List[str], price_changes: Optional[Dict[str, float]] = None) -> Dict[str, Dict[str, Any]]:
        if not self.enabled:
            return self.context_cache

        symbols = [_safe_str(s).upper() for s in (symbols or []) if _safe_str(s).strip()]
        price_changes = price_changes or {}

        async def _one(sym: str):
            oi_task = self.oi.update(session, sym)
            funding_task = self.funding.fetch(session, sym)
            oi_value, funding_value = await asyncio.gather(oi_task, funding_task, return_exceptions=True)

            if isinstance(oi_value, Exception):
                oi_value = None
            if isinstance(funding_value, Exception):
                funding_value = None

            ctx = self.build_context(sym, _safe_float(price_changes.get(sym), 0.0))
            self.context_cache[sym] = ctx
            return sym, ctx

        results = await asyncio.gather(*[_one(sym) for sym in symbols], return_exceptions=True)

        ok = 0
        for r in results:
            if isinstance(r, tuple):
                ok += 1

        self.last_update_ts = time.time()

        if self.logger:
            try:
                self.logger.info("EX_INTEL", "updated", {"symbols": len(symbols), "ok": ok})
            except Exception:
                pass

        return self.context_cache

    async def update(self, session, symbols: List[str], price_changes: Optional[Dict[str, float]] = None):
        return await self.update_all(session, symbols, price_changes)

    def build_context(self, symbol: str, price_change_pct: float = 0.0) -> Dict[str, Any]:
        symbol = _safe_str(symbol).upper()

        oi_ctx = self.oi.analyze(symbol, price_change_pct)
        funding_cached = self.funding.cache.get(symbol, {})
        funding_ctx = {
            "funding_signal": funding_cached.get("funding_signal", "neutral"),
            "funding_pct": _safe_float(funding_cached.get("funding_pct"), 0.0),
            "funding_action": funding_cached.get("funding_action", "allow_all"),
        }

        ctx = {
            "symbol": symbol,
            **oi_ctx,
            **funding_ctx,
            "ts": time.time(),
        }

        self.context_cache[symbol] = ctx
        return ctx

    def get_context(self, symbol: str) -> Dict[str, Any]:
        symbol = _safe_str(symbol).upper()
        return dict(self.context_cache.get(symbol, self.build_context(symbol, 0.0)))

    def context_for(self, symbol: str) -> Dict[str, Any]:
        return self.get_context(symbol)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "last_update_ts": self.last_update_ts,
            "symbols": len(self.context_cache),
            "context": self.context_cache,
        }

