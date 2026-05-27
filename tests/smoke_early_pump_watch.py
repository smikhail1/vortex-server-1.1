
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pump_short_advisor import analyze_symbol


def make_early_pump(n=80):
    out = []
    price = 1.0
    for i in range(n):
        if i < n - 12:
            price *= 1.0002
        else:
            price *= 1.0042
        vol = 1000 * (2.4 if i >= n - 8 else 1.0)
        out.append({
            "ts": i,
            "open": price * 0.998,
            "high": price * 1.004,
            "low": price * 0.996,
            "close": price,
            "volume": vol,
            "quote_volume": vol * price,
        })
    return out


def test_early_pump_watch_phase():
    row = analyze_symbol("EARLYUSDT", make_early_pump(), make_early_pump(40))
    assert row["available"] is True
    assert row["phase"] == "EARLY_PUMP_WATCH", row
    assert row["score"] >= 30
    assert row["waiting_for"] == "pump_confirmation"


if __name__ == "__main__":
    test_early_pump_watch_phase()
    print("OK: smoke_early_pump_watch")
