import os

filename = "api_server.py"
with open(filename, "r", encoding="utf-8") as f:
    code = f.read()

# Проверяем, есть ли методы. Если нет - вставляем перед методом start
if "def handle_risk_status" not in code:
    methods = """
    async def handle_trading_modes(self, request):
        try:
            data = await request.json()
            if not self.router: return web.json_response({"code": "ERROR"}, status=503)
            if "spot" in data: self.router.set_spot_mode(data["spot"])
            if "fut" in data: self.router.set_fut_mode(data["fut"])
            return web.json_response({"code": "00000", "mode": self.router.get_mode()})
        except: return web.json_response({"code": "ERROR"}, status=400)

    async def handle_risk_status(self, request):
        if not self.router or not hasattr(self.router, 'risk_manager'):
            return web.json_response({"code": "ERROR"}, status=503)
        return web.json_response({"code": "00000", "data": self.router.risk_manager.get_status()})

"""
    if "async def start(self" in code:
        code = code.replace("    async def start(self", methods + "    async def start(self")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)
        print("✅ Методы handle_trading_modes и handle_risk_status добавлены.")
    else:
        print("❌ Не удалось найти место для вставки.")
else:
    print("⚠️ Методы уже существуют.")
