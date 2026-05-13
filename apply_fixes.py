import os

print("Начинаю установку патча v1.7.1...")

# --- ПАТЧ MAIN.PY ---
with open("main.py", "r", encoding="utf-8") as f:
    main_code = f.read()

# Фикс 1: Правильный расчет объема с учетом плеча
main_code = main_code.replace(
    'qty = CONFIG.trading.futures_margin_usdt / price',
    'notional_size = CONFIG.trading.futures_margin_usdt * ladder.get("leverage", 3.0)\n                    qty = notional_size / price'
)

# Фикс 2: Возврат потерянных тейк-профитов (TP0 и TP2)
old_tp = """                                    tp=ladder["tp"],
                                    sl=ladder["sl"],
                                    atr=atr_abs,
                                    leverage=ladder["leverage"],"""

new_tp = """                                    tp0=ladder.get("tp0"),
                                    tp=ladder.get("tp"),
                                    tp2=ladder.get("tp2"),
                                    sl=ladder.get("sl"),
                                    atr=atr_abs,
                                    leverage=ladder.get("leverage", 3.0),"""

main_code = main_code.replace(old_tp, new_tp)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(main_code)
print("✅ main.py: TP0/TP2 и расчет маржи исправлены")


# --- ПАТЧ TRADE_MANAGER.PY ---
with open("trade_manager.py", "r", encoding="utf-8") as f:
    tm_code = f.read()

# Фикс 3: Отключение прямых запросов для защиты от API-лимитов
tm_code = tm_code.replace(
    'l = await self._fetch_bitget_futures_price(symbol)',
    'l = 0.0  # [FIX] Запрос отключен. Цена берется безопасно из кэша StateManager'
)

with open("trade_manager.py", "w", encoding="utf-8") as f:
    f.write(tm_code)
print("✅ trade_manager.py: Защита от HTTP 429 внедрена")
