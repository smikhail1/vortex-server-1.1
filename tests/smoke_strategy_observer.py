from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from strategy_observer import build_strategy_observer_snapshot
class DummyStrategy:
    def analyze_futures(self, current, macro_filter="allow_all"):
        if current.get("adx", 0) >= 70:
            return {"should_open": True, "signal": "LONG", "score": 80, "setup_type": "momentum_long", "args_text": "test | EA:B/74 ALLOW_SHADOW", "threshold": 7}
        if current.get("adx", 0) >= 50:
            return {"should_open": True, "signal": "SHORT", "score": 7, "setup_type": "trend_short_v1.8.1", "args_text": "ADX ok but no EA", "threshold": 7}
        return {"should_open": False, "signal": None, "score": 3, "setup_type": None, "args_text": "", "blocked_reason": "weak adx", "threshold": 7}
def test_snapshot_classification():
    dashboard={"meta":{"mode":"PAPER"},"counts":{},"positions":{},"market":{"prices":{"AAAUSDT":1.0,"BBBUSDT":2.0,"PRICEONLY":3.0},"ta_data":{"AAAUSDT":{"price":1.0,"adx":80,"rsi_main":55,"rsi_slope":0.5,"ema20":0.9,"ema50":0.8,"vol_ratio":1.5,"trend_4h":"up","atr":0.1},"BBBUSDT":{"price":2.0,"adx":55,"rsi_main":45,"rsi_slope":-0.2,"ema20":2.1,"ema50":2.2,"vol_ratio":0.7,"trend_4h":"down","atr":0.1}}}}
    snap=build_strategy_observer_snapshot(dashboard=dashboard,strategy=DummyStrategy(),macro_filter="allow_all",trades_path="/tmp/non_existing_trades.csv")
    assert snap["schema_version"] == "1.8.21i-a-r2"
    assert snap["summary"]["symbols_total"] == 3
    assert snap["summary"]["analyzed_count"] == 2
    assert snap["summary"]["no_ta_count"] == 1
    assert snap["summary"]["ready_allowed_count"] == 1
    assert snap["summary"]["raw_ready_no_ea_count"] == 1
    assert any(x["symbol"] == "PRICEONLY" and x["state"] == "NO_TA_DATA" for x in snap["symbols"])
if __name__ == "__main__":
    test_snapshot_classification(); print("OK: smoke_strategy_observer")
