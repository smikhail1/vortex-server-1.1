import time
from collections import deque
from typing import Dict
import aiohttp
from validators import safe_float

class OITracker:
    def __init__(self, limit: int = 5, interval_sec: int = 300):
        self.limit = limit
        self.interval_sec = interval_sec
        self.history: Dict[str, deque] = {}
        self.last_update: Dict[str, float] = {}

    async def update_oi(self, session: aiohttp.ClientSession, symbol: str) -> None:
        now = time.time()
        if symbol in self.last_update and now - self.last_update[symbol] < self.interval_sec:
            return

        try:
            async with session.get(
                "https://api.bitget.com/api/v2/mix/market/open-interest",
                params={"symbol": symbol, "productType": "USDT-FUTURES"},
                timeout=3
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("code") == "00000":
                    amount = safe_float(data.get("data", {}).get("amount"), 0.0)
                    if amount > 0:
                        if symbol not in self.history:
                            self.history[symbol] = deque(maxlen=self.limit)
                        self.history[symbol].append(amount)
                        self.last_update[symbol] = now
        except Exception:
            pass

    def get_trend(self, symbol: str) -> str:
        if symbol not in self.history or len(self.history[symbol]) < 2:
            return "neutral"
        
        hist = list(self.history[symbol])
        start, end = hist[0], hist[-1]
        if start == 0: return "neutral"
            
        delta = (end - start) / start
        if delta >= 0.015: return "up"      # Заходят новые деньги
        if delta <= -0.015: return "down"   # Закрывают позиции (сквиз)
        return "neutral"
