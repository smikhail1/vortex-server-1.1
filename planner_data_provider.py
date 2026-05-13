import asyncio
import time
from typing import Dict, List, Optional

import aiohttp

from config import CONFIG
from validators import normalize_symbol, safe_float


class PlannerDataProvider:
    """
    Собирает snapshot для Planner.
    Не пишет в state напрямую.
    Возвращает только готовый snapshot.
    """

    def __init__(self, universe: Optional[List[str]] = None, logger=None) -> None:
        self.base_url = "https://api.binance.com/api/v3/klines"
        self.universe = universe or list(CONFIG.planner.snapshot_universe)
        self.logger = logger
        self.sem = asyncio.Semaphore(6)

    async def _fetch_klines(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        interval: str,
        limit: int,
        retries: int = 2,
    ) -> Optional[List[list]]:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }

        for attempt in range(retries + 1):
            try:
                async with self.sem:
                    async with session.get(self.base_url, params=params) as resp:
                        if resp.status != 200:
                            if attempt == retries:
                                return None
                            await asyncio.sleep(0.35 * (attempt + 1))
                            continue

                        data = await resp.json(content_type=None)
                        if isinstance(data, list):
                            return data

                        if attempt == retries:
                            return None

            except Exception:
                if attempt == retries:
                    return None
                await asyncio.sleep(0.35 * (attempt + 1))

        return None

    def _parse_klines(self, rows: Optional[List[list]]) -> Optional[Dict[str, List[float]]]:
        if not rows:
            return None

        try:
            opens = [safe_float(x[1]) for x in rows]
            highs = [safe_float(x[2]) for x in rows]
            lows = [safe_float(x[3]) for x in rows]
            closes = [safe_float(x[4]) for x in rows]
            volumes = [safe_float(x[5]) for x in rows]
            ts_open = [int(x[0]) for x in rows]
            ts_close = [int(x[6]) for x in rows]

            if not closes or max(closes) <= 0:
                return None

            return {
                "opens": opens,
                "highs": highs,
                "lows": lows,
                "closes": closes,
                "volumes": volumes,
                "ts_open": ts_open,
                "ts_close": ts_close,
            }
        except Exception:
            return None

    @staticmethod
    def _ema(values: List[float], period: int) -> float:
        if not values:
            return 0.0
        period = max(1, int(period))
        k = 2 / (period + 1)
        ema_val = float(values[0])
        for v in values[1:]:
            ema_val = float(v) * k + ema_val * (1 - k)
        return ema_val

    @staticmethod
    def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        if not highs or not lows or not closes or len(closes) < 2:
            return 0.0

        trs = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)

        if not trs:
            return 0.0

        tail = trs[-period:] if len(trs) >= period else trs
        return sum(tail) / len(tail)

    @staticmethod
    def _volume_ratio(volumes: List[float], lookback: int = 20) -> float:
        if not volumes or len(volumes) == 1:
            return 1.0

        current = volumes[-1]
        base = volumes[-(lookback + 1):-1] if len(volumes) > lookback else volumes[:-1]
        avg = sum(base) / len(base) if base else current
        if avg <= 0:
            return 1.0

        return current / avg

    def _build_metrics(self, tf: Dict[str, List[float]]) -> Dict[str, float]:
        closes = tf["closes"]
        highs = tf["highs"]
        lows = tf["lows"]
        volumes = tf["volumes"]

        price = closes[-1]
        ema20 = self._ema(closes[-20:] if len(closes) >= 20 else closes, 20)
        ema50 = self._ema(closes[-50:] if len(closes) >= 50 else closes, 50)
        atr = self._atr(highs, lows, closes, period=14)
        atr_pct = (atr / price) * 100 if price > 0 else 0.0
        vol_ratio = self._volume_ratio(volumes, lookback=20)

        recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
        recent_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)

        return {
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "atr": atr,
            "atr_pct": atr_pct,
            "vol_ratio": vol_ratio,
            "recent_high": recent_high,
            "recent_low": recent_low,
        }

    async def analyze_symbol(self, session: aiohttp.ClientSession, symbol: str) -> Optional[Dict[str, object]]:
        sym = normalize_symbol(symbol)
        if not sym:
            return None

        d1_rows, w1_rows, h4_rows = await asyncio.gather(
            self._fetch_klines(session, sym, "1d", 160),
            self._fetch_klines(session, sym, "1w", 120),
            self._fetch_klines(session, sym, "4h", 200),
        )

        d1 = self._parse_klines(d1_rows)
        w1 = self._parse_klines(w1_rows)
        h4 = self._parse_klines(h4_rows)

        if not d1 or not w1 or not h4:
            return None

        d1m = self._build_metrics(d1)
        w1m = self._build_metrics(w1)
        h4m = self._build_metrics(h4)

        return {
            "symbol": sym,
            "price": float(d1m["price"]),
            "d1": d1,
            "w1": w1,
            "h4": h4,
            "metrics": {
                "d1": d1m,
                "w1": w1m,
                "h4": h4m,
            },
            "snapshot_ts": int(time.time()),
        }

    async def build_snapshot(self) -> Dict[str, object]:
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(limit=12, ssl=False)
        snapshot: Dict[str, object] = {
            "symbols": {},
            "meta": {
                "source": "binance-klines",
                "generated_at": int(time.time()),
                "universe_size": len(self.universe),
                "ok_count": 0,
                "fail_count": 0,
            },
        }

        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            tasks = [self.analyze_symbol(session, symbol) for symbol in self.universe]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        ok_count = 0
        fail_count = 0

        for result in results:
            if isinstance(result, Exception) or result is None:
                fail_count += 1
                continue

            symbol = normalize_symbol(result.get("symbol"))
            if not symbol:
                fail_count += 1
                continue

            snapshot["symbols"][symbol] = result
            ok_count += 1

        snapshot["meta"]["ok_count"] = ok_count
        snapshot["meta"]["fail_count"] = fail_count
        snapshot["meta"]["generated_at"] = int(time.time())

        if self.logger:
            self.logger.info("PLANNER_PROVIDER", "snapshot built", {
                "ok_count": ok_count,
                "fail_count": fail_count,
                "universe_size": len(self.universe),
            })

        return snapshot