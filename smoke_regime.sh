#!/usr/bin/env bash
set -e

echo "== RUN REGIME TESTS =="
python3 test_regime_scenarios.py

echo
echo "== QUICK TA / REGIME SMOKE =="
python3 - <<'PY'
from market_regime import MarketRegimeEvaluator

r = MarketRegimeEvaluator()

print("Trend up:", r.classify_trend(price=110, ema20=105, ema50=100))
print("Trend down:", r.classify_trend(price=90, ema20=95, ema50=100))
print("Macro:", r.evaluate_macro({"btc_trend": "strong_bearish", "fng_value": 22, "oi_amount": 1000}))
print("Symbol context:", r.build_symbol_context({
    "price": 110,
    "ema10": 108,
    "ema20": 105,
    "ema50": 100,
    "atr_pct": 3.1,
    "vol_ratio": 1.3,
    "breakout": True,
}))
PY