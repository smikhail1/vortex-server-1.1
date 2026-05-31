#!/usr/bin/env python3
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spot_position_advisor import SCHEMA, build_spot_position_advisor


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    source = (ROOT / "spot_position_advisor.py").read_text(encoding="utf-8")
    api = (ROOT / "api_server.py").read_text(encoding="utf-8")
    html = (ROOT / "web" / "market_analytics.html").read_text(encoding="utf-8")
    require("read_only" in source, "read_only marker missing")
    require("router.close" not in source, "shadow advisor must not call router close")
    require("close_spot" not in source, "shadow advisor must not close Spot")
    require("/api/analytics/spot-position-advisor" in api, "advisor endpoint missing")
    require("Spot Position Advisor" in html, "analytics block missing")

    result = build_spot_position_advisor(
        positions={"INJUSDT": {"symbol": "INJUSDT", "avg_price": 5.18, "qty": 1.0, "open_time": 1000}},
        ta_data={"INJUSDT": {"price": 5.60}},
        planner_snapshots={"INJUSDT": {
            "idea_id": "planner:INJ:1",
            "advisor_status": "WAIT_CONFIRMATION",
            "management_profile": "planner_swing_spot_v1",
            "position_plan": {"tp1": 5.55, "tp2": 6.05, "invalidation": 4.92, "weak_progress_sec": 604800},
        }},
        liquidity_payload={"items": [{"symbol": "INJUSDT", "liquidity_bias": "mild_long"}]},
        now_ts=1100,
    )
    require(result["schema"] == SCHEMA, "wrong schema")
    require(result["read_only"] is True, "advisor is not shadow-only")
    require(result["items_len"] == 1, "synthetic position missing")
    item = result["items"][0]
    require(item["would_action"] == "WOULD_TP1_PARTIAL", "TP1 shadow action mismatch")
    require(item["tp1_hit_shadow"] is True, "TP1 shadow flag missing")
    require(item["breakeven_shadow"] is True, "BE shadow flag missing")
    print("OK: smoke_spot_position_advisor")


if __name__ == "__main__":
    main()
