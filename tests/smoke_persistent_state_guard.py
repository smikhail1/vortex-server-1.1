import json
import os
import tempfile
from pathlib import Path

from persistent_state_guard import evaluate_futures_pre_open_guard, get_state_open_futures


class DummyRouter:
    def get_all_futures_positions(self):
        return {}

    def get_futures_position(self):
        return None


def test_blocks_when_state_has_fut_and_runtime_empty():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "trades_state.json"
        path.write_text(json.dumps({
            "open": {
                "VIRTUALUSDT::FUT": {
                    "symbol": "VIRTUALUSDT",
                    "market": "FUT",
                    "side": "LONG",
                    "entry": 0.76950768,
                    "open_time": 1779606008.0,
                }
            }
        }), encoding="utf-8")

        guard = evaluate_futures_pre_open_guard(
            symbol="RENDERUSDT",
            side="LONG",
            router=DummyRouter(),
            state_path=str(path),
        )

        assert guard["allow"] is False
        assert guard["code"] == "STATE_RUNTIME_MISMATCH"
        assert guard["state_fut_count"] == 1
        assert guard["runtime_fut_count"] == 0


def test_allows_when_state_has_no_fut():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "trades_state.json"
        path.write_text(json.dumps({"open": {}}), encoding="utf-8")

        guard = evaluate_futures_pre_open_guard(
            symbol="RENDERUSDT",
            side="LONG",
            router=DummyRouter(),
            state_path=str(path),
        )

        assert guard["allow"] is True
        assert guard["code"] == "OK"


def test_extracts_state_futures_only():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "trades_state.json"
        path.write_text(json.dumps({
            "open": {
                "BTCUSDT::SPOT": {"symbol": "BTCUSDT", "market": "SPOT"},
                "ETHUSDT::FUT": {"symbol": "ETHUSDT", "market": "FUT"},
            }
        }), encoding="utf-8")

        xs = get_state_open_futures(str(path))
        assert len(xs) == 1
        assert xs[0]["symbol"] == "ETHUSDT"


if __name__ == "__main__":
    test_blocks_when_state_has_fut_and_runtime_empty()
    test_allows_when_state_has_no_fut()
    test_extracts_state_futures_only()
    print("OK: smoke_persistent_state_guard")
