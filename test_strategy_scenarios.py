from strategy import SwingStrategy
from watchlist_builder import WatchlistBuilder

def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)

def build_base_long_context():
    return {
        "price": 105.0,
        "atr": 2.0,
        "atr_pct": 1.9,
        "ema10": 104.5,
        "ema20": 104.0,
        "ema50": 100.0,
        "rsi_main": 54.0,
        "vol_ratio": 2.5,
        "trend_4h": "strong_up",
        "trend_bias_30m": "up",
        "market_regime": "trend",
        "breakout": False,
        "breakout_dir": "",
        "near_support": True,
        "near_resistance": False,
        "pullback_long_ready": False,
        "pullback_short_ready": False,
        "retest_long_ready": True,
        "retest_short_ready": False,
        "vol_confirmed": True,
        "breakout_volume_confirmed": True,
        "recent_high": 110.0,
        "recent_low": 98.0,
        "score": 10
    }

def scenario_valid_retest_long():
    s = SwingStrategy()
    data = build_base_long_context()
    result = s.analyze_spot(data, "allow_all")
    assert_true(result["signal"] == "LONG", f"spot signal should be LONG, got: {result}")
    assert_true("retest" in result["setup_type"], "setup should be retest")
    print("OK: scenario_valid_retest_long")

def scenario_blocked_by_macro():
    s = SwingStrategy()
    data = build_base_long_context()
    result = s.analyze_spot(data, "block_longs")
    assert_true(result["should_open"] is False, "should be blocked")
    assert_true("macro" in (result["blocked_reason"] or ""), "macro block expected")
    print("OK: scenario_blocked_by_macro")

def scenario_no_chase_long():
    s = SwingStrategy()
    data = build_base_long_context()
    
    # Имитируем улетевший паровоз (перегрет RSI, нет пробоя, нет ретеста)
    data["breakout"] = False
    data["retest_long_ready"] = False
    data["price"] = 125.0
    data["recent_high"] = 125.1
    data["rsi_main"] = 86.0
    
    result = s.analyze_spot(data, "allow_all")
    assert_true(result["should_open"] is False, f"chase must be blocked, got: {result}")
    print("OK: scenario_no_chase_long")

def scenario_watchlist_mapping():
    s = SwingStrategy()
    w = WatchlistBuilder(strategy=s)
    ta_data = {"BTCUSDT": build_base_long_context()}
    items = w.build(ta_data=ta_data, fut_pool=[], spot_pool=["BTCUSDT"], macro_filter="allow_all")
    assert_true(len(items) > 0, "watchlist must not be empty")
    assert_true(items[0]["status"] in {"ready", "near_entry", "watch", "blocked"}, "bad watchlist status")
    print("OK: scenario_watchlist_mapping")

def run_all():
    scenario_valid_retest_long()
    scenario_blocked_by_macro()
    scenario_no_chase_long()
    scenario_watchlist_mapping()
    print("ALL STRATEGY TESTS PASSED")

if __name__ == "__main__":
    run_all()
