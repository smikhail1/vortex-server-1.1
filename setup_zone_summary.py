import json
from pathlib import Path


LATEST = Path("_runtime/setup_zone_latest.json")
SUMMARY = Path("_runtime/setup_zone_summary.jsonl")


def _line(x, side):
    if side == "long":
        return (
            f"{x.get('symbol')} | q:{x.get('long_zone_quality')} | zone:{x.get('preferred_zone')} | "
            f"range:{x.get('range_position_pct')} | near20:{x.get('near_ema20')} | "
            f"support:{x.get('near_support')} | resist:{x.get('near_resistance')} | "
            f"trend:{x.get('trend_4h')} | adx:{x.get('adx')} | rsi:{x.get('rsi_main')} | "
            f"vol:{x.get('vol_ratio')} | warn:{x.get('warnings')}"
        )
    return (
        f"{x.get('symbol')} | q:{x.get('short_zone_quality')} | zone:{x.get('preferred_zone')} | "
        f"range:{x.get('range_position_pct')} | near20:{x.get('near_ema20')} | "
        f"support:{x.get('near_support')} | resist:{x.get('near_resistance')} | "
        f"trend:{x.get('trend_4h')} | adx:{x.get('adx')} | rsi:{x.get('rsi_main')} | "
        f"vol:{x.get('vol_ratio')} | warn:{x.get('warnings')}"
    )


def show_latest():
    if not LATEST.exists():
        print("no latest setup zone snapshot:", LATEST)
        return

    d = json.loads(LATEST.read_text(encoding="utf-8"))
    print("schema:", d.get("schema_version"))
    print("ts:", d.get("ts"))
    print("summary:", d.get("summary"))

    print()
    print("===== TOP LONG ZONES =====")
    for x in d.get("top_long_zones", [])[:20]:
        print(_line(x, "long"))

    print()
    print("===== TOP SHORT ZONES =====")
    for x in d.get("top_short_zones", [])[:20]:
        print(_line(x, "short"))


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
