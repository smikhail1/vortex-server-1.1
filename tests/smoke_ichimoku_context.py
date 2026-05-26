from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ichimoku_context import calculate_ichimoku, build_ichimoku_snapshot_for_symbols


def make_candles(direction="up", n=80):
    out = []
    base = 100.0
    for i in range(n):
        if direction == "up":
            close = base + i * 0.5
        elif direction == "down":
            close = base - i * 0.5
        else:
            close = base + ((i % 5) - 2) * 0.1
        out.append({
            "ts": i,
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000.0,
            "quote_volume": 100000.0,
        })
    return out


class FakeCandleService:
    def get_symbol_snapshot(self, symbol, market="fut"):
        if symbol == "UPUSDT":
            return {"candles_30m": make_candles("up"), "candles_4h": make_candles("up")}
        if symbol == "DOWNUSDT":
            return {"candles_30m": make_candles("down"), "candles_4h": make_candles("down")}
        return {"candles_30m": [], "candles_4h": []}


def test_bullish_context():
    d = calculate_ichimoku(make_candles("up"), timeframe="30m")
    assert d["available"] is True
    assert d["cloud_state"] == "above_cloud"
    assert d["long_support"] == "supportive"
    assert d["short_support"] == "against"


def test_bearish_context():
    d = calculate_ichimoku(make_candles("down"), timeframe="30m")
    assert d["available"] is True
    assert d["cloud_state"] == "below_cloud"
    assert d["short_support"] == "supportive"
    assert d["long_support"] == "against"


def test_not_enough_data():
    d = calculate_ichimoku(make_candles("up", n=20), timeframe="30m")
    assert d["available"] is False
    assert d["cloud_state"] == "no_data"


def test_snapshot_builder():
    snap = build_ichimoku_snapshot_for_symbols(
        symbols=["UPUSDT", "DOWNUSDT", "EMPTYUSDT"],
        candle_service=FakeCandleService(),
    )
    assert snap["symbols_count"] == 3
    assert snap["available_count"] == 2
    assert snap["summary"]["long_support_counts"]["supportive"] >= 1
    assert snap["summary"]["short_support_counts"]["supportive"] >= 1


if __name__ == "__main__":
    test_bullish_context()
    test_bearish_context()
    test_not_enough_data()
    test_snapshot_builder()
    print("OK: smoke_ichimoku_context")
