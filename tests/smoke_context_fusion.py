from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from context_fusion import build_context_fusion_snapshot


def test_context_fusion_snapshot():
    strategy = {
        "summary": {"raw_ready_no_ea_count": 1},
        "symbols": [
            {
                "symbol": "AAAUSDT",
                "state": "RAW_READY_NO_EA",
                "strategy": {"signal": "LONG", "score": 8, "setup_type": "trend_follow_v1.7", "args_text": "x"},
                "policy": {"code": "BLOCK_NO_EA", "reason": "missing EA"},
                "ea": {"present": False},
            }
        ],
    }

    heatmap = {
        "summary": {"bias": "mild_bullish", "net_bias_score": 12.5, "long_pressure": 55, "short_pressure": 40},
        "symbols": [
            {"symbol": "AAAUSDT", "local_bias": "long_context", "trend_4h": "up", "adx": 30, "rsi_main": 55, "vol_ratio": 1.2}
        ],
    }

    setup = {
        "summary": {"long_zone_65_count": 1},
        "symbols": [
            {
                "symbol": "AAAUSDT",
                "preferred_zone": "long_pullback_zone",
                "long_zone_quality": 80,
                "short_zone_quality": 10,
                "range_position_pct": 30,
                "near_support": True,
                "near_resistance": False,
                "near_ema20": True,
                "warnings": ["near_support"],
            }
        ],
    }

    snap = build_context_fusion_snapshot(strategy, heatmap, setup, {"total_seen": 10})
    assert snap["schema_version"] == "1.8.21k-c"
    assert snap["summary"]["symbols_count"] == 1
    row = snap["symbols"][0]
    assert row["symbol"] == "AAAUSDT"
    assert row["final"]["view"] == "RAW_CANDIDATE_WAIT_EA_GOOD_ZONE"


if __name__ == "__main__":
    test_context_fusion_snapshot()
    print("OK: smoke_context_fusion")
