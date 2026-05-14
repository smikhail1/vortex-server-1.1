import os

# 1. Исправляем регистр статуса в Планере для Android-приложения
with open("spot_planner.py", "r", encoding="utf-8") as f:
    code = f.read()
code = code.replace('"status": "ok" if ideas else "empty"', '"status": "OK" if ideas else "EMPTY"')
with open("spot_planner.py", "w", encoding="utf-8") as f:
    f.write(code)

# 2. Исправляем вложенность ответа для эндпоинта приложения
with open("state_manager.py", "r", encoding="utf-8") as f:
    code = f.read()
old_line = 'async def get_spot_planner_state(self): return self.state["planner"]'
new_line = 'async def get_spot_planner_state(self): return self.state["planner"].get("spot_planner", self.state["planner"])'
code = code.replace(old_line, new_line)
with open("state_manager.py", "w", encoding="utf-8") as f:
    f.write(code)

print("✅ Формат JSON адаптирован под мобильное приложение!")
