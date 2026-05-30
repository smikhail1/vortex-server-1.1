from pathlib import Path

ROOT = Path(".")
api = (ROOT / "api_server.py").read_text(encoding="utf-8")
html = (ROOT / "web" / "pump_short_advisor.html").read_text(encoding="utf-8")

def require(cond, msg):
    if not cond:
        raise SystemExit(msg)

# API required markers
require("query_key_disabled" in api, "query key denial reason missing")
require('request.headers.get("Authorization")' in api, "Authorization header is not checked")
require("bearer " in api.lower(), "Bearer auth parsing missing")
require("X-Advisor-Device" in api, "X-Advisor-Device missing in API")
require("def _advisor_security_headers_1823a" in api, "security header helper missing")
require("Cache-Control" in api and "no-store" in api, "no-store header missing")
require("Referrer-Policy" in api, "Referrer-Policy header missing")
require("X-Frame-Options" in api, "X-Frame-Options header missing")
require("X-Content-Type-Options" in api, "X-Content-Type-Options header missing")
require("Content-Security-Policy" in api, "CSP header missing")
require("_check_or_bind_advisor_device_21mg" in api, "device binding helper missing")
require("handle_pump_short_advisor" in api, "pump advisor handler missing")

# Old API behavior must not remain
require('raw_key = safe_str(request.query.get("key"), "").strip()' not in api, "old query key extraction still present")
require("return web.json_response(self._read_pump_short_advisor_payload())" not in api, "advisor payload returned without hardened response")

# HTML required markers
require("v1.8.23-a advisor auth hardening" in html, "HTML hardening marker missing")
require("Authorization" in html and "Bearer " in html, "HTML does not use Authorization Bearer")
require("X-Advisor-Device" in html, "HTML does not send X-Advisor-Device")
require("advisor_key" in html, "advisor local key storage missing")
require("Ключ у URL" in html or "URL" in html, "URL key warning missing")

# Old HTML behavior must not remain
require("localStorage.setItem('advisor_key',k)" not in html, "HTML still stores key directly from URL query")
require("h['X-Advisor-Key']=k" not in html, "HTML still uses X-Advisor-Key as primary auth")

print("OK: smoke_advisor_auth_hardening")
