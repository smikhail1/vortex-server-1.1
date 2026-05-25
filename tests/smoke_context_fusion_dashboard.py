import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api_server import APIServer


class DummyState:
    async def get_dashboard_state(self):
        return {
            "positions": {"fut": {}, "spot": {}},
            "account": {"balances": {"spot": 100.0, "fut": 100.0}},
            "market": {"prices": {}, "ta_data": {}},
        }

    async def get_health_state(self, mode="PAPER"):
        return {"status": "online", "mode": mode}


def test_context_fusion_missing_file_fallback():
    with tempfile.TemporaryDirectory() as td:
        old = Path.cwd()
        try:
            import os
            os.chdir(td)
            api = APIServer(DummyState())
            payload = api._read_context_fusion_payload()
            assert payload["available"] is False
            assert payload["summary"] == {}
            assert payload["symbols"] == []
            assert payload["error"] == "missing_context_fusion_latest"
        finally:
            os.chdir(old)


def test_context_fusion_valid_file():
    with tempfile.TemporaryDirectory() as td:
        old = Path.cwd()
        try:
            import os
            os.chdir(td)
            Path("_runtime").mkdir()
            Path("_runtime/context_fusion_latest.json").write_text(
                json.dumps({
                    "schema": "vortex.context_fusion.v1",
                    "schema_version": "1.8.21k-c",
                    "ts": 123.0,
                    "summary": {"symbols_count": 1, "final_view_counts": {"WATCH_ONLY": 1}},
                    "symbols": [{"symbol": "BTCUSDT", "final": {"view": "WATCH_ONLY"}}],
                    "important": [{"symbol": "BTCUSDT"}],
                }),
                encoding="utf-8",
            )

            api = APIServer(DummyState())
            payload = api._read_context_fusion_payload()
            assert payload["available"] is True
            assert payload["snapshot_schema_version"] == "1.8.21k-c"
            assert payload["summary"]["symbols_count"] == 1
            assert payload["symbols"][0]["symbol"] == "BTCUSDT"
            assert payload["important"][0]["symbol"] == "BTCUSDT"
            assert payload["error"] is None
        finally:
            os.chdir(old)


def test_context_fusion_invalid_json_fallback():
    with tempfile.TemporaryDirectory() as td:
        old = Path.cwd()
        try:
            import os
            os.chdir(td)
            Path("_runtime").mkdir()
            Path("_runtime/context_fusion_latest.json").write_text("{bad json", encoding="utf-8")

            api = APIServer(DummyState())
            payload = api._read_context_fusion_payload()
            assert payload["available"] is False
            assert payload["summary"] == {}
            assert payload["symbols"] == []
            assert str(payload["error"]).startswith("read_failed:")
        finally:
            os.chdir(old)


if __name__ == "__main__":
    test_context_fusion_missing_file_fallback()
    test_context_fusion_valid_file()
    test_context_fusion_invalid_json_fallback()
    print("OK: smoke_context_fusion_dashboard")
