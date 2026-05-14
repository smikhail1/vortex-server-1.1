import os

filename = "api_server.py"
with open(filename, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)
    # Вставляем роуты после инициализации приложения
    if "self.app = web.Application()" in line:
        new_lines.append('        self.app.router.add_post("/api/trading/modes", self.handle_trading_modes)\n')
        new_lines.append('        self.app.router.add_get("/api/risk/status", self.handle_risk_status)\n')

# Обновляем handle_health для нового формата
content = "".join(new_lines)
content = content.replace('"mode": self.mode,', '"mode": self.router.get_mode() if self.router else self.mode,')

with open(filename, "w", encoding="utf-8") as f:
    f.write(content)
print("✅ API роуты принудительно добавлены.")
