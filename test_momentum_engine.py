from momentum_engine import MomentumEngine
from strategy import SwingStrategy

def scenario_momentum_behavior_in_dead_regime():
    engine = MomentumEngine()
    data = {
        "symbol": "APEUSDT",
        "price": 0.145,
        "atr": 0.004,
        "ema20": 0.140,
        "ema50": 0.130,
        "recent_high": 0.175,
        "recent_low": 0.138,
        "rsi_main": 50,
        "vol_ratio": 1.35,
        "range_pct": 16.7,
        "change_pct": -4.8,
        "breakout": False,
        "breakout_dir": "",
        "trend_bias_1h": "neutral",
        "trend_4h": "neutral",
    }
    # Движок может найти сетап (active=True), но стратегия должна его отсечь
    sig = engine.evaluate_futures(data, market_regime="dead")
    print(f"DEBUG: Engine found signal active={sig.active} side={sig.side}")
    print("OK: scenario_momentum_behavior_in_dead_regime")

def scenario_momentum_confirmed_short_in_trend():
    engine = MomentumEngine()
    data = {
        "symbol": "APEUSDT",
        "price": 0.145,
        "atr": 0.004,
        "ema20": 0.150,
        "ema50": 0.160,
        "recent_high": 0.175,
        "recent_low": 0.138,
        "rsi_main": 36,
        "vol_ratio": 3.8,
        "range_pct": 16.7,
        "change_pct": -6.2,
        "breakout": True,
        "breakout_dir": "down",
        "trend_bias_1h": "down",
        "trend_4h": "strong_down",
    }
    sig = engine.evaluate_futures(data, market_regime="trend")
    assert sig.active is True
    assert sig.confirmed is True
    assert sig.side == "SHORT"
    print("OK: scenario_momentum_confirmed_short_in_trend")

def scenario_strategy_dead_regime_hard_block():
    strategy = SwingStrategy()
    data = {
        "symbol": "APEUSDT",
        "price": 0.145,
        "atr": 0.004,
        "ema10": 0.142,
        "ema20": 0.140,
        "ema50": 0.130,
        "recent_high": 0.175,
        "recent_low": 0.138,
        "rsi_main": 50,
        "vol_ratio": 1.35,
        "market_regime": "dead",
        "trend_4h": "neutral",
        "breakout": False,
    }
    res = strategy.analyze_futures(data, macro_filter="allow_all")
    # ГЛАВНАЯ ПРОВЕРКА: Стратегия ОБЯЗАНА блокировать вход в DEAD режиме
    assert res["should_open"] is False, f"Strategy must block DEAD regime, but got: {res}"
    print(f"OK: scenario_strategy_dead_regime_hard_block (reason: {res['blocked_reason']})")

if __name__ == "__main__":
    scenario_momentum_behavior_in_dead_regime()
    scenario_momentum_confirmed_short_in_trend()
    scenario_strategy_dead_regime_hard_block()
    print("ALL MOMENTUM TESTS PASSED")
