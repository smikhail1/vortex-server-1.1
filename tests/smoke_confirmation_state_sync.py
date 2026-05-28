
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from watch_engine import WatchEngine, WatchItem


def make_item(side, price, trigger, args="momentum negative momentum | score=10 | momentum_confirmed"):
    return WatchItem(
        symbol="TESTUSDT",
        market="fut",
        side=side,
        setup_type="momentum_short" if side == "SHORT" else "momentum_long",
        score=10,
        status="watch",
        waiting_for="momentum trigger breakdown" if side == "SHORT" else "momentum trigger breakout",
        trigger_price=trigger,
        invalidation_price=trigger * 1.02 if side == "SHORT" else trigger * 0.98,
        created_at=1.0,
        updated_at=1.0,
        expires_at=9999999999.0,
        price=price,
        atr=1.0,
        args_text=args,
        confirmed=False,
        confirmation_reason="",
    )


def test_public_fields_short_crossed():
    w = WatchEngine()
    item = make_item("SHORT", price=99.0, trigger=100.0)
    out = w.to_public(item)
    assert out["momentum_confirmed"] is True
    assert out["trigger_crossed"] is True
    assert out["entry_confirmed"] is False
    assert out["confirmation_stage"] == "trigger_crossed_not_ready"


def test_public_fields_long_not_crossed():
    w = WatchEngine()
    item = make_item("LONG", price=99.0, trigger=100.0, args="momentum positive momentum | score=10 | momentum_confirmed")
    out = w.to_public(item)
    assert out["momentum_confirmed"] is True
    assert out["trigger_crossed"] is False
    assert out["entry_confirmed"] is False
    assert out["confirmation_stage"] == "momentum_confirmed_wait_trigger"


def test_snapshot_syncs_ready_with_ta():
    w = WatchEngine()
    item = make_item("SHORT", price=101.0, trigger=100.0)
    w._items[w._key("TESTUSDT", "fut", "SHORT")] = item
    rows = w.snapshot(ta_data={"TESTUSDT": {"price": 98.0, "atr": 1.0, "ema20": 110.0, "market_regime": "allow_all"}})
    assert rows
    row = rows[0]
    assert row["trigger_crossed"] is True
    assert row["confirmed"] is True
    assert row["entry_confirmed"] is True
    assert row["status"] == "ready"
    assert row["waiting_for"] == "entry safety / policy check"


if __name__ == "__main__":
    test_public_fields_short_crossed()
    test_public_fields_long_not_crossed()
    test_snapshot_syncs_ready_with_ta()
    print("OK: smoke_confirmation_state_sync")
