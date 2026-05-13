from momentum_engine import MomentumEngine
from config import CONFIG

engine = MomentumEngine()

print("\n=== ⚙️ ТЕСТ МЕХАНИЗМОВ ВХОДА (VORTEX) ===")

# Базовый хороший сигнал (должен пройти)
good_data = {
    "symbol": "TESTUSDT", "price": 100, "atr": 5, "ema20": 98, "ema50": 95,
    "rsi_main": 55, "vol_ratio": 2.0, "change_pct": 5.0, "range_pct": 6.0,
    "funding_rate": 0.0001
}
macro_ok = {"funding_rates": {"TESTUSDT": 0.0001}}

# ТЕСТ 1: Блокировка перегретого лонга (Funding > 0.15%)
bad_funding_macro = {"funding_rates": {"TESTUSDT": 0.0020}}
res1 = engine.evaluate_futures(good_data, "trend", bad_funding_macro, "up")
print(f"1. Тест Funding: Ожидаем БЛОК -> {'✅ ПАСС' if not res1.active and 'funding block' in res1.reason else f'❌ ПРОВАЛ ({res1.reason})'}")

# ТЕСТ 2: Блокировка ложного пробоя (Открытый интерес падает)
res2 = engine.evaluate_futures(good_data, "trend", macro_ok, "down")
print(f"2. Тест OI Trend: Ожидаем БЛОК -> {'✅ ПАСС' if not res2.active and 'OI falling' in res2.reason else f'❌ ПРОВАЛ ({res2.reason})'}")

# ТЕСТ 3: Блокировка позднего входа (Слишком далеко от EMA)
late_data = good_data.copy()
late_data["price"] = 120 # Улетели на 20% от EMA
res3 = engine.evaluate_futures(late_data, "trend", macro_ok, "up")
print(f"3. Тест Дистанции EMA: Ожидаем БЛОК -> {'✅ ПАСС' if not res3.active and 'EMA dist too high' in res3.reason else f'❌ ПРОВАЛ ({res3.reason})'}")

print("\n=== 🔧 ТЕСТ КОНФИГУРАЦИИ (ДОПУСКИ) ===")
print(f"SL ATR Mult: {CONFIG.momentum.sl_atr_mult} (Ожидаем 2.0)")
print(f"BU Trigger: {CONFIG.position_guide.be_trigger_usdt} USDT (Ожидаем 0.25)")
print(f"Min Volume: {CONFIG.universe.min_quote_volume_usdt:,.0f} (Ожидаем 25,000,000)")
print("========================================\n")
