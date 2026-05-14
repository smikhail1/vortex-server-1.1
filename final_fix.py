import os

filename = "api_server.py"
with open(filename, "r", encoding="utf-8") as f:
    code = f.read()

# Проверяем и добавляем handle_trading_modes
if "async def handle_trading_modes" not in code:
    method_modes = """
    async def handle_trading_modes(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            if not self.router: return web.json_response({"code": "ERROR"}, status=503)
            sm = payload.get("spot", "").upper()
            fm = payload.get("fut", "").upper()
            if sm in ["PAPER", "REAL"]: self.router.set_spot_mode(sm)
            if fm in ["PAPER", "REAL"]: self.router.set_fut_mode(fm)
            return web.json_response({"code": "00000", "msg": "success"})
        except: return web.json_response({"code": "ERROR"}, status=400)
"""
    code = code.replace("    async def start(self,", method_modes + "\n    async def start(self,")

# Проверяем и добавляем handle_risk_status
if "async def handle_risk_status" not in code:
    method_risk = """
    async def handle_risk_status(self, request: web.Request) -> web.Response:
        if not self.router or not hasattr(self.router, 'risk_manager'):
            return web.json_response({"code": "ERROR"}, status=503)
        return web.json_response({"code": "00000", "data": self.router.risk_manager.get_status()})
"""
    code = code.replace("    async def start(self,", method_risk + "\n    async def start(self,")

with open(filename, "w", encoding="utf-8") as f:
    f.write(code)
print("✅ api_server.py исправлен.")
