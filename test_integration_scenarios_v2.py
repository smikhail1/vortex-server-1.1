import asyncio
from execution_router import ExecutionRouter
from risk_manager import RiskManager
from strategy import SwingStrategy
from decision_engine import DecisionEngine

def assert_true(cond, msg):
    if not cond: raise AssertionError(msg)

def scenario_strategy_threshold_block():
    s = SwingStrategy()
    data = {
        "price": 100, "atr": 2, "atr_pct": 2.0, "ema10": 101, "ema20": 102, "ema50": 105,
        "vol_ratio": 2.5, "trend_4h": "up", "market_regime": "trend",
        "retest_long_ready": True, "rsi_main": 55, "vol_confirmed": True, "score": 8
    }
    res = s.analyze_spot(data, "allow_all")
    assert_true(res["signal"] == "LONG", "Strategy should return LONG")
    print("OK: scenario_strategy_threshold_block")

def run_all():
    scenario_strategy_threshold_block()
    print("ALL INTEGRATION TESTS PASSED")

if __name__ == "__main__":
    run_all()
