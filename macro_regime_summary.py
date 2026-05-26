import json
from pathlib import Path

PATH = Path("_runtime/macro_regime_latest.json")


def main():
    if not PATH.exists():
        print("macro regime snapshot missing:", PATH)
        return
    d = json.loads(PATH.read_text(encoding="utf-8"))
    print("schema:", d.get("schema_version"))
    print("ts:", d.get("ts"))
    print("regime:", d.get("regime"))
    print("confidence:", d.get("confidence"))
    print("recommendation:", d.get("recommendation"))
    print()
    print("heatmap:", d.get("heatmap"))
    print()
    print("ichimoku_breadth:", d.get("ichimoku_breadth"))
    print()
    print("futures_pressure:", d.get("futures_pressure"))
    print()
    print("vortex_pressure:", d.get("vortex_pressure"))
    print()
    print("reasons:", d.get("reasons"))
    print("warnings:", d.get("warnings"))


if __name__ == "__main__":
    main()
