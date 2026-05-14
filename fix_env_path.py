import os

filename = "main.py"
with open(filename, "r", encoding="utf-8") as f:
    code = f.read()

# Уточняем путь к .env, чтобы сервис его точно видел
old_load = "load_dotenv()"
new_load = """import os
from pathlib import Path
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)"""

if old_load in code and "dotenv_path" not in code:
    code = code.replace(old_load, new_load)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ Путь к .env в main.py исправлен на абсолютный.")
