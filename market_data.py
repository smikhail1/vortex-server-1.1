import asyncio, requests, time

class MarketDataStream:
    def __init__(self, fut, spot):
        self.fut_symbols = fut
        self.spot_symbols = spot
        self.buffers = {}

    async def fetch_data(self, symbol, market_type):
        try:
            url_candles = f"https://api.bitget.com/api/v2/{market_type}/market/candles"
            url_depth = f"https://api.bitget.com/api/v2/{market_type}/market/depth"
            
            # Адаптация под API Bitget: для фьючей обычно 1H/4H, для спота 1h/4h
            g_1h = "1H" if market_type == "mix" else "1h"
            g_4h = "4H" if market_type == "mix" else "4h"
            
            # Сразу грузим 100 свечей истории, чтобы бот не ждал сутки
            p_1h = {"symbol": symbol, "granularity": g_1h, "limit": 100}
            p_4h = {"symbol": symbol, "granularity": g_4h, "limit": 50}
            p_depth = {"symbol": symbol, "type": "step0", "limit": 50}
            
            if market_type == "mix": 
                p_1h["productType"] = p_4h["productType"] = p_depth["productType"] = "USDT-FUTURES"

            r_1h = requests.get(url_candles, params=p_1h, timeout=3).json()
            r_4h = requests.get(url_candles, params=p_4h, timeout=3).json()
            r_depth = requests.get(url_depth, params=p_depth, timeout=3).json()

            if r_1h.get("code") == "00000" and r_4h.get("code") == "00000":
                if symbol not in self.buffers: self.buffers[symbol] = {}
                
                # Теперь движок получит ключи, которые он ждет
                self.buffers[symbol]["1h"] = r_1h["data"]
                self.buffers[symbol]["4h"] = r_4h["data"]
                self.buffers[symbol]["last_price"] = float(r_1h["data"][0][4])
                
                if r_depth.get("code") == "00000":
                    bids = sum([float(x[1]) for x in r_depth["data"]["bids"]])
                    asks = sum([float(x[1]) for x in r_depth["data"]["asks"]])
                    self.buffers[symbol]["imbalance"] = bids / asks if asks > 0 else 1.0
                    
                if len(self.buffers) > 20:
                    inactive = [s for s in self.buffers if s not in self.fut_symbols + self.spot_symbols]
                    if inactive: del self.buffers[inactive[0]]
        except Exception:
            pass 

    async def connect(self):
        while True:
            for sym in set(self.fut_symbols):
                await self.fetch_data(sym, "mix")
                await asyncio.sleep(0.1)
            for sym in set(self.spot_symbols):
                await self.fetch_data(sym, "spot")
                await asyncio.sleep(0.1)
            # Для часовых свечей спамить биржу раз в секунду нет смысла
            await asyncio.sleep(3)
