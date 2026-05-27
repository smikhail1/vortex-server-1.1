
from pathlib import Path

p = Path("web/pump_short_advisor.html")
text = p.read_text(encoding="utf-8")

assert "21m-e2" in text
assert "localStorage.removeItem('advisor_key')" in text
assert "if(!advisorKey()){if(!ensureKeyPrompt())return;}" in text
assert "X-Advisor-Key" in text
assert "?key=" not in text or "u.searchParams.get('key')" in text

print("OK: smoke_advisor_key_reprompt")
