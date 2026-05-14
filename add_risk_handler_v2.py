import os

filename = "api_server.py"
with open(filename, "r", encoding="utf-8") as f:
    code = f.read()

# Код самого обработчика
method_code = """
    async def handle_risk_status(self, request: web.Request) -> web.Response:
        \"\"\"Эндпоинт для мониторинга лимита в 10$\"\"\"
        if not self.router or not hasattr(self.router, 'risk_manager'):
            return web.json_response({"code": "ERROR", "msg": "RiskManager not found"}, status=503)
        status = self.router.risk_manager.get_status()
        return web.json_response({"code": "00000", "data": status})

"""

if "handle_risk_status" not in code:
    # Ищем метод start и вставляем прямо перед ним
    if "async def start(self" in code:
        parts = code.split("async def start(self")
        # Собираем файл: начало + наш метод + async def start + остаток
        new_code = parts[0] + method_code + "    async def start(self" + parts[1]
        with open(filename, "w", encoding="utf-8") as f:
            f.write(new_code)
        print("✅ Метод handle_risk_status успешно внедрен!")
    else:
        print("❌ Не удалось найти точку входа 'async def start'.")
else:
    print("⚠️ Метод уже существует в файле.")
