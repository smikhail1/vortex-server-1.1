#!/usr/bin/env python3
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spot_planner import SpotPlannerEngine, planner_rr_grade


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    source = (ROOT / "spot_planner.py").read_text(encoding="utf-8")
    require("advisor_status" in source, "advisor_status missing")
    require("advisor_verdict" in source, "advisor_verdict missing")
    require('"zone_grade": zone_quality' in source, "zone_grade alias missing")
    require("position_plan" in source, "position_plan missing")
    require('"planner_swing_spot"' in source, "swing plan_type missing")
    require('"planner_swing_spot_v1"' in source, "management profile missing")
    require('"timeout_sec": 2419200' in source, "swing timeout must not be intraday")
    require('"weak_progress_sec": 604800' in source, "swing weak progress must not be intraday")
    require("block_longs = True" not in source and "block_shorts = True" not in source, "quality layer must not add hard liquidity blocks")
    require(planner_rr_grade(1.1) == "bad", "RR bad grade mismatch")
    require(planner_rr_grade(1.5) == "acceptable", "RR acceptable grade mismatch")
    require(planner_rr_grade(2.0) == "good", "RR good grade mismatch")
    require(planner_rr_grade(3.0) == "excellent", "RR excellent grade mismatch")

    payload = {
        "price": 5.18,
        "metrics": {
            "d1": {"price": 5.18, "ema20": 5.0, "ema50": 4.8},
            "w1": {"price": 5.18, "ema20": 5.0, "ema50": 4.8},
            "h4": {"price": 5.18, "ema20": 5.25, "ema50": 5.10, "atr": 0.15, "atr_pct": 2.9, "recent_high": 5.4, "recent_low": 4.9},
        },
    }
    idea = SpotPlannerEngine()._build_idea(
        "INJUSDT",
        payload,
        {"risk_state": "neutral", "global_filter": "allow_all"},
        rank=1,
        liquidity_by_symbol={"INJUSDT": {"available": True, "liquidity_bias": "mild_long"}},
    )
    require(idea["plan_type"] == "planner_swing_spot", "wrong plan_type")
    require(idea["plan_version"] == "1.8.24-g", "wrong plan_version")
    require(idea["management_profile"] == "planner_swing_spot_v1", "wrong profile")
    require(idea["position_plan"]["source"] == "planner", "position plan missing source")
    require(idea["zone_quality"] is not None, "zone_quality must not be None")
    require(idea["zone_grade"] == idea["zone_quality"], "zone alias mismatch")
    require(idea["liquidity_alignment"] == "supportive", "shadow liquidity mapping mismatch")
    require(idea["captured_at"] is None, "captured_at belongs to immutable open snapshot")
    print("OK: smoke_planner_quality_layer")


if __name__ == "__main__":
    main()
