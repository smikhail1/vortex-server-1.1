import json
from pathlib import Path


LATEST = Path("_runtime/context_fusion_latest.json")
SUMMARY = Path("_runtime/context_fusion_summary.jsonl")


def _line(x):
    f = x.get("final") or {}
    z = x.get("setup_zone") or {}
    h = x.get("heatmap") or {}
    hg = h.get("global") or {}
    p = x.get("policy") or {}
    return (
        f"{x.get('symbol')} {x.get('side') or '-'} | "
        f"view:{f.get('view')} | score:{f.get('score')} | "
        f"strategy:{x.get('strategy_state')} | "
        f"zone:{z.get('preferred_zone')} q:{z.get('zone_quality')} {z.get('support_status')} | "
        f"heatmap:{hg.get('bias')} {hg.get('support_status')} | "
        f"policy:{p.get('code')} | "
        f"blockers:{f.get('blockers')} | warnings:{f.get('warnings')}"
    )


def show_latest():
    if not LATEST.exists():
        print("no latest context fusion snapshot:", LATEST)
        return

    d = json.loads(LATEST.read_text(encoding="utf-8"))
    print("schema:", d.get("schema_version"))
    print("ts:", d.get("ts"))
    print("summary:", d.get("summary"))

    print()
    print("===== IMPORTANT CONTEXT =====")
    for x in d.get("important", [])[:30]:
        print(_line(x))

    print()
    print("===== RAW / POLICY / GOOD ZONE =====")
    for x in d.get("symbols", []):
        view = (x.get("final") or {}).get("view")
        if view in ("RAW_CANDIDATE_WAIT_EA_GOOD_ZONE", "ENTRY_CANDIDATE_STRONG", "POLICY_BLOCKED", "WATCH_GOOD_ZONE_WAIT_TRIGGER"):
            print(_line(x))


def show_tail():
    if not SUMMARY.exists():
        return

    print()
    print("===== SUMMARY TAIL =====")
    for line in SUMMARY.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]:
        try:
            d = json.loads(line)
            print("ts:", d.get("ts"), "|", d.get("summary"))
        except Exception:
            print(line[:300])


if __name__ == "__main__":
    show_latest()
    show_tail()
