from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "main.py").read_text(encoding="utf-8")

assert 'guard_decision = {"allow": False, "reason": f"post_close_cooldown_error:{exc}"}' in text
assert '"futures pre-open guard failed closed"' in text
assert 'guard_decision = {"allow": True, "reason": f"guard_error_fail_open:{exc}"}' not in text
assert '"futures pre-open guard failed open"' not in text

print("OK: smoke_preopen_guard_fail_closed")
