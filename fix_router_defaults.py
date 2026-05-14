import os

filename = "execution_router.py"
with open(filename, "r", encoding="utf-8") as f:
    code = f.read()

# Меняем жесткую привязку к CONFIG на гибкую проверку .env
old_init = 'self.spot_mode = safe_str(mode, "PAPER").upper()'
new_init = 'self.spot_mode = os.environ.get("DEFAULT_SPOT_MODE", safe_str(mode, "PAPER")).upper()'

if old_init in code:
    code = code.replace(old_init, new_init)
    code = code.replace('self.fut_mode = safe_str(mode, "PAPER").upper()', 
                        'self.fut_mode = os.environ.get("DEFAULT_FUT_MODE", safe_str(mode, "PAPER")).upper()')
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ Роутер теперь приоритетно читает режимы из .env")
else:
    print("❌ Строка для замены не найдена или уже изменена.")
