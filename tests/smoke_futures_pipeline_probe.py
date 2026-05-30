#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools" / "futures_entry_pipeline_probe.py"


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def main() -> None:
    require(PROBE.exists(), "tools/futures_entry_pipeline_probe.py missing")
    source = PROBE.read_text(encoding="utf-8")

    require("PAPER_ONLY" in source, "PAPER-only refusal missing")
    require('os.environ.get("MODE"' in source, "MODE check missing")
    require('os.environ.get("DEFAULT_FUT_MODE"' in source, "DEFAULT_FUT_MODE check missing")
    require('api_json("/api/health")' in source, "/api/health PAPER check missing")
    require("ensure_health_paper" in source, "/api/health mode validator missing")
    require("ensure_no_live_futures" in source, "open futures refusal missing")
    require("--dry-run" in source, "--dry-run missing")
    require("--paper-open" in source, "--paper-open missing")
    require("--rollback" in source, "--rollback missing")
    require("TEST_PROBE" in source, "TEST_PROBE marker missing")
    require("FUTURES_PIPELINE_PROBE" in source, "FUTURES_PIPELINE_PROBE marker missing")
    require("make_backup" in source and "backups" in source, "backup path missing")
    require("TemporaryDirectory" in source, "isolated filesystem sandbox missing")
    require("decision.evaluate" in source, "DecisionEngine path missing")
    require("evaluate_entry_safety" in source, "entry safety policy path missing")
    require("router.open_futures_position" in source, "router PAPER open path missing")
    require("router.close_futures_position" in source, "router rollback close path missing")
    require("state.sync_router_snapshot" in source, "dashboard/state visibility sync missing")
    require("PositionStateEngine" in source, "position state engine verification missing")
    require("logger.log_trade" in source, "sandbox trades.csv marker write missing")
    require("open_spot_position" not in source, "probe must not open spot")

    forbidden_imports = [
        "bitget",
        "live_exchange",
        "real_execution",
        "exchange_client",
    ]
    lower = source.lower()
    for text in forbidden_imports:
        require(f"import {text}" not in lower and f"from {text}" not in lower, f"live exchange import forbidden: {text}")

    forbidden_mutations = [
        "main.py",
        "watch_engine.py",
        "strategy.py",
    ]
    for text in forbidden_mutations:
        require(text not in source, f"probe references forbidden trading source: {text}")

    print("OK: smoke_futures_pipeline_probe")


if __name__ == "__main__":
    main()
