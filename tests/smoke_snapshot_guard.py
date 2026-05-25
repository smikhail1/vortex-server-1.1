import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from snapshot_guard import is_valid_latest_snapshot, should_write_latest_snapshot


def test_guard_keeps_valid_latest_when_new_is_empty():
    with tempfile.TemporaryDirectory() as td:
        latest = Path(td) / "latest.json"

        old = {
            "summary": {
                "symbols_count": 60,
                "ta_symbols_count": 60,
                "analyzed_count": 60,
            },
            "symbols": [{"symbol": "AAAUSDT"}],
        }
        latest.write_text(json.dumps(old), encoding="utf-8")

        new = {
            "summary": {
                "symbols_count": 0,
                "ta_symbols_count": 0,
                "prices_count": 62,
            },
            "symbols": [],
        }

        assert is_valid_latest_snapshot(old) is True
        assert is_valid_latest_snapshot(new) is False

        decision = should_write_latest_snapshot(latest, new)
        assert decision["write_latest"] is False
        assert decision["action"] == "SKIP_LATEST_KEEP_PREVIOUS"


def test_guard_writes_valid_snapshot():
    with tempfile.TemporaryDirectory() as td:
        latest = Path(td) / "latest.json"
        new = {
            "summary": {
                "symbols_count": 61,
                "ta_symbols_count": 61,
                "analyzed_count": 61,
            },
            "symbols": [{"symbol": "AAAUSDT"}],
        }

        decision = should_write_latest_snapshot(latest, new)
        assert decision["write_latest"] is True
        assert decision["action"] == "WRITE_LATEST_VALID"


def test_context_fusion_nested_counts():
    with tempfile.TemporaryDirectory() as td:
        latest = Path(td) / "context_latest.json"
        old = {
            "summary": {
                "symbols_count": 66,
                "strategy_summary": {"ta_symbols_count": 60, "analyzed_count": 60},
                "setup_summary": {"ta_symbols_count": 60},
            },
            "symbols": [{"symbol": "AAAUSDT"}],
        }
        latest.write_text(json.dumps(old), encoding="utf-8")

        new = {
            "summary": {
                "symbols_count": 0,
                "strategy_summary": {"ta_symbols_count": 0, "analyzed_count": 0},
                "setup_summary": {"ta_symbols_count": 0},
            },
            "symbols": [],
        }

        assert is_valid_latest_snapshot(old) is True
        assert is_valid_latest_snapshot(new) is False
        decision = should_write_latest_snapshot(latest, new)
        assert decision["write_latest"] is False


if __name__ == "__main__":
    test_guard_keeps_valid_latest_when_new_is_empty()
    test_guard_writes_valid_snapshot()
    test_context_fusion_nested_counts()
    print("OK: smoke_snapshot_guard")
