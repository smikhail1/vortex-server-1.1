#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# TradeManager imports aiohttp for the futures live-price helper. This smoke
# exercises PAPER Spot only, so keep the test runnable on a clean system Python.
sys.modules.setdefault("aiohttp", types.SimpleNamespace())


class FakeState:
    def __init__(self, price):
        self.price = price

    async def get_dashboard_state(self):
        return {"market": {"prices": {"TESTUSDT": self.price}, "ta_data": {}}}

    async def add_sys_log(self, *_args, **_kwargs):
        return None


class FakeRisk:
    def __init__(self):
        self.closed = []
        self.partial = []

    def register_close(self, symbol, market, pnl, reason="CLOSE"):
        self.closed.append((symbol, market, pnl, reason))

    def register_realized_pnl(self, pnl, reason="PARTIAL"):
        self.partial.append((pnl, reason))


class FakeLogger:
    def __init__(self):
        self.rows = []

    def log_trade(self, **kwargs):
        self.rows.append(kwargs)


class FakePositionState:
    def __init__(self):
        self.closes = []
        self.events = []

    def update_from_position(self, *_args, **_kwargs):
        return None

    def close(self, symbol, market, data):
        self.closes.append((symbol, market, data))

    def record_event(self, event, data):
        self.events.append((event, data))


class FakeRouter:
    def __init__(self, engine):
        self.paper_spot = engine

    def get_all_spot_positions(self):
        return self.paper_spot.get_all_positions()

    def get_spot_position(self, symbol):
        return self.paper_spot.get_position(symbol)

    def check_spot_position(self, symbol, price):
        return self.paper_spot.check_stops(symbol, price)


def assert_close_payload():
    from paper_spot import PaperSpot

    engine = PaperSpot(start_balance=100.0, state_path="_runtime/close_payload.json")
    opened = engine.open_position("TESTUSDT", qty=0.1, price=100.0, tp=110.0, atr=2.0)
    assert opened["code"] == "00000"
    pos = engine.get_position("TESTUSDT")
    pos.open_time = time.time() - 12
    result = engine.close_position("TESTUSDT", current_price=95.0, reason="SL")
    data = result["data"]
    assert data["closed"] is True
    assert data["market"] == "SPOT"
    assert data["pnl_net"] == data["pnl"]
    assert data["pnl_net"] < 0
    assert data["hold_sec"] >= 11
    assert abs(engine.get_balance() - (100.0 + data["pnl_net"])) < 1e-6


async def assert_trade_manager_full_close():
    from paper_spot import PaperSpot
    from trade_manager import TradeManager

    engine = PaperSpot(start_balance=100.0, state_path="_runtime/manager_full.json")
    engine.open_position("TESTUSDT", qty=0.1, price=100.0, tp=110.0, atr=2.0)
    engine.get_position("TESTUSDT").open_time = time.time() - 10
    risk, logger, states = FakeRisk(), FakeLogger(), FakePositionState()
    manager = TradeManager(position_state_engine=states)
    await manager.process_spot(FakeState(95.0), FakeRouter(engine), logger, risk)
    assert len(risk.closed) == 1
    assert risk.closed[0][2] < 0
    assert len(states.closes) == 1
    assert states.closes[0][2]["pnl_net"] == risk.closed[0][2]
    assert logger.rows[0]["pnl_net"] == risk.closed[0][2]
    assert logger.rows[0]["hold_sec"] >= 9


async def assert_trade_manager_partial_close():
    from paper_spot import PaperSpot
    from trade_manager import TradeManager

    engine = PaperSpot(start_balance=100.0, state_path="_runtime/manager_partial.json")
    engine.open_position("TESTUSDT", qty=0.1, price=100.0, tp=101.0, atr=2.0)
    risk, logger, states = FakeRisk(), FakeLogger(), FakePositionState()
    manager = TradeManager(position_state_engine=states)
    await manager.process_spot(FakeState(102.0), FakeRouter(engine), logger, risk)
    assert len(risk.partial) == 1
    assert risk.partial[0][0] > 0
    assert len(risk.closed) == 0
    assert len(states.events) == 1
    assert states.events[0][1]["realized_pnl_net"] == risk.partial[0][0]
    assert logger.rows[0]["reason"] == "TP1"
    assert logger.rows[0]["pnl_net"] == risk.partial[0][0]
    assert engine.get_position("TESTUSDT") is not None


def assert_state_reload_and_close():
    from paper_spot import PaperSpot
    from position_state_engine import PositionStateEngine

    engine = PaperSpot(start_balance=100.0, state_path="_runtime/state_reload_engine.json")
    engine.open_position("TESTUSDT", qty=0.1, price=100.0, tp=110.0, atr=2.0)
    pos = engine.get_position("TESTUSDT")
    pos.open_time = time.time() - 8
    state = PositionStateEngine()
    state.open_from_position(pos, "SPOT")
    result = engine.close_position("TESTUSDT", current_price=95.0, reason="SL")
    state.close("TESTUSDT", "SPOT", result["data"])
    saved = json.loads(Path("trades_state.json").read_text(encoding="utf-8"))
    assert saved["closed"][0]["pnl_net"] == result["data"]["pnl_net"]
    assert saved["closed"][0]["hold_sec"] >= 7
    restored = PositionStateEngine()
    snap = restored.snapshot()
    assert len(snap["closed_recent"]) == 1
    assert snap["closed_recent"][0]["pnl_net"] == result["data"]["pnl_net"]


def assert_paper_spot_restart_persistence():
    from paper_spot import PaperSpot

    path = "_runtime/paper_spot_restart.json"
    engine = PaperSpot(start_balance=100.0, state_path=path)
    opened = engine.open_position("TESTUSDT", qty=0.1, price=100.0, tp=110.0, atr=2.0)
    assert opened["code"] == "00000"
    balance_after_open = engine.get_balance()
    restored = PaperSpot(start_balance=999.0, state_path=path)
    assert restored.get_balance() == balance_after_open
    assert restored.get_position("TESTUSDT") is not None
    result = restored.close_position("TESTUSDT", current_price=105.0, reason="MANUAL")
    balance_after_close = restored.get_balance()
    restored_again = PaperSpot(start_balance=999.0, state_path=path)
    assert restored_again.get_position("TESTUSDT") is None
    assert restored_again.get_balance() == balance_after_close
    assert abs(balance_after_close - (100.0 + result["data"]["pnl_net"])) < 1e-6


def assert_static_contracts():
    paper = Path("paper_spot.py").read_text(encoding="utf-8")
    state = Path("position_state_engine.py").read_text(encoding="utf-8")
    manager = Path("trade_manager.py").read_text(encoding="utf-8")
    risk = Path("risk_manager.py").read_text(encoding="utf-8")
    api = Path("api_server.py").read_text(encoding="utf-8")
    assert '"pnl_net": round(net_pnl, 8)' in paper
    assert '"hold_sec": hold_sec' in paper
    assert '"schema": "vortex.paper_spot_state.v1"' in paper
    assert "self._load_state()" in paper
    assert "self._save_state()" in paper
    assert "for raw in data.get(\"closed\", []) or []" in state
    assert "def register_realized_pnl" in risk
    assert "realized_partial = safe_float" in manager
    assert "last_realized_at >= today_start_ts" in api


def main():
    os.chdir(REPO_ROOT)
    assert_static_contracts()
    with tempfile.TemporaryDirectory(prefix="vortex_spot_pnl_") as tmp:
        os.chdir(tmp)
        assert_close_payload()
        asyncio.run(assert_trade_manager_full_close())
        asyncio.run(assert_trade_manager_partial_close())
        assert_state_reload_and_close()
        assert_paper_spot_restart_persistence()
    print("OK: smoke_spot_pnl_accounting")


if __name__ == "__main__":
    main()
