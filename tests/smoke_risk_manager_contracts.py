from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from risk_manager import RiskManager


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_open_close_cooldown_and_day_limit():
    r = RiskManager(
        futures_symbol_cooldown_sec=60,
        spot_symbol_cooldown_sec=30,
        max_trades_per_symbol_per_day=2,
        persistence_enabled=False,
        daily_loss_limit_usdt=-999,
    )

    ok, reason = r.can_open("BTCUSDT", "fut")
    assert_true(ok, f"first can_open should pass: {reason}")

    r.register_open("BTCUSDT", "fut")
    ok, reason = r.can_open("BTCUSDT", "fut")
    assert_true(not ok and "cooldown" in reason.lower(), f"open cooldown should block: {reason}")

    r.last_open_ts[("BTCUSDT", "fut")] = time.time() - 120
    ok, reason = r.can_open("BTCUSDT", "fut")
    assert_true(ok, f"cooldown elapsed should pass: {reason}")

    r.register_close("BTCUSDT", "fut", pnl=0.05, reason="TP2")
    ok, reason = r.can_open("BTCUSDT", "fut")
    assert_true(not ok and "cooldown" in reason.lower(), f"close cooldown should block: {reason}")

    r.last_close_ts[("BTCUSDT", "fut")] = time.time() - 120
    ok, reason = r.can_open("BTCUSDT", "fut")
    assert_true(ok, f"close cooldown elapsed should pass: {reason}")

    r.register_open("BTCUSDT", "fut")
    ok, reason = r.can_open("BTCUSDT", "fut")
    assert_true(not ok and "daily symbol trade limit" in reason.lower(), f"daily limit should block: {reason}")

    status = r.get_status()
    assert_true("trades_per_day" in status, "status must expose trades_per_day")
    assert_true(status.get("max_trades_per_symbol_per_day") == 2, "status must expose max trade limit")


def test_loss_streak_cooldown():
    r = RiskManager(
        futures_symbol_cooldown_sec=0,
        spot_symbol_cooldown_sec=0,
        max_trades_per_symbol_per_day=99,
        loss_streak_limit=2,
        loss_streak_cooldown_sec=120,
        persistence_enabled=False,
        daily_loss_limit_usdt=-999,
    )

    r.register_close("ETHUSDT", "fut", pnl=-0.1, reason="SL")
    ok, reason = r.can_open("ETHUSDT", "fut")
    assert_true(ok, f"one loss should not block by streak: {reason}")

    r.register_close("ETHUSDT", "fut", pnl=-0.1, reason="SL")
    ok, reason = r.can_open("ETHUSDT", "fut")
    assert_true(not ok and "loss streak" in reason.lower(), f"two losses should block by streak: {reason}")

    r.last_loss_ts[("ETHUSDT", "fut")] = time.time() - 180
    ok, reason = r.can_open("ETHUSDT", "fut")
    assert_true(ok, f"loss streak cooldown elapsed should pass: {reason}")

    r.register_close("ETHUSDT", "fut", pnl=0.1, reason="TP2")
    assert_true(r.consecutive_losses[("ETHUSDT", "fut")] == 0, "winning close must reset loss streak")


def test_spot_cooldown_independent_from_futures():
    r = RiskManager(
        futures_symbol_cooldown_sec=60,
        spot_symbol_cooldown_sec=60,
        max_trades_per_symbol_per_day=10,
        persistence_enabled=False,
        daily_loss_limit_usdt=-999,
    )

    r.register_open("SOLUSDT", "spot")
    ok_spot, reason_spot = r.can_open("SOLUSDT", "spot")
    ok_fut, reason_fut = r.can_open("SOLUSDT", "fut")

    assert_true(not ok_spot and "cooldown" in reason_spot.lower(), f"spot cooldown should block spot: {reason_spot}")
    assert_true(ok_fut, f"spot cooldown must not block futures: {reason_fut}")


def main():
    test_open_close_cooldown_and_day_limit()
    test_loss_streak_cooldown()
    test_spot_cooldown_independent_from_futures()
    print("OK: smoke_risk_manager_contracts")


if __name__ == "__main__":
    main()
