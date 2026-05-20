import json
import time
from pathlib import Path
from collections import defaultdict, Counter


def load_jsonl(path):
    p = Path(path)
    rows = []
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def avg(values):
    vals = []
    for v in values:
        if isinstance(v, (int, float)):
            vals.append(float(v))
    return round(sum(vals) / len(vals), 8) if vals else 0.0


def pct(part, total):
    return round(part / total * 100.0, 2) if total else 0.0


def pctl(values, q):
    vals = sorted(float(v) for v in values if isinstance(v, (int, float)))
    if not vals:
        return 0.0
    idx = int(round((len(vals) - 1) * q))
    return round(vals[max(0, min(idx, len(vals) - 1))], 8)


diagnostics = load_jsonl("_runtime/trade_diagnostics.jsonl")
entries = load_jsonl("_runtime/entry_argument_snapshots.jsonl")

by_setup = defaultdict(list)
by_reason = defaultdict(list)

for r in diagnostics:
    by_setup[r.get("setup_type") or "UNKNOWN"].append(r)
    by_reason[r.get("close_reason") or "UNKNOWN"].append(r)

setup_summary = {}
for setup, rows in by_setup.items():
    good = sum(1 for r in rows if (r.get("entry_quality") or {}).get("mfe_gt_abs_mae"))
    had_profit = sum(1 for r in rows if (r.get("entry_quality") or {}).get("had_positive_excursion"))
    neg_final = sum(1 for r in rows if (r.get("final_pnl_pct_est") or 0) < 0)
    small_green = sum(1 for r in rows if (r.get("fee_cover_hint") or {}).get("small_green_possible"))
    setup_summary[setup] = {
        "count": len(rows),
        "avg_mfe_pct": avg([r.get("mfe_pct") for r in rows]),
        "avg_mae_pct": avg([r.get("mae_pct") for r in rows]),
        "avg_final_pnl_pct": avg([r.get("final_pnl_pct_est") for r in rows]),
        "p50_mfe_pct": pctl([r.get("mfe_pct") for r in rows], 0.50),
        "p80_mfe_pct": pctl([r.get("mfe_pct") for r in rows], 0.80),
        "good_entry_ratio_pct": pct(good, len(rows)),
        "had_profit_ratio_pct": pct(had_profit, len(rows)),
        "negative_final_ratio_pct": pct(neg_final, len(rows)),
        "small_green_possible_count": small_green,
        "small_green_possible_pct": pct(small_green, len(rows)),
    }

reason_summary = {}
for reason, rows in by_reason.items():
    reason_summary[reason] = {
        "count": len(rows),
        "avg_mfe_pct": avg([r.get("mfe_pct") for r in rows]),
        "avg_mae_pct": avg([r.get("mae_pct") for r in rows]),
        "avg_final_pnl_pct": avg([r.get("final_pnl_pct_est") for r in rows]),
        "avg_exit_gave_back_pct": avg([(r.get("entry_quality") or {}).get("exit_gave_back_pct") for r in rows]),
        "be_had_profit_count": sum(1 for r in rows if (r.get("be_damage") or {}).get("had_profit_before_be")),
        "small_green_possible_count": sum(1 for r in rows if (r.get("fee_cover_hint") or {}).get("small_green_possible")),
    }

# Entry argument buckets
entry_by_setup = defaultdict(list)
for e in entries:
    entry_by_setup[e.get("setup_type") or "UNKNOWN"].append(e)

entry_summary = {}
for setup, rows in entry_by_setup.items():
    ta_rows = [(r.get("ta") or {}) for r in rows]
    entry_summary[setup] = {
        "count": len(rows),
        "avg_adx": avg([t.get("adx") for t in ta_rows]),
        "avg_rsi": avg([t.get("rsi") for t in ta_rows]),
        "avg_volume_ratio": avg([t.get("volume_ratio") for t in ta_rows]),
        "avg_atr_pct": avg([t.get("atr_pct") for t in ta_rows]),
        "avg_change_pct": avg([t.get("change_pct") for t in ta_rows]),
        "avg_range_pct": avg([t.get("range_pct") for t in ta_rows]),
        "confirmed_count": sum(1 for r in rows if (r.get("watch") or {}).get("confirmed")),
        "data_quality_avg": avg([(r.get("data_quality") or {}).get("score") for r in rows]),
    }

overall = {
    "diagnostic_rows": len(diagnostics),
    "entry_argument_rows": len(entries),
    "had_positive_mfe_count": sum(1 for r in diagnostics if (r.get("mfe_pct") or 0) > 0),
    "negative_final_count": sum(1 for r in diagnostics if (r.get("final_pnl_pct_est") or 0) < 0),
    "be_had_profit_count": sum(1 for r in diagnostics if (r.get("be_damage") or {}).get("had_profit_before_be")),
    "small_green_possible_count": sum(1 for r in diagnostics if (r.get("fee_cover_hint") or {}).get("small_green_possible")),
}

overall["had_positive_mfe_pct"] = pct(overall["had_positive_mfe_count"], len(diagnostics))
overall["negative_final_pct"] = pct(overall["negative_final_count"], len(diagnostics))
overall["small_green_possible_pct"] = pct(overall["small_green_possible_count"], len(diagnostics))

payload = {
    "schema": "vortex.research_analytics_report.v1",
    "schema_version": "1.8.19f",
    "generated_at": time.time(),
    "source": {
        "diagnostics": "_runtime/trade_diagnostics.jsonl",
        "entry_arguments": "_runtime/entry_argument_snapshots.jsonl",
    },
    "overall": overall,
    "by_setup": setup_summary,
    "by_close_reason": reason_summary,
    "entry_arguments_by_setup": entry_summary,
    "notes": [
        "analytics_only",
        "no execution changes",
        "intended for 24h research-mode review",
    ],
}

out_dir = Path("_runtime/research_reports")
out_dir.mkdir(parents=True, exist_ok=True)
stamp = time.strftime("%Y%m%d_%H%M%S")
out_path = out_dir / f"research_report_{stamp}.json"
latest_path = Path("_runtime/research_report_latest.json")

out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

print(json.dumps({
    "schema_version": payload["schema_version"],
    "report": str(out_path),
    "latest": str(latest_path),
    "overall": overall,
}, ensure_ascii=False, indent=2))
