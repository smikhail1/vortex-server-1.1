from dataclasses import dataclass

from position_state_engine import PositionStateEngine


@dataclass
class DummyFuturesPosition:
    symbol: str = "BTCUSDT"
    side: str = "short"
    qty: float = 0.01
    entry: float = 78000.0
    mark_price: float = 78000.0
    tp: float = 77500.0
    tp2: float = 77000.0
    sl: float = 78200.0
    trail_sl: float = 78200.0
    pnl: float = 0.0
    pnl_net: float = 0.0
    max_pnl_net: float = 0.0
    open_time: float = 1000000.0
    setup_type: str = "manual_test"
    args_text: str = "test"
    tp1_hit: bool = False
    breakeven: bool = False


def main():
    engine = PositionStateEngine(logger=None)
    pos = DummyFuturesPosition()

    opened = engine.open_from_position(pos, "FUT")
    assert opened is not None
    assert opened["state"] == "OPENED"

    pos.tp1_hit = True
    pos.breakeven = True
    pos.trail_sl = 77700.0
    pos.sl = 77700.0
    pos.pnl = 3.0
    pos.pnl_net = 2.8
    pos.max_pnl_net = 2.8
    updated = engine.update_from_position(pos, "FUT", current_price=77400.0)
    assert updated is not None
    assert updated["state"] in {"BREAKEVEN_ARMED", "TRAILING_ACTIVE", "TP1_HIT"}

    closed = engine.close("BTCUSDT", "FUT", {"reason": "TP2", "exit_price": 77000.0, "pnl": 10.0, "pnl_net": 9.5})
    assert closed is not None
    assert closed["state"] == "CLOSED"
    assert closed["close_reason"] == "TP2"

    snap = engine.snapshot()
    assert snap["counts"]["open"] == 0
    assert snap["counts"]["closed_recent"] >= 1
    print("OK: position_state_engine smoke test")


if __name__ == "__main__":
    main()
