#!/usr/bin/env bash
set -e

echo "== RUN FEE GUARD TESTS =="
python3 test_fee_guard_scenarios.py

echo
echo "== QUICK STRATEGY CHECK =="
python3 - <<'PY'
from strategy import SwingStrategy

s = SwingStrategy()

small = {
    "price": 100.0,
    "atr": 0.1,
    "ema20": 100.0,
    "ema50": 99.8,
    "rsi_main": 56.0,
    "vol_ratio": 1.2,
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
    "recent_high": 102.0,
    "recent_low": 99.0,
}

good = {
    "price": 100.0,
    "atr": 3.0,
    "ema20": 100.0,
    "ema50": 99.4,
    "rsi_main": 57.0,
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
    "recent_high": 105.0,
    "recent_low": 98.0,
}

print("Small spot:", s.analyze_spot(small, "allow_all"))
print("Good spot:", s.analyze_spot(good, "allow_all"))

small_fut = dict(small)
small_fut["trend_4h"] = "strong_down"
small_fut["trend_bias_30m"] = "down"
small_fut["near_support"] = False
small_fut["near_resistance"] = True
small_fut["pullback_long_ready"] = False
small_fut["pullback_short_ready"] = True
small_fut["recent_low"] = 98.0
small_fut["recent_high"] = 101.0
small_fut["ema20"] = 100.0
small_fut["ema50"] = 100.2

good_fut = dict(good)
good_fut["trend_4h"] = "strong_down"
good_fut["trend_bias_30m"] = "down"
good_fut["near_support"] = False
good_fut["near_resistance"] = True
good_fut["pullback_long_ready"] = False
good_fut["pullback_short_ready"] = True
good_fut["recent_low"] = 95.0
good_fut["recent_high"] = 103.0
good_fut["ema20"] = 100.0
good_fut["ema50"] = 100.4

print("Small futures:", s.analyze_futures(small_fut, "allow_all"))
print("Good futures:", s.analyze_futures(good_fut, "allow_all"))
PY