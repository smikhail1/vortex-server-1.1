import json
from pathlib import Path
PATH=Path('_runtime/pump_short_advisor_latest.json')
if not PATH.exists():
    print('pump short advisor snapshot missing:', PATH); raise SystemExit(0)
d=json.loads(PATH.read_text(encoding='utf-8'))
print('schema:', d.get('schema_version'))
print('ts:', d.get('ts'))
print('available:', d.get('available'))
print('symbols_count:', d.get('symbols_count'))
print('phase_counts:', d.get('phase_counts'))
print('\n===== TOP IMPORTANT =====')
for x in (d.get('important') or [])[:40]:
    print(f"{x.get('symbol')} | phase={x.get('phase')} | score={x.get('score')} | pump24={x.get('pump_pct_24h')}% | pump6={x.get('pump_pct_6h')}% | vol={x.get('volume_ratio')}x | level={x.get('support_level')} | wait={x.get('waiting_for')} | notes={x.get('notes')}")
