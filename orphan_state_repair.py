import argparse
import csv
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


SCHEMA = "vortex.orphan_state_repair.v1"
SCHEMA_VERSION = "1.8.21f-b-r2"


CLOSE_REASONS = {
    "SL", "BU", "TP", "TP0", "TP1", "TP2",
    "TIMEOUT", "FADE", "STALL", "LIQ",
    "WEAK_PROGRESS", "WEAK_PROGRESS_STALE",
    "MANUAL", "CLOSE",
}


def _safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _parse_ts_epoch(ts_text: str) -> float:
    ts_text = _safe_str(ts_text).strip()
    if not ts_text:
        return 0.0
    try:
        dt = datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return float(dt.timestamp())
    except Exception:
        return 0.0


def _read_dashboard_fut_symbols(path: Path) -> set:
    data = _load_json(path)
    fut = data.get("positions", {}).get("fut", {}) or {}
    if not isinstance(fut, dict):
        return set()
    return {str(k).upper() for k in fut.keys()}


def _trade_rows_for_symbol_after_open(trades_path: Path, symbol: str, open_time: float) -> Tuple[List[Dict[str, Any]], bool]:
    rows: List[Dict[str, Any]] = []
    has_close = False

    if not trades_path.exists():
        return rows, False

    symbol = symbol.upper()

    with trades_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        for parts in reader:
            if len(parts) < 10:
                continue

            ts_text = parts[0].strip()
            row_symbol = parts[1].strip().upper()
            reason = parts[9].strip().upper()

            if row_symbol != symbol:
                continue

            ts_epoch = _parse_ts_epoch(ts_text)
            if ts_epoch <= 0:
                continue

            if ts_epoch + 2.0 < open_time:
                continue

            item = {
                "ts": ts_text,
                "ts_epoch": ts_epoch,
                "symbol": row_symbol,
                "side": parts[2].strip() if len(parts) > 2 else "",
                "market": parts[3].strip() if len(parts) > 3 else "",
                "entry": parts[4].strip() if len(parts) > 4 else "",
                "exit_price": parts[6].strip() if len(parts) > 6 else "",
                "pnl": parts[7].strip() if len(parts) > 7 else "",
                "pnl_net": parts[8].strip() if len(parts) > 8 else "",
                "reason": reason,
                "raw": ",".join(parts),
            }
            rows.append(item)

            if reason in CLOSE_REASONS and reason != "OPEN":
                has_close = True

    return rows, has_close


def _audit_has_close_after_open(audit_path: Path, symbol: str, open_time: float) -> bool:
    if not audit_path.exists():
        return False

    symbol = symbol.upper()

    for line in audit_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if symbol not in line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue

        if str(item.get("symbol", "")).upper() != symbol:
            continue

        ts = _safe_float(item.get("ts"), 0.0)
        was_close = bool(item.get("was_close_result"))
        event_only = bool(item.get("event_only"))

        if was_close and not event_only and ts + 2.0 >= open_time:
            return True

    return False


def build_plan(
    state_path: Path,
    dashboard_path: Path,
    trades_path: Path,
    audit_path: Path,
) -> Dict[str, Any]:
    state = _load_json(state_path)
    open_map = state.get("open") or {}
    if not isinstance(open_map, dict):
        open_map = {}

    dashboard_fut_symbols = _read_dashboard_fut_symbols(dashboard_path)

    candidates = []
    skipped = []

    for raw_key, raw_pos in open_map.items():
        if not isinstance(raw_pos, dict):
            continue

        key = str(raw_key)
        market = _safe_str(raw_pos.get("market"), "").upper()
        symbol = _safe_str(raw_pos.get("symbol"), "").upper()

        if not symbol:
            symbol = key.split("::", 1)[0].upper()

        if not market and "::" in key:
            market = key.split("::", 1)[1].upper()

        if market != "FUT" and not key.upper().endswith("::FUT"):
            continue

        open_time = _safe_float(raw_pos.get("open_time"), 0.0)

        if symbol in dashboard_fut_symbols:
            skipped.append({
                "state_key": key,
                "symbol": symbol,
                "reason": "symbol_is_live_in_dashboard",
            })
            continue

        trade_rows_after_open, has_trade_close_after_open = _trade_rows_for_symbol_after_open(
            trades_path=trades_path,
            symbol=symbol,
            open_time=open_time,
        )
        has_audit_close_after_open = _audit_has_close_after_open(
            audit_path=audit_path,
            symbol=symbol,
            open_time=open_time,
        )

        if has_trade_close_after_open or has_audit_close_after_open:
            skipped.append({
                "state_key": key,
                "symbol": symbol,
                "reason": "close_exists_after_open",
                "has_trade_close_after_open": has_trade_close_after_open,
                "has_audit_close_after_open": has_audit_close_after_open,
                "trade_rows_after_open_tail": trade_rows_after_open[-10:],
            })
            continue

        candidates.append({
            "state_key": key,
            "symbol": symbol,
            "market": "FUT",
            "side": _safe_str(raw_pos.get("side"), "").upper(),
            "entry": _safe_float(raw_pos.get("entry"), 0.0),
            "open_time": open_time,
            "pnl_net": _safe_float(raw_pos.get("pnl_net"), 0.0),
            "repair_reason": "ORPHAN_OPEN_WITHOUT_CLOSE",
            "has_trade_close_after_open": has_trade_close_after_open,
            "has_audit_close_after_open": has_audit_close_after_open,
            "trade_rows_after_open_tail": trade_rows_after_open[-10:],
            "state_position": raw_pos,
        })

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "status": "PLAN",
        "summary": {
            "state_open_count": len(open_map),
            "dashboard_fut_count": len(dashboard_fut_symbols),
            "candidates_count": len(candidates),
            "skipped_count": len(skipped),
        },
        "candidates": candidates,
        "skipped": skipped,
        "sources": {
            "state_path": str(state_path),
            "dashboard_path": str(dashboard_path),
            "trades_path": str(trades_path),
            "audit_path": str(audit_path),
        },
    }


def apply_plan(plan_path: Path, state_path: Path, audit_out: Path, backup_dir: Path) -> Dict[str, Any]:
    plan = _load_json(plan_path)
    candidates = plan.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []

    state = _load_json(state_path)
    open_map = state.get("open") or {}
    if not isinstance(open_map, dict):
        open_map = {}

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"trades_state_before_orphan_repair_{int(time.time())}.json"
    shutil.copy2(state_path, backup_path)

    audit_out.parent.mkdir(parents=True, exist_ok=True)

    removed = []

    with audit_out.open("a", encoding="utf-8") as f:
        for item in candidates:
            key = _safe_str(item.get("state_key"), "")
            if not key or key not in open_map:
                continue

            removed_pos = open_map.pop(key)

            record = {
                "schema": SCHEMA,
                "schema_version": SCHEMA_VERSION,
                "ts": time.time(),
                "event": "STATE_ORPHAN_REPAIR",
                "state_key": key,
                "symbol": item.get("symbol"),
                "market": item.get("market"),
                "side": item.get("side"),
                "entry": item.get("entry"),
                "open_time": item.get("open_time"),
                "pnl_net_last_seen": item.get("pnl_net"),
                "repair_reason": item.get("repair_reason"),
                "action": "removed_from_trades_state_open",
                "synthetic_trade_close_written": False,
                "trade_rows_after_open_tail": item.get("trade_rows_after_open_tail", []),
                "removed_position": removed_pos,
            }

            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            removed.append(key)

    state["open"] = open_map
    _save_json_atomic(state_path, state)

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "status": "APPLY_OK",
        "removed_count": len(removed),
        "removed": removed,
        "backup": str(backup_path),
        "audit_out": str(audit_out),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard-json", default="/tmp/dashboard_orphan_repair.json")
    ap.add_argument("--state", default="trades_state.json")
    ap.add_argument("--trades", default="trades.csv")
    ap.add_argument("--close-audit", default="_runtime/close_result_audit.jsonl")
    ap.add_argument("--audit-out", default="_runtime/orphan_state_repair.jsonl")
    ap.add_argument("--out", default="_runtime/orphan_state_repair_plan.json")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--plan", default="")
    args = ap.parse_args()

    if args.apply:
        result = apply_plan(
            plan_path=Path(args.plan or args.out),
            state_path=Path(args.state),
            audit_out=Path(args.audit_out),
            backup_dir=Path("backups") / f"orphan_state_repair_{SCHEMA_VERSION}_{time.strftime('%Y-%m-%d_%H-%M-%S')}",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return

    plan = build_plan(
        state_path=Path(args.state),
        dashboard_path=Path(args.dashboard_json),
        trades_path=Path(args.trades),
        audit_path=Path(args.close_audit),
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps({
        "status": "PLAN_OK",
        "summary": plan.get("summary"),
        "out": str(out_path),
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
