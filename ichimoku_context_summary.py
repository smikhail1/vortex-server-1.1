import json
from pathlib import Path

PATH = Path("_runtime/ichimoku_context_latest.json")


def main():
    if not PATH.exists():
        print("ichimoku snapshot missing:", PATH)
        return

    d = json.loads(PATH.read_text(encoding="utf-8"))
    print("schema:", d.get("schema_version"))
    print("ts:", d.get("ts"))
    print("symbols_count:", d.get("symbols_count"))
    print("available_count:", d.get("available_count"))
    print("summary:", d.get("summary"))

    rows = list(d.get("symbols") or [])
    rows.sort(key=lambda x: (x.get("quality") or 0), reverse=True)

    print()
    print("===== TOP 40 ICHIMOKU CONTEXT =====")
    for x in rows[:40]:
        print(
            f"{x.get('symbol')} | trend:{x.get('trend_bias')} | cloud:{x.get('cloud_state')} | "
            f"TK:{x.get('tk_state')} | q:{x.get('quality')} | "
            f"LONG:{x.get('long_support')} | SHORT:{x.get('short_support')} | "
            f"warnings:{x.get('warnings')}"
        )


if __name__ == "__main__":
    main()
