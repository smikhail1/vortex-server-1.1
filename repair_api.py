import os

filename = "api_server.py"
with open(filename, "r", encoding="utf-8") as f:
    lines = f.readlines()

clean_lines = []
skip = False

for line in lines:
    # Удаляем дубликаты и старые попытки внедрения (если они есть)
    if 'add_post("/api/trading/modes"' in line or 'add_get("/api/risk/status"' in line:
        continue
    
    clean_lines.append(line)
    
    # Вставляем роуты в правильное место (после инициализации приложения)
    if "self.app = web.Application()" in line:
        clean_lines.append('        self.app.router.add_post("/api/trading/modes", self.handle_trading_modes)\n')
        clean_lines.append('        self.app.router.add_get("/api/risk/status", self.handle_risk_status)\n')

# Собираем обратно
content = "".join(clean_lines)

# Исправляем handle_health (универсальный поиск)
import re
content = re.sub(r'"mode":\s*self\.mode,', '"mode": self.router.get_mode() if (hasattr(self, "router") and self.router) else self.mode,', content)

with open(filename, "w", encoding="utf-8") as f:
    f.write(content)
print("✅ api_server.py восстановлен и обновлен.")
