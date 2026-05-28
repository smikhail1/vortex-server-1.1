import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from watch_engine import WatchEngine, WatchItem


def make_item(side="SHORT", price=99.0, trigger=100.0, atr=1.0, confirmed=False, status="watch"):
    return WatchItem(
        symbol="TESTUSDT",
        market="fut",
        side=side,
        setup_type="momentum_short" if side == "SHORT" else "momentum_long",
        score=10,
        status=status,
        waiting_for="momentum trigger breakdown" if side == "SHORT" else "momentum trigger breakout",
        trigger_price=trigger,
        invalidation_price=105.0 if side == "SHORT" else 95.0,
        created_at=1.0,
        updated_at=1.0,
        expires_at=9999999999.0,
        price=price,
        atr=atr,
        args_text="momentum negative momentum | score=10 | momentum_confirmed",
        confirmed=confirmed,
        confirmation_reason="",
    )


def test_short_would_confirm_after_buffer_and_ema():
    w = WatchEngine()
    item = make_item("SHORT", price=99.0, trigger=100.0, atr=1.0)
    audit = w.evaluate_confirmation_state(item, {"price": 99.0, "atr": 1.0, "ema20": 110.0, "market_regime": "unknown"})
    assert audit["trigger_crossed"] is True
    assert audit["price_ok"] is True
    assert audit["ema_ok"] is True
    assert audit["regime_blocked"] is False
    assert audit["would_confirm_now"] is True
    assert audit["reason"] == "would_confirm_now"


def test_short_crossed_but_waiting_buffer():
    w = WatchEngine()
    item = make_item("SHORT", price=99.9, trigger=100.0, atr=1.0)
    audit = w.evaluate_confirmation_state(item, {"price": 99.9, "atr": 1.0, "ema20": 110.0, "market_regime": "unknown"})
    assert audit["trigger_crossed"] is True
    assert audit["price_ok"] is False
    assert audit["would_confirm_now"] is False
    assert audit["reason"] == "waiting_buffer"


def test_dead_regime_blocks_non_override():
    w = WatchEngine()
    item = make_item("SHORT", price=99.0, trigger=100.0, atr=1.0)
    audit = w.evaluate_confirmation_state(item, {"price": 99.0, "atr": 1.0, "ema20": 110.0, "market_regime": "dead"})
    assert audit["regime_blocked"] is True
    assert audit["would_confirm_now"] is False
    assert audit["reason"] == "regime_blocked"


def test_snapshot_exposes_confirm_check_and_is_readonly():
    w = WatchEngine()
    item = make_item("SHORT", price=99.9, trigger=100.0, atr=1.0)
    key = w._key("TESTUSDT", "fut", "SHORT")
    w._items[key] = item
    rows = w.snapshot(ta_data={"TESTUSDT": {"price": 99.9, "atr": 1.0, "ema20": 110.0, "market_regime": "unknown"}})
    row = rows[0]
    assert row["snapshot_readonly"] is True
    assert isinstance(row["confirm_check"], dict)
    assert row["confirm_check"]["reason"] == "waiting_buffer"
    assert w._items[key].status == "watch"
    assert w._items[key].confirmed is False


if __name__ == "__main__":
    test_short_would_confirm_after_buffer_and_ema()
    test_short_crossed_but_waiting_buffer()
    test_dead_regime_blocks_non_override()
    test_snapshot_exposes_confirm_check_and_is_readonly()
    print("OK: smoke_confirmation_audit")
