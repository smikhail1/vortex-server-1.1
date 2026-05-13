import csv
import os
from typing import Any, Dict, List


TRADES_FILE = "trades.csv"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    if "ts" in row:
        return {
            "ts": _safe_str(row.get("ts")),
            "symbol": _safe_str(row.get("symbol")).upper(),
            "side": _safe_str(row.get("side")).upper(),
            "market": _safe_str(row.get("market")).upper(),
            "entry": _safe_float(row.get("entry")),
            "tp": _safe_float(row.get("tp")),
            "exit": _safe_float(row.get("exit")),
            "pnl": _safe_float(row.get("pnl")),
            "pnl_net": _safe_float(row.get("pnl_net")),
            "reason": _safe_str(row.get("reason")).upper(),
            "hold_sec": int(_safe_float(row.get("hold_sec"))),
            "setup_type": _safe_str(row.get("setup_type")),
            "args_text": _safe_str(row.get("args_text")),
        }

    # Legacy fallback.
    return {
        "ts": _safe_str(row.get("timestamp")),
        "symbol": _safe_str(row.get("symbol")).upper(),
        "side": _safe_str(row.get("side")).upper(),
        "market": _safe_str(row.get("type")).upper(),
        "entry": _safe_float(row.get("entry_price")),
        "tp": _safe_float(row.get("target_tp")),
        "exit": _safe_float(row.get("exit_price")),
        "pnl": _safe_float(row.get("pnl")),
        "pnl_net": _safe_float(row.get("pnl")),
        "reason": _safe_str(row.get("status")).upper(),
        "hold_sec": 0,
        "setup_type": _safe_str(row.get("setup_type")),
        "args_text": _safe_str(row.get("args_text")),
    }


def read_trades(limit: int = 1000) -> List[Dict[str, Any]]:
    if not os.path.exists(TRADES_FILE):
        return []

    rows: List[Dict[str, Any]] = []
    with open(TRADES_FILE, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row:
                rows.append(_normalize_row(row))

    if limit <= 0:
        return rows
    return rows[-limit:]


def build_history(limit: int = 100) -> List[Dict[str, Any]]:
    return read_trades(limit=limit)


def build_stats(limit: int = 1000) -> Dict[str, Any]:
    trades = read_trades(limit=limit)
    closed = [t for t in trades if t.get("reason") not in ("", "OPEN")]

    if not closed:
        return {
            "total": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "avg_pnl_net": 0.0,
            "avg_hold_sec": 0,
            "reasons": {},
            "by_market": {},
            "by_setup": {},
        }

    total = 0
    wins = 0
    pnl_sum = 0.0
    pnl_net_sum = 0.0
    hold_sum = 0.0
    reasons: Dict[str, int] = {}
    by_market: Dict[str, int] = {}
    by_setup: Dict[str, int] = {}

    for row in closed:
        pnl = _safe_float(row.get("pnl"))
        pnl_net = _safe_float(row.get("pnl_net"))
        hold_sec = _safe_float(row.get("hold_sec"))

        total += 1
        pnl_sum += pnl
        pnl_net_sum += pnl_net
        hold_sum += hold_sec

        if pnl_net > 0:
            wins += 1

        reason = _safe_str(row.get("reason"), "UNKNOWN").upper() or "UNKNOWN"
        market = _safe_str(row.get("market"), "UNKNOWN").upper() or "UNKNOWN"
        setup_type = _safe_str(row.get("setup_type"), "UNKNOWN") or "UNKNOWN"

        reasons[reason] = reasons.get(reason, 0) + 1
        by_market[market] = by_market.get(market, 0) + 1
        by_setup[setup_type] = by_setup.get(setup_type, 0) + 1

    return {
        "total": total,
        "win_rate": round(wins / total, 4) if total else 0.0,
        "avg_pnl": round(pnl_sum / total, 6) if total else 0.0,
        "avg_pnl_net": round(pnl_net_sum / total, 6) if total else 0.0,
        "avg_hold_sec": int(hold_sum / total) if total else 0,
        "reasons": reasons,
        "by_market": by_market,
        "by_setup": by_setup,
    }
