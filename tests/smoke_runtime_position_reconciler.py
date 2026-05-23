from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "runtime_position_reconciler.py"


def write_csv(path: Path, rows):
    fields = ["ts", "symbol", "side", "market", "entry", "tp", "exit_price", "pnl", "pnl_net", "reason", "hold_sec", "setup_type", "args_text"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run_reconciler(tmp: Path):
    out = tmp / "report.json"
    cmd = [
        sys.executable, str(SCRIPT),
        "--root", str(tmp),
        "--dashboard-json", str(tmp / "dashboard.json"),
        "--out", str(out),
    ]
    subprocess.check_call(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL)
    return json.loads(out.read_text(encoding="utf-8"))


def test_matching_and_legacy_filter():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "_runtime").mkdir()
        write_csv(tmp / "trades.csv", [
            {
                "ts": "2026-05-23 10:00:00", "symbol": "OLDUSDT", "side": "LONG", "market": "FUT",
                "entry": "1.0", "tp": "1.1", "exit_price": "0.9", "pnl": "-1", "pnl_net": "-1.1",
                "reason": "SL", "hold_sec": "100", "setup_type": "x", "args_text": "legacy",
            },
            {
                "ts": "2026-05-23 18:08:24", "symbol": "WLDUSDT", "side": "LONG", "market": "FUT",
                "entry": "0.29671864", "tp": "0.299", "exit_price": "0.2968812", "pnl": "0.00657694", "pnl_net": "-0.00783277",
                "reason": "BU", "hold_sec": "244", "setup_type": "trend_follow_v1.7", "args_text": "new",
            },
        ])
        audit = {
            "ts": 1779559704.85, "symbol": "WLDUSDT", "side": "LONG", "market": "FUT",
            "entry": 0.29671864, "exit_price": 0.2968812, "pnl": 0.00657694, "pnl_net": -0.00783277,
            "reason": "BU", "hold_sec": 244, "setup_type": "trend_follow_v1.7", "was_close_result": True,
        }
        (tmp / "_runtime" / "close_result_audit.jsonl").write_text(json.dumps(audit) + "\n", encoding="utf-8")
        (tmp / "trades_state.json").write_text(json.dumps({"open": {}}), encoding="utf-8")
        (tmp / "dashboard.json").write_text(json.dumps({"positions": {"fut": {}, "spot": {}}}), encoding="utf-8")
        rep = run_reconciler(tmp)
        assert rep["summary"]["legacy_close_rows_before_audit"] == 1, rep
        assert "TRADE_CLOSE_WITHOUT_AUDIT" not in rep["summary"]["issue_types"], rep
        assert "AUDIT_WITHOUT_TRADE_ROW" not in rep["summary"]["issue_types"], rep


def test_state_dashboard_mismatch():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "_runtime").mkdir()
        write_csv(tmp / "trades.csv", [])
        (tmp / "_runtime" / "close_result_audit.jsonl").write_text("", encoding="utf-8")
        state = {"open": {"BTCUSDT::FUT": {"symbol": "BTCUSDT", "market": "FUT", "side": "LONG", "entry": 100.0, "open_time": 1000}}}
        (tmp / "trades_state.json").write_text(json.dumps(state), encoding="utf-8")
        (tmp / "dashboard.json").write_text(json.dumps({"positions": {"fut": {}, "spot": {}}}), encoding="utf-8")
        rep = run_reconciler(tmp)
        assert "OPEN_IN_STATE_ONLY" in rep["summary"]["issue_types"], rep


def main():
    test_matching_and_legacy_filter()
    test_state_dashboard_mismatch()
    print("OK: smoke_runtime_position_reconciler")


if __name__ == "__main__":
    main()
