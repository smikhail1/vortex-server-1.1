import asyncio, aiohttp, time

class MarketDataStream:
    def __init__(self, fut, spot):
        self.fut_symbols  = fut
        self.spot_symbols = spot
        self.buffers      = {}

    async def fetch_data(self, session, symbol, market_type):
        try:
            url_candles = f"https://api.bitget.com/api/v2/{market_type}/market/candles"
            url_depth   = f"https://api.bitget.com/api/v2/{market_type}/market/depth"

            g_30m = "30m"
            g_4h  = "4H" if market_type == "mix" else "4h"

            p_30m  = {"symbol": symbol, "granularity": g_30m, "limit": 60}
            p_4h   = {"symbol": symbol, "granularity": g_4h,  "limit": 30}
            p_depth = {"symbol": symbol, "type": "step0",     "limit": 50}

            if market_type == "mix":
                for p in (p_30m, p_4h, p_depth):
                    p["productType"] = "USDT-FUTURES"

            async with session.get(url_candles, params=p_30m) as r1:
                r_30m = await r1.json(content_type=None)
            async with session.get(url_candles, params=p_4h) as r2:
                r_4h = await r2.json(content_type=None)
            async with session.get(url_depth, params=p_depth) as r3:
                r_depth = await r3.json(content_type=None)

            if r_30m.get("code") == "00000" and r_4h.get("code") == "00000":
                if symbol not in self.buffers:
                    self.buffers[symbol] = {}

                self.buffers[symbol]["30m"]        = r_30m["data"]
                self.buffers[symbol]["4h"]         = r_4h["data"]
                self.buffers[symbol]["last_price"] = float(r_30m["data"][0][4])
                self.buffers[symbol]["updated_at"] = time.time()

                if r_depth.get("code") == "00000":
                    bids = sum(float(x[1]) for x in r_depth["data"]["bids"])
                    asks = sum(float(x[1]) for x in r_depth["data"]["asks"])
                    self.buffers[symbol]["imbalance"] = bids / asks if asks > 0 else 1.0

                vols = [float(x[5]) for x in r_30m["data"][:20]]
                self.buffers[symbol]["last_vol"] = vols[0] if vols else 0
                self.buffers[symbol]["avg_vol"]  = sum(vols[1:]) / len(vols[1:]) if len(vols) > 1 else 1

        except Exception:
            pass

    async def connect(self):
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                all_syms = list(set(self.fut_symbols + self.spot_symbols))
                for sym in all_syms:
                    mtype = "mix" if sym in self.fut_symbols else "spot"
                    await self.fetch_data(session, sym, mtype)
                    await asyncio.sleep(0.1)

                # чистим буферы неактивных монет
                active = set(self.fut_symbols + self.spot_symbols)
                for s in [s for s in list(self.buffers) if s not in active]:
                    del self.buffers[s]

                await asyncio.sleep(3)
