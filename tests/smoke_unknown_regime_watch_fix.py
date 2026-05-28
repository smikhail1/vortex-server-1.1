
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from watch_engine import WatchEngine, WatchItem


def make_item(side="SHORT", price=100.0, trigger=99.0):
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


def test_unknown_regime_does_not_block_before_trigger():
    w = WatchEngine()
    item = make_item(side="SHORT", price=100.0, trigger=99.0)
    result = w.check_confirmation_for_item(
        item,
        {"price": 100.0, "atr": 1.0, "ema20": 110.0, "market_regime": "unknown"},
    )
    assert result is None
    assert item.status == "watch"
    assert item.confirmed is False
    assert "regime data missing" in item.confirmation_reason


def test_unknown_regime_can_confirm_if_trigger_crossed():
    w = WatchEngine()
    item = make_item(side="SHORT", price=100.0, trigger=99.0)
    result = w.check_confirmation_for_item(
        item,
        {"price": 97.5, "atr": 1.0, "ema20": 110.0, "market_regime": "unknown"},
    )
    assert result is not None
    assert item.status == "ready"
    assert item.confirmed is True


def test_dead_regime_still_blocks():
    w = WatchEngine()
    item = make_item(side="SHORT", price=100.0, trigger=99.0)
    result = w.check_confirmation_for_item(
        item,
        {"price": 97.5, "atr": 1.0, "ema20": 110.0, "market_regime": "dead"},
    )
    assert result is None
    assert item.status == "blocked"
    assert "bad regime during watch:dead" in item.confirmation_reason


if __name__ == "__main__":
    test_unknown_regime_does_not_block_before_trigger()
    test_unknown_regime_can_confirm_if_trigger_crossed()
    test_dead_regime_still_blocks()
    print("OK: smoke_unknown_regime_watch_fix")
