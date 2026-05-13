#!/usr/bin/env bash
set -e

echo "== RUN STRATEGY TESTS =="
python3 test_strategy_scenarios.py

echo
echo "== QUICK STRATEGY SMOKE =="
python3 - <<'PY'
from strategy import SwingStrategy

s = SwingStrategy()

data = {
    "price": 105.0,
    "atr": 2.0,
    "ema20": 104.0,
    "ema50": 100.0,
    "rsi_main": 54.0,
    "vol_ratio": 1.3,
    "trend_4h": "strong_up",
    "trend_bias_30m": "up",
    "market_regime": "trend",
    "breakout": False,
    "breakout_dir": "",
    "near_support": True,
    "near_resistance": False,
    "pullback_long_ready": True,
    "pullback_short_ready": False,
    "retest_long_ready": False,
    "retest_short_ready": False,
    "vol_confirmed": True,
    "breakout_volume_confirmed": True,
    "recent_high": 110.0,
    "recent_low": 98.0,
}

print("Spot:", s.analyze_spot(data, "allow_all"))
print("Futures:", s.analyze_futures(data, "allow_all"))
PY