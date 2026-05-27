from pathlib import Path
import json
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api_server import APIServer


class DummyRequest:
    path = "/api/advisor/device-report"
    method = "POST"
    remote = "127.0.0.1"

    def __init__(self, key=""):
        self.query = {"key": key} if key else {}
        self.headers = {}


def test_advisor_auth_allowed_and_denied():
    with tempfile.TemporaryDirectory() as td:
        old = os.getcwd()
        os.chdir(td)
        try:
            Path("_runtime").mkdir()
            Path("_runtime/advisor_access_keys.json").write_text(json.dumps({
                "keys": [
                    {"key": "TEST-KEY", "label": "Test Device", "enabled": True},
                    {"key": "DISABLED", "label": "Disabled", "enabled": False},
                ]
            }), encoding="utf-8")

            api = object.__new__(APIServer)

            ok = APIServer._advisor_auth_from_request_21md(api, DummyRequest("TEST-KEY"))
            assert ok["allowed"] is True
            assert ok["label"] == "Test Device"

            missing = APIServer._advisor_auth_from_request_21md(api, DummyRequest(""))
            assert missing["allowed"] is False
            assert missing["reason"] == "missing_key"

            bad = APIServer._advisor_auth_from_request_21md(api, DummyRequest("BAD"))
            assert bad["allowed"] is False
            assert bad["reason"] == "bad_key"

            disabled = APIServer._advisor_auth_from_request_21md(api, DummyRequest("DISABLED"))
            assert disabled["allowed"] is False
            assert disabled["reason"] == "disabled_key"
        finally:
            os.chdir(old)


def test_access_log_writes_latest():
    with tempfile.TemporaryDirectory() as td:
        old = os.getcwd()
        os.chdir(td)
        try:
            Path("_runtime").mkdir()
            api = object.__new__(APIServer)
            auth = {"allowed": True, "reason": "allowed", "label": "ПК"}
            APIServer._log_advisor_access_21md(api, DummyRequest("TEST-KEY"), auth, {
                "type": "ПК",
                "mode": "десктопний",
                "width": 1920,
                "height": 919,
                "dpr": 1,
                "touch": False,
                "userAgent": "test",
            })
            latest = APIServer._read_advisor_access_latest_21md(api)
            assert latest["available"] is True
            assert latest["devices"][0]["type"] == "ПК"
            assert Path("_runtime/advisor_access.jsonl").exists()
        finally:
            os.chdir(old)


if __name__ == "__main__":
    test_advisor_auth_allowed_and_denied()
    test_access_log_writes_latest()
    print("OK: smoke_advisor_access_keys")
