from ea_verdict_bridge import write_latest_bridge


def main():
    d = write_latest_bridge()
    print("schema:", d.get("schema_version"))
    print("ts:", d.get("ts"))
    print("summary:", d.get("summary"))
    rows = []
    for item in (d.get("index") or {}).values():
        ea = item.get("ea") or {}
        pol = item.get("policy") or {}
        rows.append((item.get("symbol"), item.get("side"), item.get("setup_type"), ea.get("raw") or ea.get("label"), pol.get("code"), pol.get("reason"), item.get("ts")))
    rows.sort(key=lambda x: (x[6] or 0), reverse=True)
    print()
    print("===== LATEST 40 EA VERDICTS =====")
    for sym, side, setup, ea, code, reason, ts in rows[:40]:
        print(f"{sym} {side} | setup:{setup} | EA:{ea} | policy:{code} | reason:{reason} | ts:{ts}")


if __name__ == "__main__":
    main()
