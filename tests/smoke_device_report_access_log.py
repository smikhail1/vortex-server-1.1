
from pathlib import Path

text = Path("api_server.py").read_text(encoding="utf-8")

assert "async def handle_advisor_device_report" in text
assert "_log_advisor_access_21md(request, auth, payload)" in text
assert '"access": {' in text
assert 'payload["access_label"] = auth.get("label")' in text

print("OK: smoke_device_report_access_log")
