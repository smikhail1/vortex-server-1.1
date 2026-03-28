import asyncio
import requests
import time

class MarketOracle:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.dashboard["macro"] = {
            "btc_trend": "neutral",
            "global_filter": "allow_all",
            "binance_btc": 0.0,
            "funding_rate": 0.0
        }
        self.btc_prices = []

    def fetch_btc_and_funding(self):
        try:
            # Используем Bybit V5 для синхронности
            url = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"
            r = requests.get(url, timeout=5).json()
            
            if r.get("retCode") == 0:
                data = r["result"]["list"][0]
                new_price = float(data["lastPrice"])
                funding = float(data.get("fundingRate", 0))
                
                self.dashboard["macro"]["funding_rate"] = funding * 100 # в процентах

                self.btc_prices.append(new_price)
                if len(self.btc_prices) > 20:
                    self.btc_prices.pop(0)

                old_price = self.dashboard["macro"].get("binance_btc", new_price)
                self.dashboard["macro"]["binance_btc"] = new_price

                if len(self.btc_prices) >= 10:
                    delta = (new_price - self.btc_prices[0]) / self.btc_prices[0]
                    if delta > 0.01:
                        self.dashboard["macro"]["btc_trend"] = "strong_bullish"
                    elif delta < -0.01:
                        self.dashboard["macro"]["btc_trend"] = "strong_bearish"
                    else:
                        self.dashboard["macro"]["btc_trend"] = "neutral"
        except Exception:
            pass

    def evaluate(self):
        trend = self.dashboard["macro"]["btc_trend"]
        funding = self.dashboard["macro"]["funding_rate"]

        if trend == "strong_bearish":
            self.dashboard["macro"]["global_filter"] = "block_longs"
        elif trend == "strong_bullish":
            self.dashboard["macro"]["global_filter"] = "block_shorts"
        # Защита от перегретого фандинга
        elif funding > 0.05:
            self.dashboard["macro"]["global_filter"] = "block_longs"
        elif funding < -0.05:
            self.dashboard["macro"]["global_filter"] = "block_shorts"
        else:
            self.dashboard["macro"]["global_filter"] = "allow_all"

    async def start(self):
        while True:
            self.fetch_btc_and_funding()
            self.evaluate()

            trend = self.dashboard["macro"]["btc_trend"]
            filt = self.dashboard["macro"]["global_filter"]
            btc = self.dashboard["macro"]["binance_btc"]
            fund = self.dashboard["macro"]["funding_rate"]

            icon = {"strong_bullish": "🚀", "strong_bearish": "🩸"}.get(trend, "⚖️")
            msg = f"BTC: {btc:.0f} {icon} | Fund: {fund:.3f}% | Ф: {filt}"

            self.dashboard["sys_logs"].insert(0, f"🕒 {time.strftime('%H:%M')} 🧿 [ОРАКУЛ] {msg}")
            if len(self.dashboard["sys_logs"]) > 50:
                self.dashboard["sys_logs"].pop()

            await asyncio.sleep(60) # Свинг не требует секундных обновлений
