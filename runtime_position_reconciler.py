from __future__ import annotations

import argparse
import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA = "vortex.runtime_position_reconciler.report.v1"
SCHEMA_VERSION = "1.8.21d-r2"

CLOSE_REASONS = {
    "SL", "TP1", "TP2", "BU", "BE", "TIMEOUT", "PROFIT_TIMEOUT", "FADE",
    "STALL", "LIQ", "MANUAL", "WEAK_PROGRESS", "WEAK_PROGRESS_STALE",
    "AGGRESSIVE_BE", "SMART_TIMEOUT_TRAIL", "SETUP_DIED",
}


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    try:
        return str(v).strip()
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return default


def _norm_market(v: Any) -> str:
    m = _safe_str(v).upper()
    if m in {"FUTURES", "FUTURE", "FUT"}:
        return "FUT"
    if m == "SPOT":
        return "SPOT"
    return m or "UNKNOWN"


def _norm_side(v: Any) -> str:
    s = _safe_str(v).upper()
    if s == "BUY":
        return "LONG"
    if s == "SELL":
        return "SHORT"
    return s


def _parse_trade_ts(value: Any) -> Optional[float]:
    s = _safe_str(value)
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.strptime(s.replace("Z", ""), fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
    try:
        return float(s)
    except Exception:
        return None


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        if not path.exists():
            return rows
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except Exception:
                continue
    except Exception:
        return rows
    return rows


def _read_trades_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    first = lines[0].lower()
    has_header = "symbol" in first and "reason" in first
    rows: List[Dict[str, Any]] = []

    if has_header:
        reader = csv.DictReader(lines)
        for row in reader:
            rows.append({str(k).strip(): v for k, v in row.items() if k is not None})
        return rows

    # Fallback for headerless CSV.
    fieldnames = [
        "ts", "symbol", "side", "market", "entry", "tp", "exit_price",
        "pnl", "pnl_net", "reason", "hold_sec", "setup_type", "args_text",
    ]
    reader = csv.reader(lines)
    for raw in reader:
        row = {fieldnames[i]: (raw[i] if i < len(raw) else "") for i in range(len(fieldnames))}
        if len(raw) > len(fieldnames):
            row["args_text"] = ",".join(raw[len(fieldnames) - 1:])
        rows.append(row)
    return rows


def _normalize_trade(row: Dict[str, Any]) -> Dict[str, Any]:
    reason = _safe_str(row.get("reason")).upper()
    market = _norm_market(row.get("market"))
    side = _norm_side(row.get("side"))
    symbol = _safe_str(row.get("symbol")).upper()
    ts_s = _safe_str(row.get("ts"))
    ts_epoch = _parse_trade_ts(ts_s)
    return {
        "ts": ts_s,
        "ts_epoch": ts_epoch,
        "symbol": symbol,
        "side": side,
        "market": market,
        "entry": _safe_float(row.get("entry")),
        "tp": _safe_float(row.get("tp")),
        "exit_price": _safe_float(row.get("exit_price")),
        "pnl": _safe_float(row.get("pnl")),
        "pnl_net": _safe_float(row.get("pnl_net")),
        "reason": reason,
        "hold_sec": _safe_int(row.get("hold_sec")),
        "setup_type": _safe_str(row.get("setup_type")),
        "args_text": _safe_str(row.get("args_text")),
    }


def _normalize_audit(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ts": _safe_float(row.get("ts")),
        "symbol": _safe_str(row.get("symbol")).upper(),
        "side": _norm_side(row.get("side")),
        "market": _norm_market(row.get("market")),
        "entry": _safe_float(row.get("entry")),
        "exit_price": _safe_float(row.get("exit_price")),
        "pnl": _safe_float(row.get("pnl")),
        "pnl_net": _safe_float(row.get("pnl_net")),
        "reason": _safe_str(row.get("reason")).upper(),
        "hold_sec": _safe_int(row.get("hold_sec")),
        "setup_type": _safe_str(row.get("setup_type")),
        "was_close_result": bool(row.get("was_close_result")),
        "schema_version": _safe_str(row.get("schema_version")),
    }


def _is_open_trade(t: Dict[str, Any]) -> bool:
    return t.get("reason") == "OPEN"


def _is_close_trade(t: Dict[str, Any]) -> bool:
    r = _safe_str(t.get("reason")).upper()
    return bool(r and r != "OPEN" and (r in CLOSE_REASONS or _safe_float(t.get("pnl_net"), 0.0) != 0.0 or _safe_int(t.get("hold_sec"), 0) > 0))


def _close_key_base(x: Dict[str, Any]) -> str:
    return f"{x.get('market')}:{x.get('symbol')}:{x.get('side')}:{x.get('reason')}"


def _approx(a: float, b: float, rel: float = 0.002, abs_tol: float = 1e-8) -> bool:
    if a == 0 or b == 0:
        return True  # Unknown value should not prevent matching.
    return abs(a - b) <= max(abs_tol, max(abs(a), abs(b)) * rel)


def _trade_audit_match(trade: Dict[str, Any], audit: Dict[str, Any]) -> bool:
    if _close_key_base(trade) != _close_key_base(audit):
        return False
    if not _approx(_safe_float(trade.get("entry")), _safe_float(audit.get("entry")), rel=0.001):
        return False
    if not _approx(_safe_float(trade.get("exit_price")), _safe_float(audit.get("exit_price")), rel=0.003):
        return False
    th = _safe_int(trade.get("hold_sec"))
    ah = _safe_int(audit.get("hold_sec"))
    if th > 0 and ah > 0 and abs(th - ah) > 10:
        return False
    tts = trade.get("ts_epoch")
    ats = audit.get("ts")
    if tts and ats and abs(float(tts) - float(ats)) > 300:
        return False
    return True


def _position_from_state_item(key: str, p: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(p, dict):
        return None
    symbol = _safe_str(p.get("symbol")).upper()
    market = _norm_market(p.get("market") or ("SPOT" if "SPOT" in key.upper() else "FUT"))
    side = _norm_side(p.get("side"))
    if not side and market == "SPOT":
        side = "LONG"
    if not symbol:
        # key often looks like SYMBOL::FUT
        symbol = _safe_str(key.split("::")[0]).upper()
    open_time = _safe_float(p.get("open_time") or p.get("opened_at") or p.get("open_ts"))
    entry = _safe_float(p.get("entry") or p.get("avg_price"))
    return {
        "symbol": symbol,
        "market": market,
        "side": side,
        "entry": entry,
        "open_time": open_time,
        "raw_key": key,
        "pnl_net": _safe_float(p.get("pnl_net")),
        "setup_type": _safe_str(p.get("setup_type")),
    }


def _positions_from_state(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = state.get("open") if isinstance(state, dict) else {}
    out: List[Dict[str, Any]] = []
    if isinstance(raw, dict):
        for key, pos in raw.items():
            item = _position_from_state_item(str(key), pos)
            if item:
                out.append(item)
    return out


def _positions_from_dashboard(dashboard: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    positions = dashboard.get("positions", {}) if isinstance(dashboard, dict) else {}
    if not isinstance(positions, dict):
        return out
    for market_key, market_name in (("fut", "FUT"), ("spot", "SPOT")):
        block = positions.get(market_key) or {}
        if isinstance(block, dict):
            for key, pos in block.items():
                if not isinstance(pos, dict):
                    continue
                symbol = _safe_str(pos.get("symbol") or key).upper()
                side = _norm_side(pos.get("side"))
                if market_name == "SPOT" and not side:
                    side = "LONG"
                out.append({
                    "symbol": symbol,
                    "market": market_name,
                    "side": side,
                    "entry": _safe_float(pos.get("entry") or pos.get("avg_price")),
                    "open_time": _safe_float(pos.get("open_time") or pos.get("opened_at") or pos.get("open_ts")),
                    "pnl_net": _safe_float(pos.get("pnl_net")),
                    "setup_type": _safe_str(pos.get("setup_type")),
                })
    return out


def _open_key(p: Dict[str, Any]) -> str:
    # Use a 5 minute bucket so small serialization differences do not explode matching.
    bucket = int((_safe_float(p.get("open_time")) or 0) // 300 * 300)
    entry = round(_safe_float(p.get("entry")), 8)
    return f"{p.get('market')}:{p.get('symbol')}:{p.get('side')}:{entry}:{bucket}"


def _soft_open_match(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if a.get("market") != b.get("market") or a.get("symbol") != b.get("symbol"):
        return False
    if a.get("side") and b.get("side") and a.get("side") != b.get("side"):
        return False
    if not _approx(_safe_float(a.get("entry")), _safe_float(b.get("entry")), rel=0.003):
        return False
    at = _safe_float(a.get("open_time"))
    bt = _safe_float(b.get("open_time"))
    if at > 0 and bt > 0 and abs(at - bt) > 600:
        return False
    return True


def _issue(tp: str, severity: str, key: str, message: str, **extra) -> Dict[str, Any]:
    d = {"type": tp, "severity": severity, "key": key, "message": message}
    d.update(extra)
    return d


def reconcile(root: Path, trades_csv: Path, trades_state: Path, close_audit: Path, dashboard_json: Optional[Path], audit_start_ts: Optional[float] = None) -> Dict[str, Any]:
    dashboard = _read_json(dashboard_json, {}) if dashboard_json else {}
    state = _read_json(trades_state, {})
    trade_rows = [_normalize_trade(r) for r in _read_trades_csv(trades_csv)]
    audit_rows = [_normalize_audit(r) for r in _read_jsonl(close_audit)]
    audit_closes = [a for a in audit_rows if a.get("was_close_result")]

    if audit_start_ts is None and audit_closes:
        audit_start_ts = min(_safe_float(a.get("ts")) for a in audit_closes if _safe_float(a.get("ts")) > 0) or None

    state_open = _positions_from_state(state if isinstance(state, dict) else {})
    dash_open = _positions_from_dashboard(dashboard if isinstance(dashboard, dict) else {})
    trade_closes = [t for t in trade_rows if _is_close_trade(t)]
    trade_opens = [t for t in trade_rows if _is_open_trade(t)]

    issues: List[Dict[str, Any]] = []

    # Open state mismatch.
    for sp in state_open:
        if not any(_soft_open_match(sp, dp) for dp in dash_open):
            issues.append(_issue(
                "OPEN_IN_STATE_ONLY", "warning", _open_key(sp),
                "Open position exists in trades_state but not in dashboard snapshot.",
                state_position=sp,
            ))
    for dp in dash_open:
        if not any(_soft_open_match(dp, sp) for sp in state_open):
            issues.append(_issue(
                "OPEN_IN_DASHBOARD_ONLY", "warning", _open_key(dp),
                "Open position exists in dashboard snapshot but not in trades_state.",
                dashboard_position=dp,
            ))

    # Duplicate OPEN rows by symbol/market/side close-free history signal.
    open_groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in trade_opens:
        gkey = f"{t.get('market')}:{t.get('symbol')}:{t.get('side')}"
        open_groups.setdefault(gkey, []).append(t)
    for gkey, arr in open_groups.items():
        if len(arr) >= 3:
            issues.append(_issue(
                "DUPLICATE_OPEN_ROWS", "info", gkey,
                f"Multiple OPEN rows found for the same market/symbol/side ({len(arr)}). This may be historical noise or repeated open logging.",
                count=len(arr),
                samples=arr[-5:],
            ))

    # Trade close <-> audit matching.
    matched_trade_idx = set()
    matched_audit_idx = set()
    for ti, tr in enumerate(trade_closes):
        for ai, au in enumerate(audit_closes):
            if ai in matched_audit_idx:
                continue
            if _trade_audit_match(tr, au):
                matched_trade_idx.add(ti)
                matched_audit_idx.add(ai)
                break

    legacy_before_audit = 0
    for ti, tr in enumerate(trade_closes):
        if ti in matched_trade_idx:
            continue
        tts = tr.get("ts_epoch")
        if audit_start_ts and tts and tts < float(audit_start_ts) - 60:
            legacy_before_audit += 1
            continue
        issues.append(_issue(
            "TRADE_CLOSE_WITHOUT_AUDIT", "warning", f"{_close_key_base(tr)}:{tr.get('entry')}:{tr.get('exit_price')}:{tr.get('hold_sec')}",
            "trades.csv close row exists after audit start but matching close audit row was not found.",
            trade=tr,
        ))

    for ai, au in enumerate(audit_closes):
        if ai in matched_audit_idx:
            continue
        issues.append(_issue(
            "AUDIT_WITHOUT_TRADE_ROW", "warning", f"{_close_key_base(au)}:{au.get('entry')}:{au.get('exit_price')}:{au.get('hold_sec')}",
            "close audit row exists but matching trades.csv close row was not found.",
            audit=au,
        ))

    issue_types = sorted(set(i["type"] for i in issues))
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "ts": time.time(),
        "status": "OK" if not issues else "ISSUES_FOUND",
        "read_only": True,
        "sources": {
            "root": str(root),
            "trades_csv": str(trades_csv),
            "trades_state": str(trades_state),
            "close_audit": str(close_audit),
            "dashboard_json": str(dashboard_json) if dashboard_json else "",
        },
        "summary": {
            "trades_rows": len(trade_rows),
            "trade_open_rows": len(trade_opens),
            "trade_close_rows": len(trade_closes),
            "audit_rows": len(audit_rows),
            "audit_close_rows": len(audit_closes),
            "audit_start_ts": audit_start_ts,
            "legacy_close_rows_before_audit": legacy_before_audit,
            "state_open_count": len(state_open),
            "dashboard_open_count": len(dash_open),
            "issues_count": len(issues),
            "issue_types": issue_types,
        },
        "issues": issues,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="VORTEX read-only runtime position reconciler")
    ap.add_argument("--root", default=".")
    ap.add_argument("--trades-csv", default="trades.csv")
    ap.add_argument("--trades-state", default="trades_state.json")
    ap.add_argument("--close-audit", default="_runtime/close_result_audit.jsonl")
    ap.add_argument("--dashboard-json", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--audit-start-ts", type=float, default=None)
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    trades_csv = (root / args.trades_csv).resolve() if not Path(args.trades_csv).is_absolute() else Path(args.trades_csv)
    trades_state = (root / args.trades_state).resolve() if not Path(args.trades_state).is_absolute() else Path(args.trades_state)
    close_audit = (root / args.close_audit).resolve() if not Path(args.close_audit).is_absolute() else Path(args.close_audit)
    dashboard_json = Path(args.dashboard_json).resolve() if args.dashboard_json else None

    report = reconcile(root, trades_csv, trades_state, close_audit, dashboard_json, audit_start_ts=args.audit_start_ts)
    text = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
