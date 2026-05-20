import json
from pathlib import Path
from collections import defaultdict


def load_jsonl(path):
    p = Path(path)
    rows = []
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def avg(values):
    vals = [float(v) for v in values if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 8) if vals else 0.0


def bucket(value, edges):
    try:
        value = float(value)
    except Exception:
        return "missing"
    prev = None
    for edge in edges:
        if value <= edge:
            return f"<= {edge}"
        prev = edge
    return f"> {edges[-1]}"


entries = load_jsonl("_runtime/entry_argument_snapshots.jsonl")
diagnostics = load_jsonl("_runtime/trade_diagnostics.jsonl")

# approximate join by symbol + setup order buckets
diag_by_symbol_setup = defaultdict(list)
for d in diagnostics:
    diag_by_symbol_setup[(d.get("symbol"), d.get("setup_type"))].append(d)

matrix = defaultdict(lambda: {
    "count": 0,
    "mfe": [],
    "final": [],
    "good": 0,
    "small_green": 0,
})

for e in entries:
    ta = e.get("ta") or {}
    key = (
        e.get("setup_type") or "UNKNOWN",
        "adx_" + bucket(ta.get("adx"), [20, 35, 50, 70]),
        "vol_" + bucket(ta.get("volume_ratio"), [1, 2, 3, 5]),
        "range_" + bucket(ta.get("range_pct"), [3, 5, 8, 12]),
    )
    matches = diag_by_symbol_setup.get((e.get("symbol"), e.get("setup_type")), [])
    if matches:
        d = matches.pop(0)
        matrix[key]["count"] += 1
        matrix[key]["mfe"].append(d.get("mfe_pct"))
        matrix[key]["final"].append(d.get("final_pnl_pct_est"))
        if (d.get("entry_quality") or {}).get("mfe_gt_abs_mae"):
            matrix[key]["good"] += 1
        if (d.get("fee_cover_hint") or {}).get("small_green_possible"):
            matrix[key]["small_green"] += 1

out = []
for key, v in matrix.items():
    if v["count"] <= 0:
        continue
    setup, adx_b, vol_b, range_b = key
    out.append({
        "setup": setup,
        "adx_bucket": adx_b,
        "volume_bucket": vol_b,
        "range_bucket": range_b,
        "count": v["count"],
        "avg_mfe_pct": avg(v["mfe"]),
        "avg_final_pnl_pct": avg(v["final"]),
        "good_entry_pct": round(v["good"] / v["count"] * 100, 2),
        "small_green_pct": round(v["small_green"] / v["count"] * 100, 2),
    })

out = sorted(out, key=lambda x: (x["setup"], -x["count"], -x["avg_final_pnl_pct"]))

payload = {
    "schema": "vortex.entry_quality_matrix.v1",
    "schema_version": "1.8.19f",
    "rows": out,
}

Path("_runtime/entry_quality_matrix.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
    encoding="utf-8",
)

print(json.dumps(payload, ensure_ascii=False, indent=2)[:6000])
