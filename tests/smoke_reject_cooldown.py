from pathlib import Path

s = Path("main.py").read_text(encoding="utf-8")

required = [
    "VORTEX v1.8.22-e-r2",
    "_reject_cooldown_until",
    "skipped by reject cooldown",
    "cooldown={int(_reject_cd_sec)}s",
]

missing = [x for x in required if x not in s]
if missing:
    raise SystemExit(f"missing reject cooldown markers: {missing}")

scan_start = s.find("# 1) Scan futures")
confirm_start = s.find("# 2) Confirm futures")
if not (0 <= scan_start < confirm_start):
    raise SystemExit("scan/confirm block order invalid")

scan_block = s[scan_start:confirm_start]
if "skipped by reject cooldown" not in scan_block:
    raise SystemExit("cooldown check missing from futures scan block")
if scan_block.find("skipped by reject cooldown") > scan_block.find("upsert_from_analysis"):
    raise SystemExit("cooldown check appears after upsert; expected before")

print("OK: smoke_reject_cooldown")
