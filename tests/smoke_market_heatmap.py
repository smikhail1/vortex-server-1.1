from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_heatmap import build_market_heatmap_snapshot


def test_market_heatmap_snapshot():
    dashboard = {
        "market": {
            "prices": {
                "AAAUSDT": 10,
                "BBBUSDT": 20,
                "CCCUSDT": 30,
            },
            "ta_data": {
                "AAAUSDT": {
                    "price": 10,
                    "trend_4h": "up",
                    "adx": 50,
                    "rsi_main": 62,
                    "rsi_slope": 0.2,
                    "ema20": 9,
                    "ema50": 8,
                    "vol_ratio": 1.2,
                },
                "BBBUSDT": {
                    "price": 20,
                    "trend_4h": "down",
                    "adx": 45,
                    "rsi_main": 35,
                    "rsi_slope": -0.2,
                    "ema20": 21,
                    "ema50": 22,
                    "vol_ratio": 1.1,
                },
                "CCCUSDT": {
                    "price": 30,
                    "trend_4h": "up",
                    "adx": 20,
                    "rsi_main": 52,
                    "rsi_slope": 0.0,
                    "ema20": 29,
                    "ema50": 28,
                    "vol_ratio": 0.5,
                },
            },
        },
    }

    snap = build_market_heatmap_snapshot(dashboard)
    assert snap["schema_version"] == "1.8.21k-a"
    assert snap["summary"]["symbols_count"] == 3
    assert snap["summary"]["long_context_count"] == 1
    assert snap["summary"]["short_context_count"] == 1
    assert snap["summary"]["trend_up_pct"] > 0
    assert snap["top_long_context"][0]["symbol"] == "AAAUSDT"
    assert snap["top_short_context"][0]["symbol"] == "BBBUSDT"


if __name__ == "__main__":
    test_market_heatmap_snapshot()
    print("OK: smoke_market_heatmap")
