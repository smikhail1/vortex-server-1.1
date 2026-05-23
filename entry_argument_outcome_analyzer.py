"""
VORTEX v1.8.20c Entry Argument Outcome Analyzer.

Purpose:
- correlate EntryArgumentEngine shadow grades (EA:A/B/C/D) with real trade outcomes;
- quantify whether BLOCK_SHADOW / SHADOW_ONLY / ALLOW_SHADOW are predictive;
- produce JSON/JSONL reports for later tuning before enabling real entry blocking.

Inputs:
- trades.csv
- _runtime/entry_argument_decisions.jsonl

Outputs:
- _runtime/entry_argument_outcomes.jsonl
- _runtime/entry_argument_outcome_report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA = "vortex.entry_argument_outcome_report.v1"
SCHEMA_VERSION = "1.8.20c"
EA_RE = re.compile(r"EA:(?P<grade>[A-D])/(?P<confidence>\d+)\s+(?P<decision>[A-Z_]+)")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return int(default)
        return int(float(v))
    except Exception:
        return int(default)


def _safe_str(v: Any, default: str = "") -> str:
    try:
        if v is None:
            return default
        return str(v)
    except Exception:
        return default


def _parse_trade_ts(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _dt_to_epoch(dt: Optional[datetime]) -> float:
    if dt is None:
        return 0.0
    try:
        return float(dt.timestamp())
    except Exception:
        return 0.0


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except Exception:
            continue
    return rows


def _read_trades(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            row = dict(row)
            dt = _parse_trade_ts(_safe_str(row.get("ts")))
            row["_row_index"] = i
            row["_dt"] = dt
            row["_epoch"] = _dt_to_epoch(dt)
            row["_pnl_net"] = _safe_float(row.get("pnl_net"), 0.0)
            row["_pnl"] = _safe_float(row.get("pnl"), 0.0)
            row["_hold_sec"] = _safe_int(row.get("hold_sec"), 0)
            row["_symbol"] = _safe_str(row.get("symbol")).upper()
            row["_side"] = _safe_str(row.get("side")).upper()
            row["_market"] = _safe_str(row.get("market")).upper()
            row["_reason"] = _safe_str(row.get("reason")).upper()
            row["_setup_type"] = _safe_str(row.get("setup_type"))
            row["_args_text"] = _safe_str(row.get("args_text"))
            rows.append(row)
    return rows


def _extract_ea(args_text: str) -> Optional[Dict[str, Any]]:
    m = EA_RE.search(args_text or "")
    if not m:
        return None
    return {
        "entry_grade": m.group("grade"),
        "confidence": int(m.group("confidence")),
        "decision": m.group("decision"),
        "summary": m.group(0),
    }


def _nearest_decision(
    decisions: List[Dict[str, Any]],
    symbol: str,
    side: str,
    setup_type: str,
    summary: str,
    open_epoch: float,
) -> Optional[Dict[str, Any]]:
    candidates = []
    for d in decisions:
        if _safe_str(d.get("symbol")).upper() != symbol:
            continue
        if _safe_str(d.get("side")).upper() != side:
            continue
        if setup_type and _safe_str(d.get("setup_type")) != setup_type:
            continue
        if summary and _safe_str(d.get("summary")) != summary:
            continue
        ts = _safe_float(d.get("ts"), 0.0)
        distance = abs(open_epoch - ts) if open_epoch and ts else 10**12
        candidates.append((distance, d))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    # Prefer a decision close to the open event, but still allow fallback by summary.
    return candidates[0][1]


def _find_close_for_open(open_row: Dict[str, Any], rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    symbol = open_row["_symbol"]
    market = open_row["_market"]
    side = open_row["_side"]
    start_idx = int(open_row.get("_row_index", -1))

    for row in rows:
        if int(row.get("_row_index", -1)) <= start_idx:
            continue
        if row["_symbol"] != symbol:
            continue
        if row["_market"] != market:
            continue
        # Futures close rows keep same side in this project.
        if row["_side"] != side:
            continue
        if row["_reason"] and row["_reason"] != "OPEN":
            return row
        # If a new OPEN for same symbol appears before close, stop to avoid wrong pairing.
        if row["_reason"] == "OPEN":
            return None
    return None


def _outcome_class(close_row: Optional[Dict[str, Any]]) -> str:
    if close_row is None:
        return "OPEN_OR_UNKNOWN"
    reason = close_row["_reason"]
    pnl = close_row["_pnl_net"]
    if pnl > 0:
        return "WIN"
    if pnl < 0:
        return "LOSS"
    if reason in {"TP", "TP1", "TP2", "STALL"}:
        return "WIN_OR_FLAT"
    return "FLAT"


def _bucket_summary(items: Iterable[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        buckets[_safe_str(item.get(key), "UNKNOWN")].append(item)

    out: Dict[str, Dict[str, Any]] = {}
    for name, arr in sorted(buckets.items()):
        closed = [x for x in arr if x.get("close_reason")]
        pnl = sum(_safe_float(x.get("pnl_net"), 0.0) for x in closed)
        wins = [x for x in closed if _safe_float(x.get("pnl_net"), 0.0) > 0]
        losses = [x for x in closed if _safe_float(x.get("pnl_net"), 0.0) < 0]
        reasons = Counter(_safe_str(x.get("close_reason"), "OPEN") for x in arr)
        out[name] = {
            "count": len(arr),
            "closed": len(closed),
            "open_or_unknown": len(arr) - len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
            "pnl_net": round(pnl, 8),
            "avg_pnl_net": round(pnl / len(closed), 8) if closed else 0.0,
            "avg_hold_sec": round(sum(_safe_float(x.get("hold_sec"), 0.0) for x in closed) / len(closed), 2) if closed else 0.0,
            "reasons": dict(reasons),
        }
    return out


def analyze(
    trades_path: Path = Path("trades.csv"),
    decisions_path: Path = Path("_runtime/entry_argument_decisions.jsonl"),
    outcomes_path: Path = Path("_runtime/entry_argument_outcomes.jsonl"),
    report_path: Path = Path("_runtime/entry_argument_outcome_report.json"),
    since_epoch: float = 0.0,
) -> Dict[str, Any]:
    trades = _read_trades(trades_path)
    decisions = _read_jsonl(decisions_path)

    outcomes: List[Dict[str, Any]] = []
    for row in trades:
        if row["_reason"] != "OPEN":
            continue
        if row["_market"] != "FUT":
            continue
        if since_epoch and row["_epoch"] and row["_epoch"] < since_epoch:
            continue
        ea = _extract_ea(row["_args_text"])
        if not ea:
            continue

        close_row = _find_close_for_open(row, trades)
        decision = _nearest_decision(
            decisions=decisions,
            symbol=row["_symbol"],
            side=row["_side"],
            setup_type=row["_setup_type"],
            summary=ea.get("summary", ""),
            open_epoch=row["_epoch"],
        )

        outcome = {
            "schema": "vortex.entry_argument_outcome.v1",
            "schema_version": SCHEMA_VERSION,
            "symbol": row["_symbol"],
            "side": row["_side"],
            "market": row["_market"],
            "setup_type": row["_setup_type"],
            "open_ts": row.get("ts"),
            "open_epoch": row["_epoch"],
            "entry": _safe_float(row.get("entry"), 0.0),
            "tp": _safe_float(row.get("tp"), 0.0),
            "ea_summary": ea.get("summary"),
            "entry_grade": ea.get("entry_grade"),
            "confidence": ea.get("confidence"),
            "decision": ea.get("decision"),
            "close_ts": close_row.get("ts") if close_row else "",
            "close_reason": close_row["_reason"] if close_row else "",
            "exit_price": _safe_float(close_row.get("exit_price"), 0.0) if close_row else 0.0,
            "pnl": close_row["_pnl"] if close_row else 0.0,
            "pnl_net": close_row["_pnl_net"] if close_row else 0.0,
            "hold_sec": close_row["_hold_sec"] if close_row else 0,
            "outcome_class": _outcome_class(close_row),
            "args_text": row["_args_text"],
            "entry_argument": decision or {},
        }
        outcomes.append(outcome)

    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    with outcomes_path.open("w", encoding="utf-8") as f:
        for item in outcomes:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    closed = [x for x in outcomes if x.get("close_reason")]
    total_pnl = sum(_safe_float(x.get("pnl_net"), 0.0) for x in closed)

    report = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.time(),
        "inputs": {
            "trades_path": str(trades_path),
            "decisions_path": str(decisions_path),
            "since_epoch": since_epoch,
        },
        "outputs": {
            "outcomes_path": str(outcomes_path),
            "report_path": str(report_path),
        },
        "summary": {
            "total_ea_trades": len(outcomes),
            "closed_ea_trades": len(closed),
            "open_or_unknown": len(outcomes) - len(closed),
            "total_pnl_net": round(total_pnl, 8),
            "avg_pnl_net": round(total_pnl / len(closed), 8) if closed else 0.0,
            "wins": len([x for x in closed if _safe_float(x.get("pnl_net"), 0.0) > 0]),
            "losses": len([x for x in closed if _safe_float(x.get("pnl_net"), 0.0) < 0]),
        },
        "by_grade": _bucket_summary(outcomes, "entry_grade"),
        "by_decision": _bucket_summary(outcomes, "decision"),
        "by_setup": _bucket_summary(outcomes, "setup_type"),
        "by_close_reason": _bucket_summary(outcomes, "close_reason"),
        "block_shadow_closed": [x for x in outcomes if x.get("decision") == "BLOCK_SHADOW" and x.get("close_reason")],
        "worst_closed": sorted(closed, key=lambda x: _safe_float(x.get("pnl_net"), 0.0))[:20],
        "best_closed": sorted(closed, key=lambda x: _safe_float(x.get("pnl_net"), 0.0), reverse=True)[:20],
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze EntryArgumentEngine outcomes")
    parser.add_argument("--trades", default="trades.csv")
    parser.add_argument("--decisions", default="_runtime/entry_argument_decisions.jsonl")
    parser.add_argument("--outcomes", default="_runtime/entry_argument_outcomes.jsonl")
    parser.add_argument("--report", default="_runtime/entry_argument_outcome_report.json")
    parser.add_argument("--since-epoch", type=float, default=0.0)
    args = parser.parse_args(argv)

    report = analyze(
        trades_path=Path(args.trades),
        decisions_path=Path(args.decisions),
        outcomes_path=Path(args.outcomes),
        report_path=Path(args.report),
        since_epoch=float(args.since_epoch or 0.0),
    )

    print("===== ENTRY ARGUMENT OUTCOME REPORT =====")
    print("schema_version:", report.get("schema_version"))
    print("summary:", json.dumps(report.get("summary", {}), ensure_ascii=False))
    print("by_grade:", json.dumps(report.get("by_grade", {}), ensure_ascii=False))
    print("by_decision:", json.dumps(report.get("by_decision", {}), ensure_ascii=False))
    print("saved_report:", report.get("outputs", {}).get("report_path"))
    print("saved_outcomes:", report.get("outputs", {}).get("outcomes_path"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
