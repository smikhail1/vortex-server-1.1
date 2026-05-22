"""VORTEX v1.8.19k — clean entry-quality verdict evaluator.

Standalone analytics module. It does not trade and does not mutate runtime trading state.
It reads trade diagnostics JSONL, filters impossible/legacy rows, classifies each closed
trade, and writes a compact report for later decision-making.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = "vortex.entry_quality_verdict.v1"
SCHEMA_VERSION = "1.8.19k"
DEFAULT_DIAGNOSTICS_PATH = Path("_runtime/trade_diagnostics.jsonl")
DEFAULT_REPORT_PATH = Path("_runtime/entry_quality_verdict_report.json")
DEFAULT_JSONL_PATH = Path("_runtime/entry_quality_verdicts.jsonl")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def _is_clean_diagnostic(row: Dict[str, Any], max_abs_final_pct: float = 10.0) -> bool:
    value = row.get("final_pnl_pct_est")
    if not isinstance(value, (int, float)):
        return False
    return abs(float(value)) <= max_abs_final_pct


def classify_diagnostic(row: Dict[str, Any]) -> Dict[str, Any]:
    """Classify one clean trade diagnostic into a practical engineering verdict."""
    setup = str(row.get("setup_type") or "UNKNOWN")
    reason = str(row.get("close_reason") or "UNKNOWN")
    symbol = str(row.get("symbol") or "")
    side = str(row.get("side") or "")

    mfe = _safe_float(row.get("mfe_pct"))
    mae = _safe_float(row.get("mae_pct"))
    final = _safe_float(row.get("final_pnl_pct_est"))
    hold_sec = _safe_int(row.get("hold_sec"))

    entry_quality = row.get("entry_quality") or {}
    fee_cover_hint = row.get("fee_cover_hint") or {}
    had_profit = bool(entry_quality.get("had_positive_excursion"))
    mfe_gt_abs_mae = bool(entry_quality.get("mfe_gt_abs_mae"))
    small_green = bool(fee_cover_hint.get("small_green_possible"))

    if hold_sec <= 60 and final < 0 and mfe < 0.05:
        verdict = "bad_entry_fast_loss"
        problem = "entry_failed_immediately"
        recommendation = "block_or_shadow_similar_fast_loss_conditions"
    elif had_profit and final < 0 and small_green:
        verdict = "good_entry_bad_exit_small_green_missed"
        problem = "profit_not_locked"
        recommendation = "enable_small_green_or_giveback_protection"
    elif mfe > 0.25 and final < 0:
        verdict = "good_entry_profit_not_locked"
        problem = "large_mfe_given_back"
        recommendation = "tighten_after_positive_mfe"
    elif mfe <= 0.05 and final < 0:
        verdict = "bad_or_late_entry_no_mfe"
        problem = "no_positive_excursion"
        recommendation = "improve_entry_argument_or_delay_filter"
    elif final > 0:
        verdict = "profitable_or_ok_exit"
        problem = "none"
        recommendation = "keep_collecting"
    else:
        verdict = "unclear"
        problem = "insufficient_signal"
        recommendation = "needs_more_context"

    grade = "C"
    if verdict == "profitable_or_ok_exit" and mfe_gt_abs_mae:
        grade = "A"
    elif verdict in {"good_entry_bad_exit_small_green_missed", "good_entry_profit_not_locked"}:
        grade = "B"
    elif verdict in {"bad_or_late_entry_no_mfe", "bad_entry_fast_loss"}:
        grade = "D"

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "side": side,
        "setup_type": setup,
        "close_reason": reason,
        "entry_verdict": verdict,
        "entry_grade": grade,
        "problem": problem,
        "recommendation": recommendation,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "final_pnl_pct_est": final,
        "hold_sec": hold_sec,
        "had_positive_excursion": had_profit,
        "mfe_gt_abs_mae": mfe_gt_abs_mae,
        "small_green_possible": small_green,
    }


def build_report(
    diagnostics_path: Path = DEFAULT_DIAGNOSTICS_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    jsonl_path: Path = DEFAULT_JSONL_PATH,
) -> Dict[str, Any]:
    rows = _load_jsonl(diagnostics_path)
    clean = [r for r in rows if _is_clean_diagnostic(r)]
    suspicious = len(rows) - len(clean)
    verdict_rows = [classify_diagnostic(r) for r in clean]

    verdicts = Counter(v["entry_verdict"] for v in verdict_rows)
    by_setup: Dict[str, Counter] = defaultdict(Counter)
    by_reason: Dict[str, Counter] = defaultdict(Counter)
    by_setup_pnl: Dict[str, float] = defaultdict(float)
    by_setup_count: Counter = Counter()

    for v in verdict_rows:
        setup = v["setup_type"]
        by_setup[setup][v["entry_verdict"]] += 1
        by_reason[v["close_reason"]][v["entry_verdict"]] += 1
        by_setup_pnl[setup] += _safe_float(v.get("final_pnl_pct_est"))
        by_setup_count[setup] += 1

    report = {
        "schema": "vortex.entry_quality_verdict_report.v1",
        "schema_version": SCHEMA_VERSION,
        "created_at": time.time(),
        "source": str(diagnostics_path),
        "rows_total": len(rows),
        "rows_clean": len(clean),
        "rows_suspicious": suspicious,
        "verdict_counts": dict(verdicts),
        "by_setup": {setup: dict(counter) for setup, counter in sorted(by_setup.items())},
        "by_reason": {reason: dict(counter) for reason, counter in sorted(by_reason.items())},
        "pnl_pct_by_setup_clean": {
            setup: {
                "count": by_setup_count[setup],
                "sum_final_pnl_pct_est": round(total, 8),
                "avg_final_pnl_pct_est": round(total / by_setup_count[setup], 8) if by_setup_count[setup] else 0.0,
            }
            for setup, total in sorted(by_setup_pnl.items())
        },
        "top_recommendations": _recommend(verdicts, by_setup),
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in verdict_rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    return report


def _recommend(verdicts: Counter, by_setup: Dict[str, Counter]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    missed = verdicts.get("good_entry_bad_exit_small_green_missed", 0) + verdicts.get("good_entry_profit_not_locked", 0)
    bad = verdicts.get("bad_or_late_entry_no_mfe", 0) + verdicts.get("bad_entry_fast_loss", 0)
    total = sum(verdicts.values())

    if total and missed / total >= 0.35:
        out.append({
            "priority": 1,
            "area": "position_management",
            "reason": "large share of entries had positive excursion but bad final exit",
            "action": "enable shadow profit giveback and small-green protection before changing entry filters",
        })
    if total and bad / total >= 0.20:
        out.append({
            "priority": 2,
            "area": "entry_quality",
            "reason": "meaningful share of entries had no MFE or fast loss",
            "action": "build Entry Argument Engine and stricter late-momentum filters",
        })

    for setup, counter in by_setup.items():
        setup_total = sum(counter.values())
        if setup_total <= 0:
            continue
        setup_missed = counter.get("good_entry_bad_exit_small_green_missed", 0) + counter.get("good_entry_profit_not_locked", 0)
        if setup_missed / setup_total >= 0.45:
            out.append({
                "priority": 3,
                "area": "setup_management",
                "setup_type": setup,
                "reason": "setup frequently produces good-entry/bad-exit verdicts",
                "action": "apply setup-aware trailing and profit protection",
            })
    return out


if __name__ == "__main__":
    result = build_report()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
