import asyncio, aiohttp, time, os

class SysMonitor:
    def __init__(self, dashboard):
        self.dashboard  = dashboard
        self.start_time = time.time()
        self.dashboard["server_status"] = {
            "uptime": "00:00:00", "ram_mb": "0", "ping_ms": "0"
        }

    def get_ram(self):
        try:
            with open(f"/proc/{os.getpid()}/status") as f:
                for line in f:
                    if "VmRSS" in line:
                        return str(int(line.split()[1]) // 1024)
        except Exception:
            pass
        return "?"

    async def get_ping(self, session):
        try:
            t = time.perf_counter()
            async with session.get(
                "https://api.bitget.com/api/v2/public/time"
            ) as r:
                await r.read()
            return str(int((time.perf_counter() - t) * 1000))
        except Exception:
            return "ERR"

    async def start(self):
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                u = int(time.time() - self.start_time)
                self.dashboard["server_status"]["uptime"] = (
                    f"{u//3600:02d}:{(u%3600)//60:02d}:{u%60:02d}"
                )
                self.dashboard["server_status"]["ram_mb"] = self.get_ram()
                self.dashboard["server_status"]["ping_ms"] = await self.get_ping(session)
                await asyncio.sleep(5)