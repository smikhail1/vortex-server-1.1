from market_regime import MarketRegimeEvaluator


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def scenario_trend_up() -> None:
    r = MarketRegimeEvaluator()
    trend = r.classify_trend(price=110, ema20=105, ema50=100)
    assert_true(trend in {"up", "strong_up"}, "trend up classification failed")
    print("OK: scenario_trend_up")


def scenario_trend_down() -> None:
    r = MarketRegimeEvaluator()
    trend = r.classify_trend(price=90, ema20=95, ema50=100)
    assert_true(trend in {"down", "strong_down"}, "trend down classification failed")
    print("OK: scenario_trend_down")


def scenario_macro_risk_off() -> None:
    r = MarketRegimeEvaluator()
    result = r.evaluate_macro({
        "btc_trend": "strong_bearish",
        "fng_value": 25,
        "oi_amount": 12345,
    })
    assert_true(result["risk_state"] == "risk_off", "risk_off classification failed")
    assert_true(result["global_filter"] == "block_longs", "global filter failed")
    print("OK: scenario_macro_risk_off")


def scenario_macro_risk_on() -> None:
    r = MarketRegimeEvaluator()
    result = r.evaluate_macro({
        "btc_trend": "strong_bullish",
        "fng_value": 70,
        "oi_amount": 12345,
    })
    assert_true(result["risk_state"] == "risk_on", "risk_on classification failed")
    print("OK: scenario_macro_risk_on")


def scenario_symbol_context() -> None:
    r = MarketRegimeEvaluator()
    ctx = r.build_symbol_context({
        "price": 110,
        "ema10": 108,
        "ema20": 105,
        "ema50": 100,
        "atr_pct": 3.2,
        "vol_ratio": 1.4,
        "breakout": True,
    })
    assert_true("trend_4h" in ctx, "missing trend_4h")
    assert_true("trend_bias_30m" in ctx, "missing trend_bias_30m")
    assert_true("market_regime" in ctx, "missing market_regime")
    print("OK: scenario_symbol_context")


def run_all() -> None:
    scenario_trend_up()
    scenario_trend_down()
    scenario_macro_risk_off()
    scenario_macro_risk_on()
    scenario_symbol_context()
    print("ALL REGIME TESTS PASSED")


if __name__ == "__main__":
    run_all()