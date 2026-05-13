import os

file_path = 'strategy.py'
if os.path.exists(file_path):
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Исправляем аргумент p на price в расчетах
    content = content.replace('calculate_futures_trade(self, p, side, atr', 'calculate_futures_trade(self, price, side, atr')
    content = content.replace('calculate_spot_ladder(self, p, atr', 'calculate_spot_ladder(self, price, atr')
    
    # Также внутри функций меняем использование p на price
    content = content.replace('p, atr = safe_float(p)', 'price, atr = safe_float(price)')
    content = content.replace('round(p + atr', 'round(price + atr')
    content = content.replace('round(p - atr', 'round(price - atr')
    
    with open(file_path, 'w') as f:
        f.write(content)
    print("✅ Аргументы в strategy.py исправлены на 'price'")
