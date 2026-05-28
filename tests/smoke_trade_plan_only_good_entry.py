
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pump_short_advisor import _build_trade_plan_21mi


def make_candles(n=60):
    out = []
    price = 100.0
    for i in range(n):
        if i < 35:
            price *= 1.003
        elif i < 45:
            price *= 0.998
        else:
            price *= 0.992
        out.append({
            "ts": i,
            "open": price * 1.002,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 1000,
        })
    return out


def test_trade_plan_only_for_short_candidate():
    candles = make_candles()
    row = {
        "symbol": "TESTUSDT",
        "phase": "SHORT_CANDIDATE",
        "score": 70,
        "price": 92.0,
        "support_level": 94.0,
    }
    plan = _build_trade_plan_21mi(row, candles, [])
    assert plan is not None
    assert plan["available"] is True
    assert plan["side"] == "SHORT"
    assert plan["entry_zone"]["center"] == 94.0
    assert plan["stop"] > plan["entry_zone"]["center"]
    assert plan["tp1"] < plan["entry_zone"]["center"]
    assert plan["rr"]["tp1"] > 0


def test_no_plan_for_weak_or_watch():
    candles = make_candles()
    row = {
        "symbol": "TESTUSDT",
        "phase": "EARLY_PUMP_WATCH",
        "score": 80,
        "price": 100.0,
        "support_level": 95.0,
    }
    assert _build_trade_plan_21mi(row, candles, []) is None

    row["phase"] = "SHORT_CANDIDATE"
    row["score"] = 40
    assert _build_trade_plan_21mi(row, candles, []) is None


if __name__ == "__main__":
    test_trade_plan_only_for_short_candidate()
    test_no_plan_for_weak_or_watch()
    print("OK: smoke_trade_plan_only_good_entry")
