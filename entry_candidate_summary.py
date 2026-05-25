import json
from collections import Counter
from pathlib import Path


PATH = Path("_runtime/entry_candidates.jsonl")
DEDUP_SUMMARY = Path("_runtime/entry_candidate_dedup_summary.json")


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def show_dedup():
    print("===== DEDUP SUMMARY =====")
    summary = _load_json(DEDUP_SUMMARY)
    if not summary:
        print("no dedup summary:", DEDUP_SUMMARY)
        return

    print("schema:", summary.get("schema_version"))
    print("dedup_window_sec:", summary.get("dedup_window_sec"))
    print("total_seen:", summary.get("total_seen"))
    print("total_written:", summary.get("total_written"))
    print("total_suppressed:", summary.get("total_suppressed"))
    print("unique_keys:", summary.get("unique_keys"))
    print("top_policy:", summary.get("top_policy"))
    print("top_symbol:", summary.get("top_symbol"))
    print("top_setup:", summary.get("top_setup"))
    print("top_ea_grade:", summary.get("top_ea_grade"))


def main():
    show_dedup()
    print()

    if not PATH.exists():
        print("no entry candidate journal:", PATH)
        return

    rows = []
    for line in PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass

    print("===== JOURNAL SUMMARY =====")
    print("written_rows:", len(rows))
    print("final_action:", dict(Counter(r.get("final_action") for r in rows)))
    print("policy_code:", dict(Counter(r.get("policy_code") for r in rows)))
    print("ea_grade:", dict(Counter((r.get("ea") or {}).get("grade") or "NO_EA" for r in rows)))
    print("setup_type:", dict(Counter(r.get("setup_type") or "UNKNOWN" for r in rows)))

    print()
    print("===== LAST 30 WRITTEN =====")
    for r in rows[-30:]:
        ea = r.get("ea") or {}
        dedup = r.get("dedup") or {}
        print(
            r.get("symbol"),
            r.get("side"),
            "| setup:", r.get("setup_type"),
            "| EA:", (ea.get("raw") or "NO_EA"),
            "| policy:", r.get("policy_code"),
            "| action:", r.get("final_action"),
            "| result:", r.get("router_result_code"),
            "| seen:", dedup.get("seen_count"),
            "| suppressed:", dedup.get("suppressed_count"),
            "| reason:", r.get("policy_reason"),
        )


if __name__ == "__main__":
    main()
