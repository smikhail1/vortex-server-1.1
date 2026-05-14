filename = "api_server.py"
method_code = """
    async def handle_risk_status(self, request: web.Request) -> web.Response:
        if not self.router or not hasattr(self.router, 'risk_manager'):
            return web.json_response({"code": "ERROR", "msg": "RiskManager not found"}, status=503)
        status = self.router.risk_manager.get_status()
        return web.json_response({"code": "00000", "data": status})

    async def start(self,"""

with open(filename, "r") as f:
    code = f.read()

if "handle_risk_status" not in code:
    code = code.replace("    async def start(self,", method_code)
    with open(filename, "w") as f:
        f.write(code)
    print("✅ Обработчик риска добавлен.")
