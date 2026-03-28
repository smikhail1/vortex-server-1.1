import asyncio, time, requests, os

class SysMonitor:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.start_time = time.time()
        self.dashboard["server_status"] = {"uptime": "00:00:00", "ram_mb": "0", "ping_ms": "0"}

    def get_ram_usage(self):
        try:
            with open(f"/proc/{os.getpid()}/status", "r") as f:
                for line in f:
                    if "VmRSS" in line:
                        return str(int(line.split()[1]) // 1024)
        except Exception: pass
        return "?"

    def get_ping(self):
        try:
            start = time.perf_counter()
            requests.get("https://api.bitget.com/api/v2/public/time", timeout=2)
            return str(int((time.perf_counter() - start) * 1000))
        except Exception: return "ERR"

    async def start(self):
        while True:
            u_sec = int(time.time() - self.start_time)
            self.dashboard["server_status"]["uptime"] = f"{u_sec//3600:02d}:{(u_sec%3600)//60:02d}:{u_sec%60:02d}"
            self.dashboard["server_status"]["ram_mb"] = self.get_ram_usage()
            self.dashboard["server_status"]["ping_ms"] = self.get_ping()
            await asyncio.sleep(5)
