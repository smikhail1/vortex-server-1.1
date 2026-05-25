from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from setup_zone import build_setup_zone_snapshot, classify_setup_zone


def test_setup_zone_classification():
    long_ta = {
        "price": 100,
        "trend_4h": "up",
        "adx": 35,
        "rsi_main": 55,
        "vol_ratio": 1.2,
        "atr_pct": 1.0,
        "ema20": 99.8,
        "ema50": 95,
        "recent_high": 120,
        "recent_low": 99.6,
    }
    item = classify_setup_zone("AAAUSDT", long_ta)
    assert item["symbol"] == "AAAUSDT"
    assert item["near_ema20"] is True
    assert item["near_support"] is True
    assert item["long_zone_quality"] > item["short_zone_quality"]

    dashboard = {
        "market": {
            "prices": {"AAAUSDT": 100},
            "ta_data": {"AAAUSDT": long_ta},
        }
    }
    snap = build_setup_zone_snapshot(dashboard)
    assert snap["schema_version"] == "1.8.21k-b-r2"
    assert snap["summary"]["symbols_count"] == 1
    assert snap["top_long_zones"][0]["symbol"] == "AAAUSDT"


if __name__ == "__main__":
    test_setup_zone_classification()
    print("OK: smoke_setup_zone")
