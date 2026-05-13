import asyncio

from execution_router import ExecutionRouter
from risk_manager import RiskManager
from trade_manager import TradeManager


class DummyState:
    def __init__(self, prices):
        self.prices = prices
        self.logs = []

    async def get_dashboard_state(self):
        return {
            "market": {
                "prices": self.prices,
            }
        }

    async def add_sys_log(self, tag, message):
        self.logs.append((tag, message))


class DummyTradeLogger:
    def __init__(self):
        self.records = []

    def log_trade(self, *args, **kwargs):
        self.records.append((args, kwargs))


class DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def scenario_futures_trade_manager_close() -> None:
    router = ExecutionRouter(mode="PAPER")
    risk = RiskManager()
    tm = TradeManager(logger=DummyLogger())
    trade_logger = DummyTradeLogger()

    open_result = router.manual_open_futures(
        symbol="BTCUSDT",
        side="LONG",
        price=70000,
        atr=400,
        margin_usdt=20,
        leverage=3,
        tp_mult=2.5,
        sl_mult=1.3,
        setup_type="tm_fut_test",
        args_text="trade manager futures test",
    )
    assert_true(open_result.get("code") == "00000", f"futures open failed: {open_result}")

    state = DummyState(prices={"BTCUSDT": 72050})
    await tm.loop(state=state, router=router, trade_logger=trade_logger, risk_manager=risk)

    # либо TP1 event, либо close, в зависимости от уровня/цены
    assert_true(len(state.logs) > 0, "trade manager should emit futures logs")
    print("OK: scenario_futures_trade_manager_close")


async def scenario_spot_trade_manager_close() -> None:
    router = ExecutionRouter(mode="PAPER")
    risk = RiskManager()
    tm = TradeManager(logger=DummyLogger())
    trade_logger = DummyTradeLogger()

    open_result = router.manual_open_spot(
        symbol="ETHUSDT",
        price=2000,
        atr=40,
        order_usdt=20,
        tp_mult=3.0,
        setup_type="tm_spot_test",
        args_text="trade manager spot test",
    )
    assert_true(open_result.get("code") == "00000", f"spot open failed: {open_result}")

    state = DummyState(prices={"ETHUSDT": 2150})
    await tm.loop(state=state, router=router, trade_logger=trade_logger, risk_manager=risk)

    assert_true(len(state.logs) > 0, "trade manager should emit spot logs")
    print("OK: scenario_spot_trade_manager_close")


async def run_all() -> None:
    await scenario_futures_trade_manager_close()
    await scenario_spot_trade_manager_close()
    print("ALL TRADE MANAGER TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(run_all())