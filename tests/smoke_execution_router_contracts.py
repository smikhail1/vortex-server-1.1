from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution_router import ExecutionRouter


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    router = ExecutionRouter(mode="PAPER")

    res = router.manual_open_futures(
        symbol="BTCUSDT",
        side="LONG",
        price=100.0,
        atr=2.0,
        margin_usdt=10.0,
        leverage=2.0,
        setup_type="smoke_router",
    )
    assert_true(res.get("code") == "00000", f"manual_open_futures failed: {res}")

    check = router.check_futures_position(current_price=101.0)
    assert_true(check is None or isinstance(check, dict), f"check_futures_position keyword failed: {check}")

    close_kw = router.close_futures_position(current_price=101.0, reason="MANUAL")
    assert_true(close_kw is None or close_kw.get("code") == "00000", f"close_futures_position keyword failed: {close_kw}")

    res = router.manual_open_futures(
        symbol="ETHUSDT",
        side="SHORT",
        price=100.0,
        atr=2.0,
        margin_usdt=10.0,
        leverage=2.0,
        setup_type="smoke_router",
    )
    assert_true(res.get("code") == "00000", f"manual_open_futures second failed: {res}")
    close_positional = router.close_futures_position(99.0, "MANUAL")
    assert_true(close_positional is None or close_positional.get("code") == "00000", f"close_futures_position positional failed: {close_positional}")

    res = router.manual_open_spot(
        symbol="ETHUSDT",
        price=100.0,
        atr=2.0,
        order_usdt=10.0,
        setup_type="smoke_router",
    )
    assert_true(res.get("code") == "00000", f"manual_open_spot failed: {res}")

    check = router.check_spot_position("ETHUSDT", 101.0)
    assert_true(check is None or isinstance(check, dict), f"check_spot_position positional failed: {check}")

    all_closed = router.manual_close_all_spot(prices={"ETHUSDT": 101.0}, reason="MANUAL")
    assert_true(isinstance(all_closed, list), "manual_close_all_spot must return list")

    router2 = ExecutionRouter(mode="PAPER")
    router2.set_fut_mode("REAL")
    blocked = router2.manual_open_futures(symbol="BTCUSDT", side="LONG", price=100, atr=1)
    assert_true(blocked.get("code") == "ERROR", f"non-PAPER futures open must be blocked: {blocked}")
    router2.set_spot_mode("REAL")
    blocked = router2.manual_open_spot(symbol="BTCUSDT", price=100, atr=1)
    assert_true(blocked.get("code") == "ERROR", f"non-PAPER spot open must be blocked: {blocked}")

    print("OK: smoke_execution_router_contracts")


if __name__ == "__main__":
    main()
