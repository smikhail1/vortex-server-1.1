import asyncio, aiohttp, time

class MarketOracle:
    def __init__(self, dashboard):
        self.dashboard  = dashboard
        self.dashboard["macro"] = {
            "btc_trend":     "neutral",
            "global_filter": "allow_all",
            "binance_btc":   0.0,
            "oi_amount":     0.0,
            "fng_value":     50,
        }
        self.btc_prices = []

    async def fetch_btc(self, session):
        try:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": "BTCUSDT"}
            ) as r:
                data = await r.json(content_type=None)
            if "price" not in data:
                return
            price = float(data["price"])
            self.btc_prices.append(price)
            if len(self.btc_prices) > 12:
                self.btc_prices.pop(0)
            self.dashboard["macro"]["binance_btc"] = price

            if len(self.btc_prices) >= 6:
                delta = (self.btc_prices[-1] - self.btc_prices[0]) / self.btc_prices[0]
                if delta > 0.005:
                    trend = "strong_bullish"
                elif delta < -0.005:
                    trend = "strong_bearish"
                elif delta > 0.002:
                    trend = "bullish"
                elif delta < -0.002:
                    trend = "bearish"
                else:
                    trend = "neutral"
                self.dashboard["macro"]["btc_trend"] = trend
        except Exception:
            pass

    async def fetch_oi(self, session):
        try:
            async with session.get(
                "https://api.bitget.com/api/v2/mix/market/open-interest",
                params={"symbol": "BTCUSDT", "productType": "USDT-FUTURES"}
            ) as r:
                data = await r.json(content_type=None)
            if data.get("code") == "00000":
                self.dashboard["macro"]["oi_amount"] = float(data["data"]["amount"])
        except Exception:
            pass

    async def fetch_fng(self, session):
        try:
            async with session.get("https://api.alternative.me/fng/?limit=1") as r:
                data = await r.json(content_type=None)
            self.dashboard["macro"]["fng_value"] = int(data["data"][0]["value"])
        except Exception:
            pass

    def evaluate(self):
        trend = self.dashboard["macro"]["btc_trend"]
        if trend == "strong_bearish":
            self.dashboard["macro"]["global_filter"] = "block_longs"
        elif trend == "strong_bullish":
            self.dashboard["macro"]["global_filter"] = "block_shorts"
        else:
            self.dashboard["macro"]["global_filter"] = "allow_all"

    async def start(self):
        last_fng = 0
        last_oi  = 0
        timeout  = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                await self.fetch_btc(session)
                self.evaluate()

                if time.time() - last_oi > 60:
                    await self.fetch_oi(session)
                    last_oi = time.time()

                if time.time() - last_fng > 3600:
                    await self.fetch_fng(session)
                    last_fng = time.time()

                trend = self.dashboard["macro"]["btc_trend"]
                filt  = self.dashboard["macro"]["global_filter"]
                btc   = self.dashboard["macro"]["binance_btc"]
                icon  = {"strong_bullish": "🚀", "bullish": "📈",
                         "strong_bearish": "🩸", "bearish": "📉"}.get(trend, "⚖️")

                self.dashboard["sys_logs"].insert(0,
                    f"🕒 {time.strftime('%H:%M:%S')} 🧿 [ОРАКУЛ] "
                    f"BTC:{btc:.0f} {icon} | {filt}"
                )
                if len(self.dashboard["sys_logs"]) > 50:
                    self.dashboard["sys_logs"].pop()

                await asyncio.sleep(10)