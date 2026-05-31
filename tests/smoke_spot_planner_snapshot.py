#!/usr/bin/env python3
from pathlib import Path
import json
import tempfile
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trade_snapshot_recorder import TradeSnapshotRecorder


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    recorder_source = (ROOT / "trade_snapshot_recorder.py").read_text(encoding="utf-8")
    require("planner_snapshot" in recorder_source, "immutable planner snapshot missing")
    require("spot_args_text" in main_source, "compact planner log summary missing")
    require("router.open_spot_position" in main_source, "spot open path unexpectedly missing")

    path = Path(tempfile.mkdtemp(prefix="vortex_planner_snapshot_")) / "snapshots.jsonl"
    recorder = TradeSnapshotRecorder(path=str(path))
    idea = {
        "symbol": "INJUSDT",
        "setup_type": "spot_pullback",
        "score": 82,
        "tier": "A",
        "advisor_status": "WAIT_CONFIRMATION",
        "advisor_verdict": "valid_idea_wait_confirmation",
        "zone_quality": "in_zone",
        "rr_grade": "good",
        "market_alignment": "neutral",
        "liquidity_alignment": "supportive",
        "accumulation_zone": {"top": 5.25, "bottom": 5.10},
        "avg_entry": 5.17,
        "invalidation": 4.92,
        "targets": [{"price": 5.55}, {"price": 6.05}, {"price": 6.40}],
        "rr_ratio": 1.83,
        "plan_type": "planner_swing_spot",
        "plan_version": "1.8.24-g",
        "idea_id": "planner:INJUSDT:123",
        "generated_at": 123,
        "management_profile": "planner_swing_spot_v1",
        "position_plan": {"source": "planner", "tp1": 5.55, "timeout_sec": 2419200},
    }
    snapshot = recorder.record_open(
        symbol="INJUSDT",
        market="SPOT",
        side="BUY",
        result={"code": "00000", "data": {"entry": 5.18, "qty": 1.0}},
        current={"price": 5.18, "atr": 0.15},
        analysis={"setup_type": "planner_spot", "args_text": "Planner A"},
        watch={},
        planner_idea=idea,
    )
    saved = snapshot["planner_snapshot"]
    require(saved["position_plan"]["source"] == "planner", "position_plan missing")
    require(saved["rr_grade"] == "good", "rr_grade missing")
    require(saved["zone_quality"] == "in_zone", "zone_quality missing")
    require(saved["advisor_status"] == "WAIT_CONFIRMATION", "advisor status missing")
    require(saved["captured_at"] is not None, "captured_at missing")
    idea["position_plan"]["tp1"] = 999
    require(saved["position_plan"]["tp1"] == 5.55, "snapshot must be detached from live Planner idea")
    line = json.loads(path.read_text(encoding="utf-8").strip())
    require(line["planner_snapshot"]["idea_id"] == "planner:INJUSDT:123", "append-only snapshot missing idea_id")

    no_planner = recorder.record_open(
        symbol="BTCUSDT", market="SPOT", side="BUY",
        result={"code": "00000", "data": {"entry": 1, "qty": 1}},
        current={"price": 1, "atr": 0.1}, analysis={}, watch={}, planner_idea=None,
    )
    require(no_planner["planner_snapshot"] == {}, "missing Planner must remain safe")
    print("OK: smoke_spot_planner_snapshot")


if __name__ == "__main__":
    main()
