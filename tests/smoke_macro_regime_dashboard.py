from pathlib import Path
import json
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api_server import APIServer


def test_macro_regime_reader_missing_is_safe():
    with tempfile.TemporaryDirectory() as td:
        old = os.getcwd()
        os.chdir(td)
        try:
            api = object.__new__(APIServer)
            payload = APIServer._read_macro_regime_payload(api)
            assert payload["available"] is False
            assert payload["regime"] is None
            assert payload["error"] == "missing_macro_regime_latest"
        finally:
            os.chdir(old)


def test_macro_regime_reader_valid_snapshot():
    with tempfile.TemporaryDirectory() as td:
        old = os.getcwd()
        os.chdir(td)
        try:
            Path("_runtime").mkdir()
            Path("_runtime/macro_regime_latest.json").write_text(json.dumps({
                "schema": "vortex.macro_regime.v1",
                "schema_version": "1.8.21l-f-r2",
                "ts": 123.0,
                "regime": "mild_risk_off",
                "confidence": 34,
                "recommendation": {
                    "long_permission": "reduced",
                    "short_permission": "selective_plus",
                    "risk_mode": "defensive",
                },
                "reasons": ["heatmap_bearish=mild_bearish"],
                "warnings": ["ichimoku_mixed_breadth"],
                "heatmap": {"bias": "mild_bearish"},
                "ichimoku_breadth": {"bias": "mixed_breadth"},
                "futures_pressure": {"pressure": "neutral_futures"},
                "vortex_pressure": {"pressure": "candidate_pressure"},
            }), encoding="utf-8")

            api = object.__new__(APIServer)
            payload = APIServer._read_macro_regime_payload(api)

            assert payload["available"] is True
            assert payload["schema_version"] == "1.8.21l-h"
            assert payload["snapshot_schema_version"] == "1.8.21l-f-r2"
            assert payload["regime"] == "mild_risk_off"
            assert payload["confidence"] == 34
            assert payload["recommendation"]["risk_mode"] == "defensive"
            assert payload["reasons"][0].startswith("heatmap_bearish")
        finally:
            os.chdir(old)


if __name__ == "__main__":
    test_macro_regime_reader_missing_is_safe()
    test_macro_regime_reader_valid_snapshot()
    print("OK: smoke_macro_regime_dashboard")
