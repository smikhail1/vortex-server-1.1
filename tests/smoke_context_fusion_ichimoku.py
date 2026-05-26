
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from context_fusion import build_context_fusion_snapshot


def test_ichimoku_is_in_fusion_row_and_affects_score():
    strategy = {
        "symbols": [
            {
                "symbol": "TESTUSDT",
                "state": "RAW_READY_NO_EA",
                "strategy": {
                    "signal": "SHORT",
                    "score": 8,
                    "setup_type": "trend_short_v1.8.1",
                    "args_text": "test",
                },
                "policy": {"code": "BLOCK_NO_EA", "reason": "missing"},
                "ea": {"present": False, "grade": "", "score": 0},
            }
        ],
        "summary": {},
    }
    heatmap = {
        "summary": {"bias": "strong_bearish", "net_bias_score": -35, "long_pressure": 10, "short_pressure": 70},
        "symbols": [{"symbol": "TESTUSDT"}],
    }
    setup = {
        "summary": {},
        "symbols": [
            {
                "symbol": "TESTUSDT",
                "preferred_zone": "short_pullback_zone",
                "short_zone_quality": 80,
                "long_zone_quality": 10,
                "range_position_pct": 80,
                "warnings": [],
            }
        ],
    }
    ichi = {
        "summary": {"available_count": 1},
        "symbols": [
            {
                "symbol": "TESTUSDT",
                "available": True,
                "trend_bias": "bearish",
                "cloud_state": "below_cloud",
                "tk_state": "bearish",
                "cloud_bias": "bearish",
                "long_support": "against",
                "short_support": "supportive",
                "quality": 72,
                "warnings": [],
            }
        ],
    }

    snap = build_context_fusion_snapshot(strategy, heatmap, setup, ichimoku_snapshot=ichi)
    row = snap["symbols"][0]

    assert row["ichimoku"]["available"] is True
    assert row["ichimoku"]["support_status"] == "supportive"
    assert row["final"]["view"] == "RAW_CANDIDATE_WAIT_EA_GOOD_ZONE"
    assert any("ichimoku_support=" in x for x in row["final"]["reasons"])


def test_ichimoku_against_adds_warning():
    strategy = {
        "symbols": [
            {
                "symbol": "LONGUSDT",
                "state": "RAW_READY_NO_EA",
                "strategy": {"signal": "LONG", "score": 8, "setup_type": "momentum_long", "args_text": "test"},
                "policy": {"code": "BLOCK_NO_EA", "reason": "missing"},
                "ea": {},
            }
        ],
        "summary": {},
    }
    heatmap = {"summary": {"bias": "mild_bullish", "net_bias_score": 15}, "symbols": [{"symbol": "LONGUSDT"}]}
    setup = {"summary": {}, "symbols": [{"symbol": "LONGUSDT", "preferred_zone": "long_pullback_zone", "long_zone_quality": 75}]}
    ichi = {
        "summary": {},
        "symbols": [
            {
                "symbol": "LONGUSDT",
                "available": True,
                "trend_bias": "bearish",
                "cloud_state": "below_cloud",
                "tk_state": "bearish",
                "cloud_bias": "bearish",
                "long_support": "against",
                "short_support": "supportive",
                "quality": 72,
                "warnings": [],
            }
        ],
    }

    snap = build_context_fusion_snapshot(strategy, heatmap, setup, ichimoku_snapshot=ichi)
    row = snap["symbols"][0]
    assert row["ichimoku"]["support_status"] == "against"
    assert any("ichimoku_against=" in x for x in row["final"]["warnings"])


if __name__ == "__main__":
    test_ichimoku_is_in_fusion_row_and_affects_score()
    test_ichimoku_against_adds_warning()
    print("OK: smoke_context_fusion_ichimoku")
