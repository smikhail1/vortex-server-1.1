import json
import subprocess
import tempfile
from pathlib import Path


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=True)


def test_orphan_repair_plan_and_apply():
    root = Path(tempfile.mkdtemp())

    state = root / "trades_state.json"
    dashboard = root / "dashboard.json"
    trades = root / "trades.csv"
    close_audit = root / "close_audit.jsonl"
    audit_out = root / "orphan_audit.jsonl"
    plan = root / "plan.json"

    state.write_text(json.dumps({
        "open": {
            "VIRTUALUSDT::FUT": {
                "symbol": "VIRTUALUSDT",
                "market": "FUT",
                "side": "LONG",
                "entry": 0.76950768,
                "open_time": 1779606008.0,
                "pnl_net": -0.05,
            },
            "BTCUSDT::SPOT": {
                "symbol": "BTCUSDT",
                "market": "SPOT",
                "side": "LONG",
            },
        }
    }), encoding="utf-8")

    dashboard.write_text(json.dumps({"positions": {"fut": {}, "spot": {}}}), encoding="utf-8")
    trades.write_text("2026-05-24 07:00:08,VIRTUALUSDT,LONG,FUT,0.76950768,0.77727143,0.0,0.0,0.0,OPEN,0,momentum_long,args\n", encoding="utf-8")
    close_audit.write_text("", encoding="utf-8")

    here = Path(__file__).resolve().parents[1]
    script = here / "orphan_state_repair.py"

    run([
        "python3", str(script),
        "--dashboard-json", str(dashboard),
        "--state", str(state),
        "--trades", str(trades),
        "--close-audit", str(close_audit),
        "--audit-out", str(audit_out),
        "--out", str(plan),
    ], cwd=here)

    p = json.loads(plan.read_text(encoding="utf-8"))
    assert p["summary"]["candidates_count"] == 1
    assert p["candidates"][0]["symbol"] == "VIRTUALUSDT"

    run([
        "python3", str(script),
        "--apply",
        "--plan", str(plan),
        "--state", str(state),
        "--audit-out", str(audit_out),
    ], cwd=here)

    s = json.loads(state.read_text(encoding="utf-8"))
    assert "VIRTUALUSDT::FUT" not in s["open"]
    assert "BTCUSDT::SPOT" in s["open"]
    assert "STATE_ORPHAN_REPAIR" in audit_out.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_orphan_repair_plan_and_apply()
    print("OK: smoke_orphan_state_repair")
