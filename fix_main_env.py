import os

filename = "main.py"
if not os.path.exists(filename):
    print(f"❌ Файл {filename} не найден!")
    exit(1)

with open(filename, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Проверяем, нет ли уже импорта
if any("load_dotenv" in line for line in lines):
    print("⚠️ dotenv уже импортирован в main.py")
    exit(0)

# Вставляем строки в самое начало файла
dotenv_code = [
    "from dotenv import load_dotenv\n",
    "load_dotenv()\n",
    "\n"
]

new_content = dotenv_code + lines

with open(filename, "w", encoding="utf-8") as f:
    f.writelines(new_content)

print("✅ dotenv успешно добавлен в начало main.py")
