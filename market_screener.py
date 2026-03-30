import asyncio
import aiohttp
import time

class MarketScreener:
    """
    Изолированный микросервис скринера.
    Живет в своем асинхронном цикле, обновляет внутренний state.
    Никого не ждет и никого не блокирует.
    """
    def __init__(self):
        self.baseline_vol = {}
        self.btc_change = 0.0
        self._cache = {}            # Защищенный state
        self._lock = asyncio.Lock() # Микро-лок только для чтения/записи кэша
        self.is_ready = False       # Флаг первого успешного прохода

    async def _fetch_tickers(self, session):
        url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        try:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return {}
                data = await response.json()
                return {t["symbol"]: t for t in data.get("data", []) if t["symbol"].endswith("USDT")}
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return {}
        except Exception as e:
            print(f"⚠️ [Screener] Критическая ошибка сети: {e}")
            return {}

    def _update_btc(self, tickers):
        btc = tickers.get("BTCUSDT", {})
        try:
            self.btc_change = float(btc.get("priceChangePercent", 0))
        except Exception:
            self.btc_change = 0.0

    def _score_ticker(self, sym, t):
        try:
            price   = float(t.get("lastPr", 0))
            change  = float(t.get("priceChangePercent", 0))
            vol     = float(t.get("quoteVolume", 0))
            high24  = float(t.get("high24h", price))
            low24   = float(t.get("low24h", price))
            funding = float(t.get("fundingRate", 0))
        except Exception:
            return None

        if vol < 500_000 or price <= 0:
            return None

        rng = high24 - low24
        rng_pct = rng / price * 100 if price > 0 else 0
        if rng_pct < 1.0:
            return None

        score  = 0
        args   = []
        signal = "neutral"

        prev_vol = self.baseline_vol.get(sym, vol)
        vol_ratio = vol / prev_vol if prev_vol > 0 else 1.0
        self.baseline_vol[sym] = prev_vol * 0.8 + vol * 0.2

        if vol_ratio > 2.0:
            score += 3; args.append(f"Объём ×{vol_ratio:.1f} 🔥")
        elif vol_ratio > 1.5:
            score += 2; args.append(f"Объём ×{vol_ratio:.1f}")

        btc = self.btc_change
        if abs(btc) > 0.3 and abs(change) > abs(btc):
            ratio = abs(change) / abs(btc)
            same_dir = (change > 0) == (btc > 0)
            if ratio > 2.0 and same_dir:
                score += 2; args.append(f"Лидер ×{ratio:.1f}")
            elif ratio > 1.3 and same_dir:
                score += 1; args.append(f"Сильнее BTC ×{ratio:.1f}")

        if change > 1.0 and vol_ratio < 0.7:
            score += 2; args.append("Рост без объёма ⚠️"); signal = "short"
        elif change > 0:
            signal = "long"
        else:
            signal = "short"

        pos = (price - low24) / rng if rng > 0 else 0.5
        if pos > 0.92:
            score += 2; args.append("Хай дня 🔝"); signal = "long"
        elif pos < 0.08:
            score += 2; args.append("Лой дня 🔻"); signal = "short"

        if funding > 0.001 or funding < -0.001:
            score += 1; args.append(f"Фандинг {funding*100:.3f}%")

        if score < 3:
            return None

        return {
            "score": score, "signal": signal, "change": change,
            "vol": vol, "vol_ratio": vol_ratio, "args": args,
            "added_at": time.time(), "confirmed": 0
        }

    async def run(self):
        print("🚀 [Screener] Воркер запущен...")
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    tickers = await self._fetch_tickers(session)
                    
                    if not tickers:
                        await asyncio.sleep(5)
                        continue

                    self._update_btc(tickers)
                    
                    found = {}
                    for sym, t in tickers.items():
                        if sym in ("BTCUSDT", "ETHUSDT"):
                            self.baseline_vol[sym] = float(t.get("quoteVolume", 0))
                            continue
                        
                        res = self._score_ticker(sym, t)
                        if res:
                            found[sym] = res

                    new_cache = {}
                    now = time.time()
                    
                    for sym, info in found.items():
                        if sym not in self._cache:
                            new_cache[sym] = info
                        else:
                            old = self._cache[sym]
                            new_cache[sym] = old
                            new_cache[sym]["score"] = info["score"]
                            new_cache[sym]["args"] = info["args"]
                            new_cache[sym]["confirmed"] += 1

                    to_keep = {k: v for k, v in new_cache.items() if now - v["added_at"] <= 3600}

                    async with self._lock:
                        self._cache = to_keep
                        self.is_ready = True

                except Exception as e:
                    print(f"⚠️ [Screener] Ошибка в цикле: {e}")

                await asyncio.sleep(60)

    async def get_top_symbols(self, limit=6):
        if not self.is_ready:
            return [] 

        async with self._lock:
            top = sorted(self._cache.items(), key=lambda x: x[1]["score"], reverse=True)[:limit]
            return [s for s, _ in top]