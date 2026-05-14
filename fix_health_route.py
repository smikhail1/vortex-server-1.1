import os

filename = "api_server.py"
with open(filename, "r", encoding="utf-8") as f:
    code = f.read()

# Если роут health потерялся, возвращаем его
if '"/api/health"' not in code:
    code = code.replace(
        'self.app.router.add_post("/api/trading/modes"', 
        'self.app.router.add_get("/api/health", self.handle_health)\n        self.app.router.add_post("/api/trading/modes"'
    )
    with open(filename, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ Роут /api/health успешно возвращен в api_server.py!")
else:
    print("⚠️ Роут /api/health уже на месте. Проблема в другом.")
