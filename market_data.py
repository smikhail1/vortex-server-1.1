import asyncio, aiohttp, time

class MarketDataStream:
    def __init__(self, fut, spot):
        self.fut_symbols  = fut
        self.spot_symbols = spot
        self.buffers      = {}
        self.sem          = asyncio.Semaphore(6)  
        self.last_candle_fetch = {}

    async def fetch_candles(self, session, symbol, market_type):
        now = time.time()
        # Свечи запрашиваем раз в 60 секунд.
        if now - self.last_candle_fetch.get(symbol, 0) < 60:
            return

        try:
            url = f"https://api.bitget.com/api/v2/{market_type}/market/candles"
            g_30m = "30m"
            g_4h  = "4H" if market_type == "mix" else "4h"
            
            p_30m = {"symbol": symbol, "granularity": g_30m, "limit": 60}
            p_4h  = {"symbol": symbol, "granularity": g_4h,  "limit": 30}
            if market_type == "mix":
                p_30m["productType"] = "USDT-FUTURES"
                p_4h["productType"]  = "USDT-FUTURES"

            async with self.sem:
                async with session.get(url, params=p_30m) as r1:
                    r_30m = await r1.json(content_type=None)
                async with session.get(url, params=p_4h) as r2:
                    r_4h = await r2.json(content_type=None)

            if r_30m.get("code") == "00000" and r_4h.get("code") == "00000":
                if symbol not in self.buffers:
                    self.buffers[symbol] = {}
                self.buffers[symbol]["30m"] = r_30m["data"]
                self.buffers[symbol]["4h"]  = r_4h["data"]
                
                vols = [float(x[5]) for x in r_30m["data"][:20]]
                self.buffers[symbol]["last_vol"] = vols[0] if vols else 0
                self.buffers[symbol]["avg_vol"]  = sum(vols[1:]) / len(vols[1:]) if len(vols) > 1 else 1
                
                self.last_candle_fetch[symbol] = now
        except Exception:
            pass

    async def fetch_ticker_and_depth(self, session, symbol, market_type):
        try:
            # 1. Запрос точной цены последней сделки (Ticker)
            url_ticker = f"https://api.bitget.com/api/v2/{market_type}/market/ticker"
            p_ticker = {"symbol": symbol}
            if market_type == "mix":
                p_ticker["productType"] = "USDT-FUTURES"

            # 2. Запрос стакана для имбаланса (Depth)
            url_depth = f"https://api.bitget.com/api/v2/{market_type}/market/depth"
            p_depth = {"symbol": symbol, "limit": 50}
            if market_type == "mix":
                p_depth["productType"] = "USDT-FUTURES"
            else:
                p_depth["type"] = "step0" # Только Спот требует step0!

            async with self.sem:
                async with session.get(url_ticker, params=p_ticker) as r_t:
                    data_ticker = await r_t.json(content_type=None)
                async with session.get(url_depth, params=p_depth) as r_d:
                    data_depth = await r_d.json(content_type=None)

            if symbol not in self.buffers:
                self.buffers[symbol] = {}

            # Обновляем точную цену
            if data_ticker.get("code") == "00000" and data_ticker.get("data"):
                # Ticker возвращает массив data, берем 0 элемент
                self.buffers[symbol]["last_price"] = float(data_ticker["data"][0]["lastPr"])
                self.buffers[symbol]["updated_at"] = time.time()

            # Обновляем имбаланс
            if data_depth.get("code") == "00000" and data_depth.get("data"):
                bids = data_depth["data"].get("bids", [])
                asks = data_depth["data"].get("asks", [])
                if bids and asks:
                    bids_vol = sum(float(x[1]) for x in bids)
                    asks_vol = sum(float(x[1]) for x in asks)
                    self.buffers[symbol]["imbalance"] = bids_vol / asks_vol if asks_vol > 0 else 1.0

        except Exception:
            pass

    async def process_symbol(self, session, symbol):
        mtype = "mix" if symbol in self.fut_symbols else "spot"
        await asyncio.gather(
            self.fetch_candles(session, symbol, mtype),
            self.fetch_ticker_and_depth(session, symbol, mtype)
        )

    async def connect(self):
        print("📡 [DataStream] Поток данных запущен...")
        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    while True:
                        all_syms = list(set(self.fut_symbols + self.spot_symbols))
                        if not all_syms:
                            await asyncio.sleep(1)
                            continue

                        tasks = [self.process_symbol(session, sym) for sym in all_syms]
                        await asyncio.gather(*tasks)

                        active = set(all_syms)
                        for s in list(self.buffers):
                            if s not in active:
                                del self.buffers[s]

                        # Пауза 2 секунды, чтобы не спамить биржу
                        await asyncio.sleep(2)
            except Exception as e:
                print(f"⚠️ [DataStream] Сбой подключения: {e}. Реконнект через 5с...")
                await asyncio.sleep(5)