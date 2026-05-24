import json
from pathlib import Path
LATEST = Path("_runtime/strategy_observer_latest.json")
SUMMARY = Path("_runtime/strategy_observer_summary.jsonl")

def _strategy_line(x):
    s = x.get("strategy") or {}; p = x.get("policy") or {}; ta = x.get("ta") or {}; ea = x.get("ea") or {}
    return (f"{x.get('symbol')} {s.get('signal')} | state: {x.get('state')} | score: {s.get('score')} | setup: {s.get('setup_type')} | EA: {ea.get('raw') or 'NO_EA'} | policy: {p.get('code')} | reason: {p.get('reason') or s.get('blocked_reason')} | adx: {ta.get('adx')} | trend: {ta.get('trend_4h')} | rsi: {ta.get('rsi_main')} | vol: {ta.get('vol_ratio')}")

def show_latest():
    if not LATEST.exists():
        print("no latest strategy observer snapshot:", LATEST); return
    d = json.loads(LATEST.read_text(encoding="utf-8"))
    print("schema:", d.get("schema_version")); print("ts:", d.get("ts")); print("summary:", d.get("summary"))
    print("\n===== READY ALLOWED =====")
    for x in d.get("ready_allowed", [])[:20]: print(_strategy_line(x))
    print("\n===== READY BLOCKED =====")
    for x in d.get("ready_blocked", [])[:30]: print(_strategy_line(x))
    print("\n===== RAW READY / NO EA =====")
    for x in d.get("raw_ready_no_ea", [])[:30]: print(_strategy_line(x))
    print("\n===== TOP WATCH =====")
    for x in d.get("top_watch", [])[:20]: print(_strategy_line(x))

def show_tail():
    if not SUMMARY.exists(): return
    print("\n===== SUMMARY TAIL =====")
    for line in SUMMARY.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]:
        try:
            d = json.loads(line); print("ts:", d.get("ts"), "|", d.get("summary"))
        except Exception: print(line[:300])
if __name__ == "__main__":
    show_latest(); show_tail()
