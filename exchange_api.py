import aiohttp
import time

class ExchangeAPI:
    def __init__(self, api_key="", api_secret=""):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.binance.com/api/v3"

    async def get_ping(self):
        """Замеряет реальную задержку до серверов Binance в миллисекундах"""
        start = time.time()
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.base_url}/ping", timeout=2) as resp:
                    if resp.status == 200:
                        return str(int((time.time() - start) * 1000))
            except:
                pass
        return "999"

    async def get_top_symbols(self, limit=30):
        """Получает ТОП реальных USDT монет по объему торгов за 24ч"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.base_url}/ticker/24hr") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        usdt_pairs = [d for d in data if d['symbol'].endswith('USDT')]
                        usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
                        return [d['symbol'] for d in usdt_pairs[:limit]]
            except:
                pass
        return ["BTCUSDT", "ETHUSDT"]

    async def get_market_metrics(self, symbol):
        """Тянет реальные японские свечи (4H) и считает настоящие RSI и ATR"""
        async with aiohttp.ClientSession() as session:
            try:
                url = f"{self.base_url}/klines?symbol={symbol}&interval=4h&limit=15"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        klines = await resp.json()
                        if len(klines) < 15: return None
                        
                        closes = [float(k[4]) for k in klines]
                        highs = [float(k[2]) for k in klines]
                        lows = [float(k[3]) for k in klines]
                        volumes = [float(k[5]) for k in klines]
                        
                        gains, losses = [], []
                        for i in range(1, len(closes)):
                            diff = closes[i] - closes[i-1]
                            if diff >= 0: gains.append(diff)
                            else: losses.append(abs(diff))
                        
                        avg_gain = sum(gains) / 14 if gains else 0
                        avg_loss = sum(losses) / 14 if losses else 0
                        rsi = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
                        
                        ranges = [highs[i] - lows[i] for i in range(len(highs))]
                        atr = sum(ranges) / len(ranges)
                        atr_pct = (atr / closes[-1]) * 100
                        
                        avg_vol = sum(volumes[:-1]) / 14 if len(volumes) > 1 else 1
                        vol_ratio = volumes[-1] / (avg_vol + 0.0001)
                        sma = sum(closes) / len(closes)
                        trend = "uptrend" if closes[-1] > sma else "downtrend"
                        
                        return {
                            "symbol": symbol, "last_price": closes[-1],
                            "atr_pct": round(atr_pct, 2), "rsi": round(rsi, 2),
                            "vol_ratio": round(vol_ratio, 2), "trend_4h": trend,
                            "near_support": rsi < 35 
                        }
            except:
                pass
        return None

    async def get_balances(self):
        """Тестовый баланс, чтобы UI не сбрасывался"""
        if not self.api_key:
            return {"fut": 100.0, "spot": 100.0}
        return {"fut": 0.0, "spot": 0.0}
