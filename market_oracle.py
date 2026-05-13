import asyncio
import time
import aiohttp
from config import CONFIG
from validators import safe_float

class MarketOracle:
    def __init__(self, state_manager, logger=None) -> None:
        self.state = state_manager
        self.logger = logger
        self.macro = {"funding_rates": {}, "bitget_btc": 0.0}

    async def fetch_tickers(self, session):
        try:
            async with session.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=10) as r:
                res = await r.json(content_type=None)
                if res.get("code") == "00000":
                    data = res.get("data", [])
                    rates = {i["symbol"]: safe_float(i.get("fundingRate")) for i in data if "symbol" in i}
                    btc = next((safe_float(i.get("lastPr")) for i in data if i.get("symbol") == "BTCUSDT"), 0.0)
                    self.macro["funding_rates"] = rates
                    self.macro["bitget_btc"] = btc
                    return len(rates)
        except Exception: pass
        return 0

    async def loop(self):
        if self.logger: self.logger.info("ORACLE", "Loop started")
        h = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(headers=h) as session:
            while True:
                try:
                    count = await self.fetch_tickers(session)
                    if count > 0:
                        await self.state.update_macro(self.macro)
                        if self.logger: self.logger.info("ORACLE", f"Successfully synced {count} symbols")
                except Exception: pass
                await asyncio.sleep(CONFIG.loops.oracle_sec)
