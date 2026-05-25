import json
from pathlib import Path


LATEST = Path("_runtime/market_heatmap_latest.json")
SUMMARY = Path("_runtime/market_heatmap_summary.jsonl")


def show_latest():
    if not LATEST.exists():
        print("no latest market heatmap snapshot:", LATEST)
        return

    d = json.loads(LATEST.read_text(encoding="utf-8"))
    print("schema:", d.get("schema_version"))
    print("ts:", d.get("ts"))
    print("summary:", d.get("summary"))

    print()
    print("===== TOP LONG CONTEXT =====")
    for x in d.get("top_long_context", [])[:20]:
        print(
            x.get("symbol"),
            "| bias:", x.get("local_bias"),
            "| adx:", x.get("adx"),
            "| rsi:", x.get("rsi_main"),
            "| vol:", x.get("vol_ratio"),
            "| trend:", x.get("trend_4h"),
            "| above20:", x.get("above_ema20"),
            "| above50:", x.get("above_ema50"),
        )

    print()
    print("===== TOP SHORT CONTEXT =====")
    for x in d.get("top_short_context", [])[:20]:
        print(
            x.get("symbol"),
            "| bias:", x.get("local_bias"),
            "| adx:", x.get("adx"),
            "| rsi:", x.get("rsi_main"),
            "| vol:", x.get("vol_ratio"),
            "| trend:", x.get("trend_4h"),
            "| below20:", x.get("below_ema20"),
            "| below50:", x.get("below_ema50"),
        )


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
