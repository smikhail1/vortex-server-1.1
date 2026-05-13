import json, os
from datetime import datetime

file = 'trades_state.json'
if not os.path.exists(file):
    print("Файл сделок пока пуст.")
    exit()

with open(file, 'r') as f:
    data = json.load(f)

print(f"\n=== ОТЧЕТ ПО СДЕЛКАМ VORTEX (Всего закрыто: {len(data.get('closed', []))}) ===")

for pos in data.get('closed', []):
    ot = datetime.fromtimestamp(pos['open_time']).strftime('%H:%M:%S')
    ct = datetime.fromtimestamp(pos['closed_at']).strftime('%H:%M:%S')
    print(f"[{pos['symbol']}] {pos['side']} | Вход: {pos['entry']} ({ot}) | Выход: {pos['current_price']} ({ct})")
    print(f"      Результат: {pos['pnl_net']:.4f} USDT | Причина: {pos['close_reason']}")
    print("-" * 50)

print("\n=== АКТИВНЫЕ ПОЗИЦИИ ===")
for k, pos in data.get('open', {}).items():
    print(f"[{pos['symbol']}] {pos['side']} | Вход: {pos['entry']} | Тейк: {pos['tp']:.4f} | Стоп: {pos['sl']:.4f}")
    print(f"      Текущий PnL: {pos['pnl_net']:.4f} USDT | Удержание: {pos['hold_sec'] // 60} мин.")
