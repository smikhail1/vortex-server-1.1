import json
from collections import Counter
from pathlib import Path


PATH = Path("_runtime/entry_candidates.jsonl")


def main():
    if not PATH.exists():
        print("no entry candidate journal:", PATH)
        return

    rows = []
    for line in PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass

    print("total:", len(rows))
    print("final_action:", dict(Counter(r.get("final_action") for r in rows)))
    print("policy_code:", dict(Counter(r.get("policy_code") for r in rows)))
    print("ea_grade:", dict(Counter((r.get("ea") or {}).get("grade") or "NO_EA" for r in rows)))
    print("setup_type:", dict(Counter(r.get("setup_type") or "UNKNOWN" for r in rows)))

    print()
    print("===== LAST 30 =====")
    for r in rows[-30:]:
        ea = r.get("ea") or {}
        print(
            r.get("symbol"),
            r.get("side"),
            "| setup:", r.get("setup_type"),
            "| EA:", (ea.get("raw") or "NO_EA"),
            "| policy:", r.get("policy_code"),
            "| action:", r.get("final_action"),
            "| result:", r.get("router_result_code"),
            "| reason:", r.get("policy_reason"),
        )


if __name__ == "__main__":
    main()
