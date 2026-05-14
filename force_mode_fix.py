filename = "api_server.py"
with open(filename, "r") as f:
    code = f.read()

# Находим место, где формируется ответ health
if '"mode": self.mode,' in code:
    code = code.replace('"mode": self.mode,', '"mode": self.router.get_mode() if (hasattr(self, "router") and self.router) else self.mode,')
    with open(filename, "w") as f:
        f.write(code)
    print("✅ Формат mode в api_server.py обновлен принудительно.")
else:
    print("⚠️ Строка не найдена, возможно уже обновлена.")
