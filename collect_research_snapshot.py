import json
import tarfile
import time
from pathlib import Path

files = [
    "_runtime/trade_diagnostics.jsonl",
    "_runtime/entry_argument_snapshots.jsonl",
    "_runtime/fee_cover_shadow_guard.json",
    "_runtime/shadow_variant_results.json",
    "_runtime/exit_diagnostics_summary.json",
    "_runtime/research_report_latest.json",
    "_runtime/entry_quality_matrix.json",
    "_runtime/outcome_summary.json",
    "_runtime/shadow_policy_simulation.json",
    "trades.csv",
    "trades_state.json",
]

out_dir = Path("_analysis")
out_dir.mkdir(parents=True, exist_ok=True)
stamp = time.strftime("%Y%m%d_%H%M%S")
bundle = out_dir / f"vortex_research_snapshot_{stamp}.tar.gz"

with tarfile.open(bundle, "w:gz") as tar:
    for f in files:
        p = Path(f)
        if p.exists():
            tar.add(p, arcname=f)

manifest = {
    "schema": "vortex.research_snapshot.v1",
    "schema_version": "1.8.19f",
    "created_at": time.time(),
    "bundle": str(bundle),
    "included": [f for f in files if Path(f).exists()],
    "missing": [f for f in files if not Path(f).exists()],
}

manifest_path = out_dir / f"vortex_research_snapshot_{stamp}.json"
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

print(json.dumps(manifest, ensure_ascii=False, indent=2))
