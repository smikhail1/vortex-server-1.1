import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_main_contains_real_confirmation_engine_pickup_audit():
    text = Path("main.py").read_text(encoding="utf-8")
    assert "_vortex_confirm_pickup_audit_1822b2" in text
    assert "confirmed_fut_items = confirmation_engine.confirmed_futures_items(watch_engine, ta_data)" in text
    assert "for item in confirmed_fut_items:" in text
    assert "pickup mismatch | reason=watch_engine_would_but_confirmation_engine_returned_none" in text


def test_patch_does_not_switch_to_direct_watch_engine_pickup():
    text = Path("main.py").read_text(encoding="utf-8")
    assert "for item in watch_engine.confirmed_items(ta_data, market=\"fut\")" not in text
    assert "for item in watch_engine.confirmed_items(ta_data, market='fut')" not in text


if __name__ == "__main__":
    test_main_contains_real_confirmation_engine_pickup_audit()
    test_patch_does_not_switch_to_direct_watch_engine_pickup()
    print("OK: smoke_strategy_pickup_audit")
