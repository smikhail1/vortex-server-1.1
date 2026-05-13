import os
import re

file_path = 'strategy.py'
with open(file_path, 'r') as f:
    content = f.read()

# 1. Исправляем calculate_futures_trade
new_fut_method = """
    def calculate_futures_trade(self, price, side, atr, setup_type="", args_text=""):
        price = float(price)
        atr = float(atr)
        # Рассчитываем уровни (ATR-based)
        if side.lower() == "long":
            tp = price + (atr * 2.0)
            sl = price - (atr * 1.5)
        else:
            tp = price - (atr * 2.0)
            sl = price + (atr * 1.5)
            
        return {
            "price": round(price, 8),
            "qty": 0,  # Будет рассчитано в Risk Manager
            "leverage": 3.0,
            "tp": round(tp, 8),
            "sl": round(sl, 8),
            "atr": round(atr, 8),
            "setup_type": setup_type,
            "args_text": args_text
        }
"""

# 2. Исправляем calculate_spot_ladder
new_spot_method = """
    def calculate_spot_ladder(self, price, atr, setup_type="", args_text=""):
        price = float(price)
        atr = float(atr)
        return {
            "price": round(price, 8),
            "qty": 0,
            "tp": round(price + (atr * 3.0), 8),
            "atr": round(atr, 8),
            "setup_type": setup_type,
            "args_text": args_text
        }
"""

# Заменяем старые методы через регулярные выражения (ищем от def до return { ... })
content = re.sub(r'def calculate_futures_trade\(.*?return \{.*?\}', new_fut_method, content, flags=re.DOTALL)
content = re.sub(r'def calculate_spot_ladder\(.*?return \{.*?\}', new_spot_method, content, flags=re.DOTALL)

with open(file_path, 'w') as f:
    f.write(content)
print("✅ Функции в strategy.py полностью обновлены.")
