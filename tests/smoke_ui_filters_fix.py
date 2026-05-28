
from pathlib import Path

text = Path("web/pump_short_advisor.html").read_text(encoding="utf-8")

assert 'data-f="EARLY_PUMP_WATCH"' in text
assert "function updateFilterButtons" in text
assert "function emptyMessage" in text
assert "Немає монет у цьому фільтрі" in text
assert "phaseCount" in text
assert "button[data-f]" in text
assert "Ранній памп" in text
assert "pump_confirmation" in text

print("OK: smoke_ui_filters_fix")
