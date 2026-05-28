import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any


TRADES = Path("trades.csv")
OUT_DIR = Path("_analysis")
OUT_DIR.mkdir(exist_ok=True)

CLOSE_REASONS = {
    "SL", "BU", "TP", "TP0", "TP1", "TP2",
    "TIMEOUT", "FADE", "STALL", "LIQ",
    "WEAK_PROGRESS", "WEAK_PROGRESS_STALE",
    "MANUAL", "CLOSE",
}


def parse_ts(s: str) -> float:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def f(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def ea_bucket(args: str) -> str:
    m = re.search(r"\bEA:([A-D])\/(\d+)\s+([A-Z_]+)", args or "")
    if not m:
        return "NO_EA"
    return f"EA:{m.group(1)}:{m.group(3)}"


def load_trades() -> List[Dict[str, Any]]:
    rows = []
    if not TRADES.exists():
        return rows

    with TRADES.open("r", encoding="utf-8", errors="replace", newline="") as fp:
        reader = csv.reader(fp)
        for parts in reader:
            if len(parts) < 12:
                continue

            ts, symbol, side, market = parts[0], parts[1], parts[2], parts[3]
            reason = parts[9].strip().upper()
            setup = parts[11].strip() if len(parts) > 11 else ""
            args = ",".join(parts[12:]).strip() if len(parts) > 12 else ""

            row = {
                "ts": ts,
                "ts_epoch": parse_ts(ts),
                "symbol": symbol.strip().upper(),
                "side": side.strip().upper(),
                "market": market.strip().upper(),
                "entry": f(parts[4]),
                "tp": f(parts[5]),
                "exit_price": f(parts[6]),
                "pnl": f(parts[7]),
                "pnl_net": f(parts[8]),
                "reason": reason,
                "hold_sec": int(f(parts[10], 0)),
                "setup_type": setup,
                "args_text": args,
                "ea_bucket": ea_bucket(args),
                "is_open": reason == "OPEN",
                "is_close": reason in CLOSE_REASONS and reason != "OPEN",
            }
            rows.append(row)

    return rows


def summarize_group(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    closes = [r for r in rows if r["is_close"]]
    opens = [r for r in rows if r["is_open"]]

    pnl = [r["pnl_net"] for r in closes]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]

    return {
        "opens": len(opens),
        "closes": len(closes),
        "net": round(sum(pnl), 6),
        "avg_net": round(statistics.mean(pnl), 6) if pnl else 0.0,
        "median_net": round(statistics.median(pnl), 6) if pnl else 0.0,
        "winrate_pct": round(len(wins) / len(pnl) * 100, 2) if pnl else 0.0,
        "wins": len(wins),
        "losses": len(losses),
        "best": round(max(pnl), 6) if pnl else 0.0,
        "worst": round(min(pnl), 6) if pnl else 0.0,
        "avg_hold_sec": round(statistics.mean([r["hold_sec"] for r in closes]), 1) if closes else 0.0,
        "reasons": dict(Counter(r["reason"] for r in closes)),
    }


def top_table(groups: Dict[str, List[Dict[str, Any]]], min_closes=2):
    out = []
    for k, rs in groups.items():
        s = summarize_group(rs)
        if s["closes"] >= min_closes:
            out.append((k, s))
    out.sort(key=lambda x: x[1]["net"])
    return out


def main():
    rows = load_trades()
    closes = [r for r in rows if r["is_close"]]
    opens = [r for r in rows if r["is_open"]]
    fut_rows = [r for r in rows if r["market"] == "FUT"]
    fut_closes = [r for r in fut_rows if r["is_close"]]
    fut_opens = [r for r in fut_rows if r["is_open"]]

    by_setup = defaultdict(list)
    by_symbol = defaultdict(list)
    by_ea = defaultdict(list)
    by_reason = defaultdict(list)
    by_day = defaultdict(list)

    for r in fut_rows:
        by_setup[r["setup_type"] or "UNKNOWN"].append(r)
        by_symbol[r["symbol"]].append(r)
        by_ea[r["ea_bucket"]].append(r)
        by_reason[r["reason"]].append(r)
        by_day[r["ts"][:10]].append(r)

    unmatched_open_candidates = []
    close_seen = defaultdict(int)
    for r in fut_closes:
        close_seen[(r["symbol"], r["side"])] += 1

    # Грубый индикатор: последние OPEN по symbol/side, если после них нет close в tail-контексте.
    for r in fut_opens[-120:]:
        later = [
            x for x in fut_closes
            if x["symbol"] == r["symbol"]
            and x["side"] == r["side"]
            and x["ts_epoch"] >= r["ts_epoch"]
        ]
        if not later:
            unmatched_open_candidates.append(r)

    report = {
        "schema": "vortex.trade_decision_report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "rows": len(rows),
            "opens": len(opens),
            "closes": len(closes),
            "fut_opens": len(fut_opens),
            "fut_closes": len(fut_closes),
        },
        "fut_total": summarize_group(fut_rows),
        "by_setup": {k: summarize_group(v) for k, v in sorted(by_setup.items())},
        "by_ea": {k: summarize_group(v) for k, v in sorted(by_ea.items())},
        "by_day": {k: summarize_group(v) for k, v in sorted(by_day.items())},
        "by_reason": {k: summarize_group(v) for k, v in sorted(by_reason.items())},
        "worst_symbols": top_table(by_symbol, min_closes=2)[:15],
        "best_symbols": list(reversed(top_table(by_symbol, min_closes=2)[-15:])),
        "worst_setups": top_table(by_setup, min_closes=2)[:15],
        "best_setups": list(reversed(top_table(by_setup, min_closes=2)[-15:])),
        "unmatched_recent_fut_opens": [
            {
                "ts": r["ts"],
                "symbol": r["symbol"],
                "side": r["side"],
                "entry": r["entry"],
                "setup_type": r["setup_type"],
                "ea_bucket": r["ea_bucket"],
                "args_text": r["args_text"],
            }
            for r in unmatched_open_candidates[-30:]
        ],
    }

    out_json = OUT_DIR / "trade_decision_report_latest.json"
    out_txt = OUT_DIR / "trade_decision_report_latest.txt"

    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    lines = []
    lines.append("===== VORTEX TRADE DECISION REPORT =====")
    lines.append(f"generated_at: {report['generated_at']}")
    lines.append("")
    lines.append("===== TOTALS =====")
    lines.append(json.dumps(report["totals"], ensure_ascii=False))
    lines.append("")
    lines.append("===== FUT TOTAL =====")
    lines.append(json.dumps(report["fut_total"], ensure_ascii=False))
    lines.append("")
    lines.append("===== BY DAY =====")
    for k, v in report["by_day"].items():
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("===== BY SETUP =====")
    for k, v in report["by_setup"].items():
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("===== BY EA =====")
    for k, v in report["by_ea"].items():
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("===== WORST SYMBOLS =====")
    for k, v in report["worst_symbols"]:
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("===== BEST SYMBOLS =====")
    for k, v in report["best_symbols"]:
        lines.append(f"{k}: {v}")
    lines.append("")
    lines.append("===== UNMATCHED RECENT FUT OPENS =====")
    for r in report["unmatched_recent_fut_opens"]:
        lines.append(json.dumps(r, ensure_ascii=False))

    out_txt.write_text("\n".join(lines), encoding="utf-8")

    print("report_json:", out_json)
    print("report_txt:", out_txt)
    print()
    print("===== SHORT SUMMARY =====")
    print("totals:", report["totals"])
    print("fut_total:", report["fut_total"])
    print()
    print("===== BY SETUP =====")
    for k, v in report["by_setup"].items():
        print(k, v)
    print()
    print("===== BY EA =====")
    for k, v in report["by_ea"].items():
        print(k, v)
    print()
    print("===== WORST SYMBOLS =====")
    for k, v in report["worst_symbols"][:10]:
        print(k, v)
    print()
    print("===== BEST SYMBOLS =====")
    for k, v in report["best_symbols"][:10]:
        print(k, v)
    print()
    print("===== UNMATCHED RECENT FUT OPENS =====")
    for r in report["unmatched_recent_fut_opens"][-15:]:
        print(r)


if __name__ == "__main__":
    main()
