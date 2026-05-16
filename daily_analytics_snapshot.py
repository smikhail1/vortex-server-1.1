import json
import time
from pathlib import Path

FILES = [
    "_runtime/outcome_summary.json",
    "_runtime/policy_recommendations.json",
    "_runtime/shadow_adaptive_replay.json",
]

SNAPSHOT_DIR = Path("_runtime/daily_snapshots")
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

payload = {
    "schema": "vortex.daily_analytics_snapshot.v1",
    "generated_at": time.time(),
    "files": {}
}

for f in FILES:
    p = Path(f)
    if p.exists():
        try:
            payload["files"][f] = json.loads(
                p.read_text(encoding="utf-8")
            )
        except Exception as exc:
            payload["files"][f] = {
                "error": str(exc)
            }

name = time.strftime("%Y%m%d_%H%M%S") + ".json"
out = SNAPSHOT_DIR / name

out.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(json.dumps({
    "snapshot": str(out),
    "files": list(payload["files"].keys())
}, ensure_ascii=False, indent=2))

