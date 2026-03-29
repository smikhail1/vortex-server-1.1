import asyncio, requests, time

class MarketOracle:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.dashboard["macro"] = {
            "btc_trend":    "neutral",
            "global_filter":"allow_all",
            "binance_btc":  0.0,
            "oi_amount":    0.0,
            "fng_value":    50,
        }
        self.btc_prices = []

    def fetch_btc(self):
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
                timeout=3
            ).json()
            if "price" not in r:
                return
            price = float(r["price"])
            self.btc_prices.append(price)
            if len(self.btc_prices) > 12:
                self.btc_prices.pop(0)
            self.dashboard["macro"]["binance_btc"] = price

            if len(self.btc_prices) >= 6:
                delta = (self.btc_prices[-1] - self.btc_prices[0]) / self.btc_prices[0]
                if delta > 0.005:
                    self.dashboard["macro"]["btc_trend"] = "strong_bullish"
                elif delta < -0.005:
                    self.dashboard["macro"]["btc_trend"] = "strong_bearish"
                elif delta > 0.002:
                    self.dashboard["macro"]["btc_trend"] = "bullish"
                elif delta < -0.002:
                    self.dashboard["macro"]["btc_trend"] = "bearish"
                else:
                    self.dashboard["macro"]["btc_trend"] = "neutral"
        except Exception:
            pass

    def fetch_oi(self):
        try:
            r = requests.get(
                "https://api.bitget.com/api/v2/mix/market/open-interest"
                "?symbol=BTCUSDT&productType=USDT-FUTURES",
                timeout=3
            ).json()
            if r.get("code") == "00000":
                self.dashboard["macro"]["oi_amount"] = float(r["data"]["amount"])
        except Exception:
            pass

    def fetch_fng(self):
        try:
            r = requests.get(
                "https://api.alternative.me/fng/?limit=1",
                timeout=5
            ).json()
            self.dashboard["macro"]["fng_value"] = int(r["data"][0]["value"])
        except Exception:
            pass

    def evaluate(self):
        trend = self.dashboard["macro"]["btc_trend"]
        # только резкие движения блокируют торговлю
        if trend == "strong_bearish":
            self.dashboard["macro"]["global_filter"] = "block_longs"
        elif trend == "strong_bullish":
            self.dashboard["macro"]["global_filter"] = "block_shorts"
        else:
            self.dashboard["macro"]["global_filter"] = "allow_all"

    async def start(self):
        last_fng = 0
        last_oi  = 0
        while True:
            self.fetch_btc()
            self.evaluate()

            if time.time() - last_oi > 60:
                self.fetch_oi()
                last_oi = time.time()

            if time.time() - last_fng > 3600:
                self.fetch_fng()
                last_fng = time.time()

            trend = self.dashboard["macro"]["btc_trend"]
            filt  = self.dashboard["macro"]["global_filter"]
            btc   = self.dashboard["macro"]["binance_btc"]
            oi    = self.dashboard["macro"]["oi_amount"]
            icon  = {"strong_bullish":"🚀","bullish":"📈",
                     "strong_bearish":"🩸","bearish":"📉"}.get(trend, "⚖️")

            self.dashboard["sys_logs"].insert(0,
                f"🕒 {time.strftime('%H:%M:%S')} 🧿 [ОРАКУЛ] "
                f"BTC:{btc:.0f} {icon} OI:{oi:.0f} | {filt}"
            )
            if len(self.dashboard["sys_logs"]) > 50:
                self.dashboard["sys_logs"].pop()

            await asyncio.sleep(10)
