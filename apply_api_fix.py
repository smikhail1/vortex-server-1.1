import os

filename = "api_server.py"
if not os.path.exists(filename):
    print(f"❌ Файл {filename} не найден!")
    exit(1)

with open(filename, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Добавляем новый роут в список маршрутов
old_routes = 'web.post("/api/trading/close_all_spot", self.handle_close_all_spot),'
new_routes = old_routes + '\n            web.post("/api/trading/modes", self.handle_trading_modes),'

if old_routes in code and '/api/trading/modes' not in code:
    code = code.replace(old_routes, new_routes)
    print("✅ Роут /api/trading/modes добавлен.")

# 2. Обновляем handle_health для отображения раздельных режимов
old_health = '"mode": self.mode,'
new_health = '"mode": self.router.get_mode() if self.router else self.mode,'

if old_health in code:
    code = code.replace(old_health, new_health)
    print("✅ Метод handle_health обновлен.")

# 3. Внедряем метод handle_trading_modes перед методом start
method_code = """
    async def handle_trading_modes(self, request: web.Request) -> web.Response:
        \"\"\"Эндпоинт для мобильного приложения: Раздельное переключение режимов\"\"\"
        if not self.router:
            return web.json_response({"code": "ERROR", "msg": "Router not initialized"}, status=503)
        
        try:
            payload = await request.json()
            spot_mode = safe_str(payload.get("spot")).upper()
            fut_mode = safe_str(payload.get("fut")).upper()
            
            if spot_mode in ["PAPER", "REAL"]:
                self.router.set_spot_mode(spot_mode)
            if fut_mode in ["PAPER", "REAL"]:
                self.router.set_fut_mode(fut_mode)
                
            if self.logger:
                self.logger.info("API", "Trading modes updated via App", {
                    "spot": self.router.spot_mode, 
                    "fut": self.router.fut_mode
                })
                
            return web.json_response({
                "code": "00000",
                "msg": "success",
                "data": {
                    "spot_mode": self.router.spot_mode,
                    "fut_mode": self.router.fut_mode
                }
            })
        except Exception as exc:
            return web.json_response({"code": "ERROR", "msg": str(exc)}, status=400)

    async def start(self,"""

if 'handle_trading_modes' not in code:
    code = code.replace("    async def start(self,", method_code)
    print("✅ Обработчик handle_trading_modes внедрен.")

with open(filename, "w", encoding="utf-8") as f:
    f.write(code)
