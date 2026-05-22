"""VORTEX v1.8.19k — clean analytics session collector.

Creates a period folder with raw copies plus clean entry-quality verdict report.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict

from entry_quality_evaluator import build_report

SCHEMA_VERSION = "1.8.19k"


def collect_session(session_name: str | None = None) -> Dict[str, Any]:
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    session_id = session_name or f"session_{stamp}_v1_8_19k"
    out_dir = Path("_analysis/sessions") / session_id
    out_dir.mkdir(parents=True, exist_ok=True)

    files = [
        "trades.csv",
        "trades_state.json",
        "_runtime/trade_diagnostics.jsonl",
        "_runtime/trade_snapshots.jsonl",
        "_runtime/trade_outcomes.jsonl",
        "_runtime/entry_argument_snapshots.jsonl",
        "_runtime/post_close_cooldown_state.json",
        "_runtime/position_management_shadow.jsonl",
        "_runtime/position_management_shadow_state.json",
        "_runtime/research_report_latest.json",
        "_runtime/entry_quality_matrix.json",
        "_runtime/outcome_summary.json",
        "_runtime/shadow_policy_simulation.json",
        "_runtime/shadow_variant_results.json",
    ]

    copied = []
    missing = []
    for name in files:
        src = Path(name)
        if src.exists():
            dst = out_dir / name.replace("/", "__")
            shutil.copy2(src, dst)
            copied.append(name)
        else:
            missing.append(name)

    verdict_report_path = out_dir / "entry_quality_verdict_report.json"
    verdict_jsonl_path = out_dir / "entry_quality_verdicts.jsonl"
    report = build_report(report_path=verdict_report_path, jsonl_path=verdict_jsonl_path)

    manifest = {
        "schema": "vortex.analytics_session.v1",
        "schema_version": SCHEMA_VERSION,
        "created_at": time.time(),
        "session_id": session_id,
        "out_dir": str(out_dir),
        "copied": copied,
        "missing": missing,
        "entry_quality_rows_clean": report.get("rows_clean"),
        "entry_quality_rows_suspicious": report.get("rows_suspicious"),
        "entry_quality_verdict_counts": report.get("verdict_counts"),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(collect_session(), ensure_ascii=False, indent=2, sort_keys=True))
