from pathlib import Path

text = Path("main.py").read_text(encoding="utf-8")

required = [
    'confirmed_fut_items = watch_engine.confirmed_items(ta_data, market="fut")',
    "_vortex_confirm_pickup_audit_1822b2(",
    "pickup audit snapshot | fut_items=",
    "legacy engine compare | engine_confirmed=",
]

missing = [x for x in required if x not in text]
if missing:
    raise SystemExit(f"missing expected strategy pickup audit markers: {missing}")

forbidden = [
    "confirmed_fut_items = confirmation_engine.confirmed_futures_items(watch_engine, ta_data)",
    "pickup mismatch | reason=watch_engine_would_but_confirmation_engine_returned_none",
    "real ConfirmationEngine pickup path",
]

present = [x for x in forbidden if x in text]
if present:
    raise SystemExit(f"forbidden stale strategy pickup markers still present: {present}")

print("OK: smoke_strategy_pickup_audit")
