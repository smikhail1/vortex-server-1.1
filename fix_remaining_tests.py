import os

files_to_fix = [
    "test_integration_scenarios_v2.py",
    "test_console_scenarios.py",
    "test_fee_guard_scenarios.py"
]

for fname in files_to_fix:
    if os.path.exists(fname):
        with open(fname, "r") as f:
            content = f.read()
        
        # Глобальная замена BUY на LONG
        content = content.replace('== "BUY"', '== "LONG"')
        content = content.replace('["signal"] == "BUY"', '["signal"] == "LONG"')
        
        # Добавляем в контексты v1.8.0 поля, если их нет
        if '"price":' in content and '"atr_pct":' not in content:
            content = content.replace('"price":', '"atr_pct": 2.0, "ema10": 100, "price":')
        
        with open(fname, "w") as f:
            f.write(content)
        print(f"✅ Fixed {fname}")

