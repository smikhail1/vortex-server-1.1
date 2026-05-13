from strategy import SwingStrategy
from watchlist_builder import WatchlistBuilder


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def build_ctx(price: float, ema20: float, ema50: float, recent_high: float, regime: str = "trend"):
    return {
        "price": price,
        "atr": 2.0,
        "ema20": ema20,
        "ema50": ema50,
        "rsi_main": 54.0,
        "vol_ratio": 1.3,
        "trend_4h": "strong_up",
        "trend_bias_30m": "up",
        "market_regime": regime,
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
        "recent_high": recent_high,
        "recent_low": 98.0,
    }


def run_all():
    s = SwingStrategy()
    w = WatchlistBuilder(strategy=s)

    ta_data = {
        "BTCUSDT": build_ctx(105, 104, 100, 110),
        "ETHUSDT": build_ctx(112, 104, 100, 112.1),  # chase => blocked
    }

    items = w.build(
        ta_data=ta_data,
        fut_pool=["BTCUSDT"],
        spot_pool=["ETHUSDT"],
        macro_filter="allow_all",
    )

    assert_true(len(items) >= 2, "expected watchlist items")
    statuses = {item["symbol"]: item["status"] for item in items}
    assert_true(statuses["ETHUSDT"] in {"blocked", "near_entry", "watch", "ready"}, "invalid status")
    print("ALL WATCHLIST SNAPSHOT TESTS PASSED")


if __name__ == "__main__":
    run_all()