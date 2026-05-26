from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api_server
from api_server import _format_uptime_human_21li


def test_time_import_and_started_at():
    assert hasattr(api_server, "time")
    assert hasattr(api_server, "SERVER_STARTED_AT")
    assert isinstance(api_server.SERVER_STARTED_AT, float)
    assert api_server.SERVER_STARTED_AT <= time.time()


def test_format_uptime_seconds():
    assert _format_uptime_human_21li(0) == "0с"
    assert _format_uptime_human_21li(45) == "45с"


def test_format_uptime_minutes():
    assert _format_uptime_human_21li(60) == "1м"
    assert _format_uptime_human_21li(59 * 60) == "59м"


def test_format_uptime_hours():
    assert _format_uptime_human_21li(60 * 60) == "1ч 0м"
    assert _format_uptime_human_21li(5 * 3600 + 42 * 60) == "5ч 42м"


def test_format_uptime_days():
    assert _format_uptime_human_21li(24 * 3600) == "1д 0ч"
    assert _format_uptime_human_21li(2 * 24 * 3600 + 4 * 3600) == "2д 4ч"


if __name__ == "__main__":
    test_time_import_and_started_at()
    test_format_uptime_seconds()
    test_format_uptime_minutes()
    test_format_uptime_hours()
    test_format_uptime_days()
    print("OK: smoke_health_uptime")
