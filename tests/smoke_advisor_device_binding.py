from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api_server import APIServer


def bind(api, key, ua="ua-pc", touch=False, dpr=1.0, typ="ПК", mode="десктопний"):
    auth = {"allowed": True, "reason": "allowed", "key": key, "label": "Device 01"}
    payload = {
        "type": typ,
        "mode": mode,
        "width": 1920,
        "height": 919,
        "dpr": dpr,
        "touch": touch,
        "userAgent": ua,
    }
    return APIServer._check_or_bind_advisor_device_21mg(api, auth, payload)


def test_device_binding_first_and_repeat_allowed():
    with tempfile.TemporaryDirectory() as td:
        old = os.getcwd()
        os.chdir(td)
        try:
            Path("_runtime").mkdir()
            api = object.__new__(APIServer)

            first = bind(api, "KEY1", ua="ua-pc")
            assert first["allowed"] is True
            assert first["binding"] == "created"

            second = bind(api, "KEY1", ua="ua-pc")
            assert second["allowed"] is True
            assert second["binding"] == "matched"
        finally:
            os.chdir(old)


def test_device_binding_blocks_other_device():
    with tempfile.TemporaryDirectory() as td:
        old = os.getcwd()
        os.chdir(td)
        try:
            Path("_runtime").mkdir()
            api = object.__new__(APIServer)

            first = bind(api, "KEY1", ua="ua-pc", touch=False, typ="ПК")
            assert first["allowed"] is True

            other = bind(api, "KEY1", ua="ua-phone", touch=True, dpr=3.5, typ="телефон", mode="мобільний")
            assert other["allowed"] is False
            assert other["reason"] == "device_mismatch"
        finally:
            os.chdir(old)


if __name__ == "__main__":
    test_device_binding_first_and_repeat_allowed()
    test_device_binding_blocks_other_device()
    print("OK: smoke_advisor_device_binding")
