
from pathlib import Path

p = Path("web/pump_short_advisor.html")
text = p.read_text(encoding="utf-8")

assert "function advisorHeaders" in text
assert "ensureKeyPrompt" in text
assert "Введіть ключ пристрою" in text
assert "X-Advisor-Key" in text
assert "history.replaceState" in text
assert "Змінити ключ" in text
assert "?key=" not in text or "u.searchParams.get('key')" in text

print("OK: smoke_advisor_key_prompt")
