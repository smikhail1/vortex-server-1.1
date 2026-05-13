import asyncio, aiohttp, time, os

class SysMonitor:
    # Теперь мы передаем сюда ссылку на наше Ядро (state_manager)
    def __init__(self, state_manager):
        self.state = state_manager  
        self.start_time = time.time()

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
        last_ping = 0
        ping_ms = "0"
        
        print("📊 [SysMonitor] Запущен и подключен к Ядру...")
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    u = int(time.time() - self.start_time)
                    uptime = f"{u//3600:02d}:{(u%3600)//60:02d}:{u%60:02d}"
                    ram_mb = self.get_ram()
                    
                    # Пинг запрашиваем раз в 5 секунд
                    if time.time() - last_ping > 5:
                        ping_ms = await self.get_ping(session)
                        last_ping = time.time()

                    # 🔥 ВОТ ОНА, МАГИЯ АРХИТЕКТУРЫ V3:
                    # Никаких прямых записей в словари. Только запрос к Ядру.
                    await self.state.update_system_metrics(uptime, ram_mb, ping_ms)

                except Exception as e:
                    print(f"⚠️ [SysMonitor] Ошибка цикла: {e}")
                    
                # Таймер спит 1 секунду для плавности UI
                await asyncio.sleep(1)