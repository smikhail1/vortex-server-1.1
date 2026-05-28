
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from watch_engine import WatchEngine, WatchItem


def make_item(side="SHORT", price=101.0, trigger=100.0):
    return WatchItem(
        symbol="TESTUSDT",
        market="fut",
        side=side,
        setup_type="momentum_short" if side == "SHORT" else "momentum_long",
        score=10,
        status="watch",
        waiting_for="momentum trigger breakdown" if side == "SHORT" else "momentum trigger breakout",
        trigger_price=trigger,
        invalidation_price=105.0 if side == "SHORT" else 95.0,
        created_at=1.0,
        updated_at=1.0,
        expires_at=9999999999.0,
        price=price,
        atr=1.0,
        args_text="momentum negative momentum | score=10 | momentum_confirmed",
        confirmed=False,
        confirmation_reason="",
    )


def test_snapshot_does_not_mutate_to_ready():
    w = WatchEngine()
    item = make_item(side="SHORT", price=101.0, trigger=100.0)
    w._items[w._key("TESTUSDT", "fut", "SHORT")] = item

    rows = w.snapshot(ta_data={"TESTUSDT": {"price": 98.0, "atr": 1.0, "ema20": 110.0, "market_regime": "unknown"}})
    assert rows
    row = rows[0]
    assert row["trigger_crossed"] is True
    assert row["snapshot_readonly"] is True

    # Critical: snapshot is UI/API only. It must not mutate decision state.
    assert item.status == "watch"
    assert item.confirmed is False
    assert row["entry_confirmed"] is False


def test_confirmed_items_still_mutates_and_returns_ready():
    w = WatchEngine()
    item = make_item(side="SHORT", price=101.0, trigger=100.0)
    w._items[w._key("TESTUSDT", "fut", "SHORT")] = item

    rows = w.confirmed_items(
        {"TESTUSDT": {"price": 98.0, "atr": 1.0, "ema20": 110.0, "market_regime": "unknown"}},
        market="fut",
    )
    assert rows
    assert item.status == "ready"
    assert item.confirmed is True


def test_stale_ready_not_presented_as_entry_confirmed_if_live_price_uncrossed():
    w = WatchEngine()
    item = make_item(side="SHORT", price=98.0, trigger=100.0)
    item.status = "ready"
    item.confirmed = True
    w._items[w._key("TESTUSDT", "fut", "SHORT")] = item

    rows = w.snapshot(ta_data={"TESTUSDT": {"price": 101.0, "atr": 1.0, "ema20": 110.0, "market_regime": "unknown"}})
    row = rows[0]
    assert row["trigger_crossed"] is False
    assert row["entry_confirmed"] is False
    assert row["confirmation_stage"] == "stale_ready_wait_reconfirm"


if __name__ == "__main__":
    test_snapshot_does_not_mutate_to_ready()
    test_confirmed_items_still_mutates_and_returns_ready()
    test_stale_ready_not_presented_as_entry_confirmed_if_live_price_uncrossed()
    print("OK: smoke_readonly_watchlist_snapshot")
