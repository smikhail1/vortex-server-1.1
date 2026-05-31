#!/usr/bin/env python3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    futures, spot = source.split("# 4) Confirm spot: only confirmed WATCH candidates open Entry 1.", 1)
    require("spot_args_text" not in futures, "Spot diagnostics leaked into futures-open path")
    require("spot_args_text = safe_str(analysis.get(\"args_text\"))" in spot, "Spot summary builder missing")
    require('args_text=spot_args_text' in spot, "Spot trade log must use Planner summary")
    require('analysis={**analysis, "args_text": spot_args_text}' in spot, "Spot snapshot must capture Planner summary")
    print("OK: smoke_spot_snapshot_scope")


if __name__ == "__main__":
    main()
