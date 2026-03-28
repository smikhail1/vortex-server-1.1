from aiohttp import web
import json, time

class APIServer:
    def __init__(self, dashboard):
        self.dashboard = dashboard

    def _safe(self, obj):
        """Рекурсивно чистим нессериализуемые объекты"""
        if isinstance(obj, dict):
            return {k: self._safe(v) for k, v in obj.items()
                    if not callable(v)}
        elif isinstance(obj, list):
            return [self._safe(i) for i in obj]
        elif isinstance(obj, (int, float, str, bool, type(None))):
            return obj
        else:
            return str(obj)

    async def handle(self, request):
        data = self._safe(self.dashboard)
        # добавляем uptime в секундах для фронтенда
        data["uptime_sec"] = int(time.time() - self.dashboard.get("start_time", time.time()))
        return web.Response(
            text=json.dumps(data, ensure_ascii=False),
            content_type="application/json"
        )

    async def start(self, port=8080):
        app = web.Application()
        app.router.add_get("/api/dashboard", self.handle)
        app.router.add_get("/", self.handle)  # удобно для проверки в браузере
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"✅ API сервер запущен на порту {port}")
