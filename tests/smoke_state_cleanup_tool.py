#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "state_cleanup_tool.py"


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    if not TOOL.exists():
        raise SystemExit("state_cleanup_tool.py missing")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = {
            "open": {
                "BTCUSDT::SPOT": {"symbol": "BTCUSDT", "market": "SPOT", "side": "BUY", "entry": 100.0},
                "ETHUSDT::FUT": {"symbol": "ETHUSDT", "market": "FUT", "side": "SHORT", "entry": 200.0},
            }
        }
        report = {
            "status": "ISSUES_FOUND",
            "summary": {"issue_types": ["OPEN_IN_STATE_ONLY"]},
            "issues": [
                {"type": "OPEN_IN_STATE_ONLY", "severity": "warning", "key": "SPOT:BTCUSDT:LONG:100:123", "message": "ghost"}
            ],
        }
        dashboard = {"positions": {"fut": {"ETHUSDT": {"symbol": "ETHUSDT", "side": "short", "entry": 200.0}}, "spot": {}}}

        write_json(root / "trades_state.json", state)
        write_json(root / "_runtime" / "state_cleanup_candidates.json", report)
        write_json(root / "dashboard.json", dashboard)

        cmd = [sys.executable, str(TOOL), "--root", str(root), "--report", "_runtime/state_cleanup_candidates.json", "--dashboard-json", "dashboard.json", "--dry-run", "--out", "_runtime/state_cleanup_plan.json"]
        subprocess.check_call(cmd)

        plan = json.loads((root / "_runtime" / "state_cleanup_plan.json").read_text(encoding="utf-8"))
        assert plan["summary"]["candidates_count"] == 1, plan
        assert plan["candidates"][0]["state_key"] == "BTCUSDT::SPOT", plan

        before = json.loads((root / "trades_state.json").read_text(encoding="utf-8"))
        assert "BTCUSDT::SPOT" in before["open"], "dry-run modified state"

        cmd = [sys.executable, str(TOOL), "--root", str(root), "--apply", "--plan", "_runtime/state_cleanup_plan.json"]
        subprocess.check_call(cmd)

        after = json.loads((root / "trades_state.json").read_text(encoding="utf-8"))
        assert "BTCUSDT::SPOT" not in after["open"], after
        assert "ETHUSDT::FUT" in after["open"], after
        assert list((root / "backups").glob("state_cleanup_*/*trades_state.json")), "backup missing"

    print("OK: smoke_state_cleanup_tool")


if __name__ == "__main__":
    main()
