import os

filename = "api_server.py"
with open(filename, "r", encoding="utf-8") as f:
    code = f.read()

# Текст метода, которого не хватает
method_code = """
    async def handle_risk_status(self, request: web.Request) -> web.Response:
        if not self.router or not hasattr(self.router, 'risk_manager'):
            return web.json_response({"code": "ERROR", "msg": "RiskManager not found"}, status=503)
        status = self.router.risk_manager.get_status()
        return web.json_response({"code": "00000", "data": status})

    async def start(self,"""

# Вставляем метод, если его там действительно нет
if "def handle_risk_status" not in code:
    if "async def start(self," in code:
        code = code.replace("    async def start(self,", method_code)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)
        print("✅ Метод handle_risk_status добавлен.")
    else:
        print("❌ Не нашел точку входа 'async def start' для вставки.")
else:
    print("⚠️ Метод уже существует.")
