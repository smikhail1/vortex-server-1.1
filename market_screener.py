import requests
import time

class MarketScreener:
    def __init__(self):
        self.top_coins = []
        self.last_update = 0
        self.min_volume = 50000000  # $50 млн суточного объема

    def update_watchlist(self):
        """Обновляет список топ-10 волатильных монет с высоким объемом"""
        if time.time() - self.last_update < 3600:  # Раз в час
            return self.top_coins

        try:
            url = "https://api.bybit.com/v5/market/tickers?category=linear"
            response = requests.get(url, timeout=5).json()
            
            if response.get("retCode") != 0:
                return self.top_coins

            valid_coins = []
            for item in response["result"]["list"]:
                symbol = item["symbol"]
                # Пропускаем стейблкоины и дичь
                if not symbol.endswith("USDT") or "USDC" in symbol:
                    continue
                
                volume = float(item.get("turnover24h", 0))
                volatility = abs(float(item.get("price24hPcnt", 0)))

                if volume >= self.min_volume:
                    valid_coins.append({
                        "symbol": symbol,
                        "volatility": volatility
                    })

            # Сортируем по волатильности и берем топ-10
            valid_coins.sort(key=lambda x: x["volatility"], reverse=True)
            self.top_coins = [c["symbol"] for c in valid_coins[:10]]
            
            # Обязательно держим BTC в пуле как поводыря
            if "BTCUSDT" not in self.top_coins:
                self.top_coins.insert(0, "BTCUSDT")

            self.last_update = time.time()
            return self.top_coins

        except Exception as e:
            return self.top_coins
