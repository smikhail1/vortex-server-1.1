#!/usr/bin/env python3
"""
VORTEX v1.8.21e - State Cleanup Tool
Read-only by default. Cleans only ghost OPEN positions from trades_state.json when explicitly applied.

Modes:
  --dry-run  : build a plan, do not modify anything
  --apply    : apply a previously generated plan after creating backup

Safety rules:
  - Only OPEN_IN_STATE_ONLY issues from runtime_position_reconciler are eligible.
  - DASHBOARD open positions are never removed.
  - DUPLICATE_OPEN_ROWS are ignored; trades.csv is never modified.
  - trades_state.json backup is mandatory before apply.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA = "vortex.state_cleanup_tool.v1"
SCHEMA_VERSION = "1.8.21e"


@dataclass
class Candidate:
    key: str
    market: str
    symbol: str
    side: str
    entry: float
    open_time_bucket: Optional[int]
    severity: str
    message: str
    state_key: Optional[str]
    reason: str = "OPEN_IN_STATE_ONLY"


def _load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _norm_market(v: Any) -> str:
    s = str(v or "").strip().upper()
    if s in {"FUTURES", "FUTURE"}:
        return "FUT"
    return s


def _norm_side(v: Any) -> str:
    s = str(v or "").strip().upper()
    if s == "BUY":
        return "LONG"
    if s == "SELL":
        return "SHORT"
    return s


def _entry_close(a: float, b: float, rel_tol: float = 0.0005, abs_tol: float = 1e-10) -> bool:
    if a == b:
        return True
    return abs(a - b) <= max(abs_tol, max(abs(a), abs(b)) * rel_tol)


def _iter_state_open_positions(state: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """Yield (state_key, position) from known state shapes."""
    open_obj = state.get("open") or state.get("open_positions") or {}
    if isinstance(open_obj, dict):
        for k, v in open_obj.items():
            if isinstance(v, dict):
                yield str(k), v
    elif isinstance(open_obj, list):
        for idx, v in enumerate(open_obj):
            if isinstance(v, dict):
                yield str(idx), v


def _dashboard_open_keys(dashboard: Dict[str, Any]) -> set[str]:
    out: set[str] = set()
    positions = dashboard.get("positions") or {}
    for market_key in ["fut", "spot", "FUT", "SPOT"]:
        market_positions = positions.get(market_key) or {}
        if not isinstance(market_positions, dict):
            continue
        market = "FUT" if market_key.lower() == "fut" else "SPOT"
        for sym, p in market_positions.items():
            if not isinstance(p, dict):
                continue
            symbol = str(p.get("symbol") or sym).upper()
            side = _norm_side(p.get("side") or p.get("direction") or p.get("position_side") or "LONG")
            entry = _safe_float(p.get("entry") or p.get("avg_price") or p.get("open_price"), 0.0)
            out.add(f"{market}:{symbol}:{side}:{entry:.12g}")
    return out


def _state_position_key(pos: Dict[str, Any], fallback_key: str = "") -> Tuple[str, str, str, float, str]:
    market = _norm_market(pos.get("market"))
    symbol = str(pos.get("symbol") or "").upper()
    side = _norm_side(pos.get("side") or pos.get("direction") or "")
    entry = _safe_float(pos.get("entry") or pos.get("avg_price") or pos.get("open_price"), 0.0)

    # Fallback from keys like SYMBOL::FUT or BTCUSDT::SPOT
    if (not symbol or not market) and "::" in fallback_key:
        parts = fallback_key.split("::")
        if len(parts) >= 2:
            symbol = symbol or parts[0].upper()
            market = market or _norm_market(parts[1])
    if not market:
        market = "FUT"
    if not side:
        side = "LONG" if market == "SPOT" else "UNKNOWN"
    compact = f"{market}:{symbol}:{side}:{entry:.12g}"
    return market, symbol, side, entry, compact


def _parse_reconciler_key(key: str) -> Dict[str, Any]:
    # Expected: MARKET:SYMBOL:SIDE:ENTRY:OPEN_BUCKET
    parts = str(key or "").split(":")
    return {
        "market": parts[0].upper() if len(parts) > 0 else "",
        "symbol": parts[1].upper() if len(parts) > 1 else "",
        "side": _norm_side(parts[2]) if len(parts) > 2 else "",
        "entry": _safe_float(parts[3], 0.0) if len(parts) > 3 else 0.0,
        "open_time_bucket": _safe_int(parts[4]) if len(parts) > 4 else None,
    }


def find_state_key_for_issue(issue: Dict[str, Any], state: Dict[str, Any]) -> Optional[str]:
    parsed = _parse_reconciler_key(str(issue.get("key") or ""))
    for state_key, pos in _iter_state_open_positions(state):
        market, symbol, side, entry, _ = _state_position_key(pos, state_key)
        if market != parsed["market"]:
            continue
        if symbol != parsed["symbol"]:
            continue
        if parsed["side"] and side != parsed["side"]:
            continue
        if not _entry_close(entry, float(parsed["entry"] or 0.0)):
            continue
        return state_key
    return None


def build_plan(root: Path, report_path: Path, dashboard_path: Optional[Path], out_path: Path) -> Dict[str, Any]:
    state_path = root / "trades_state.json"
    state = _load_json(state_path, {})
    report = _load_json(report_path, {})
    dashboard = _load_json(dashboard_path, {}) if dashboard_path else {}
    dash_keys = _dashboard_open_keys(dashboard)

    issues = report.get("issues") or []
    candidates: List[Candidate] = []
    skipped: List[Dict[str, Any]] = []

    for issue in issues:
        if issue.get("type") != "OPEN_IN_STATE_ONLY":
            continue
        parsed = _parse_reconciler_key(issue.get("key") or "")
        state_key = find_state_key_for_issue(issue, state)
        if not state_key:
            skipped.append({"issue_key": issue.get("key"), "reason": "state_key_not_found"})
            continue

        # Extra safety: if dashboard has same compact open, skip removal.
        compact = f"{parsed['market']}:{parsed['symbol']}:{parsed['side']}:{float(parsed['entry'] or 0.0):.12g}"
        if compact in dash_keys:
            skipped.append({"issue_key": issue.get("key"), "state_key": state_key, "reason": "still_visible_in_dashboard"})
            continue

        candidates.append(Candidate(
            key=str(issue.get("key")),
            market=parsed["market"],
            symbol=parsed["symbol"],
            side=parsed["side"],
            entry=float(parsed["entry"] or 0.0),
            open_time_bucket=parsed["open_time_bucket"],
            severity=str(issue.get("severity") or "warning"),
            message=str(issue.get("message") or ""),
            state_key=state_key,
        ))

    plan = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "mode": "dry-run",
        "created_at": time.time(),
        "root": str(root),
        "sources": {
            "trades_state": str(state_path),
            "reconciler_report": str(report_path),
            "dashboard_json": str(dashboard_path) if dashboard_path else "",
        },
        "summary": {
            "report_status": report.get("status"),
            "report_summary": report.get("summary"),
            "candidates_count": len(candidates),
            "skipped_count": len(skipped),
        },
        "candidates": [asdict(c) for c in candidates],
        "skipped": skipped,
        "safety": {
            "read_only_plan": True,
            "trades_csv_modified": False,
            "dashboard_modified": False,
            "requires_apply_flag": True,
            "backup_required": True,
        },
    }
    _write_json(out_path, plan)
    return plan


def apply_plan(root: Path, plan_path: Path, allow_empty: bool = False) -> Dict[str, Any]:
    state_path = root / "trades_state.json"
    plan = _load_json(plan_path, {})
    if plan.get("schema") != SCHEMA:
        raise SystemExit(f"Invalid plan schema: {plan.get('schema')}")
    candidates = plan.get("candidates") or []
    if not candidates and not allow_empty:
        raise SystemExit("No cleanup candidates in plan. Use --allow-empty to apply empty plan.")

    state = _load_json(state_path, {})
    open_obj = state.get("open") or state.get("open_positions")
    if not isinstance(open_obj, dict):
        raise SystemExit("Unsupported trades_state open structure: expected dict at 'open' or 'open_positions'.")

    backup_dir = root / "backups" / f"state_cleanup_{SCHEMA_VERSION}_{time.strftime('%Y-%m-%d_%H-%M-%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / "trades_state.json"
    shutil.copy2(state_path, backup_path)

    removed: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    for c in candidates:
        state_key = c.get("state_key")
        if state_key in open_obj:
            removed.append({"state_key": state_key, "issue_key": c.get("key"), "position": open_obj.get(state_key)})
            del open_obj[state_key]
        else:
            missing.append({"state_key": state_key, "issue_key": c.get("key")})

    if "open" in state and isinstance(state.get("open"), dict):
        state["open"] = open_obj
    elif "open_positions" in state and isinstance(state.get("open_positions"), dict):
        state["open_positions"] = open_obj

    state.setdefault("meta", {})
    if isinstance(state["meta"], dict):
        state["meta"]["last_state_cleanup"] = {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "ts": time.time(),
            "plan": str(plan_path),
            "backup": str(backup_path),
            "removed_count": len(removed),
            "missing_count": len(missing),
        }

    _write_json(state_path, state)
    result = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "mode": "apply",
        "applied_at": time.time(),
        "backup": str(backup_path),
        "removed_count": len(removed),
        "missing_count": len(missing),
        "removed": removed,
        "missing": missing,
        "trades_state": str(state_path),
    }
    out_path = root / "_runtime" / "state_cleanup_apply_result.json"
    _write_json(out_path, result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="VORTEX read-only/dry-run state cleanup planner and guarded applier")
    ap.add_argument("--root", default=".", help="Project root, default: current directory")
    ap.add_argument("--report", default="_runtime/state_cleanup_candidates.json", help="Runtime reconciler report JSON")
    ap.add_argument("--dashboard-json", default="", help="Dashboard JSON snapshot used as safety reference")
    ap.add_argument("--out", default="_runtime/state_cleanup_plan.json", help="Dry-run plan output JSON")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Build cleanup plan only")
    mode.add_argument("--apply", action="store_true", help="Apply cleanup plan to trades_state.json")
    ap.add_argument("--plan", default="", help="Plan file to apply. Required with --apply")
    ap.add_argument("--allow-empty", action="store_true", help="Allow applying an empty plan")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if args.dry_run:
        plan = build_plan(
            root=root,
            report_path=(root / args.report).resolve() if not Path(args.report).is_absolute() else Path(args.report),
            dashboard_path=((root / args.dashboard_json).resolve() if args.dashboard_json and not Path(args.dashboard_json).is_absolute() else Path(args.dashboard_json)) if args.dashboard_json else None,
            out_path=(root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out),
        )
        print(json.dumps({"status": "DRY_RUN_OK", "summary": plan.get("summary"), "out": args.out}, ensure_ascii=False, indent=2))
        return 0

    if args.apply:
        if not args.plan:
            raise SystemExit("--plan is required with --apply")
        result = apply_plan(root=root, plan_path=(root / args.plan).resolve() if not Path(args.plan).is_absolute() else Path(args.plan), allow_empty=args.allow_empty)
        print(json.dumps({"status": "APPLY_OK", "removed_count": result.get("removed_count"), "backup": result.get("backup")}, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
