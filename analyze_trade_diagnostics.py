import json
from pathlib import Path
from collections import defaultdict
def load_jsonl(path):
    p=Path(path); rows=[]
    if not p.exists(): return rows
    for line in p.read_text(encoding='utf-8').splitlines():
        try: rows.append(json.loads(line))
        except Exception: pass
    return rows
def avg(vals):
    vals=[float(v) for v in vals if isinstance(v,(int,float))]
    return round(sum(vals)/len(vals),8) if vals else 0.0
rows=load_jsonl('_runtime/trade_diagnostics.jsonl'); args=load_jsonl('_runtime/entry_argument_snapshots.jsonl')
print('=== VORTEX v1.8.19d TRADE DIAGNOSTICS ==='); print('diagnostic_rows:',len(rows)); print('entry_argument_rows:',len(args))
by_setup=defaultdict(list); by_reason=defaultdict(list)
for r in rows: by_setup[r.get('setup_type') or 'UNKNOWN'].append(r); by_reason[r.get('close_reason') or 'UNKNOWN'].append(r)
print('\n=== BY SETUP ===')
for setup,items in sorted(by_setup.items()):
    good=sum(1 for x in items if (x.get('entry_quality') or {}).get('mfe_gt_abs_mae')); had=sum(1 for x in items if (x.get('entry_quality') or {}).get('had_positive_excursion'))
    print(setup,{'count':len(items),'avg_mfe_pct':avg([x.get('mfe_pct') for x in items]),'avg_mae_pct':avg([x.get('mae_pct') for x in items]),'avg_final_pnl_pct':avg([x.get('final_pnl_pct_est') for x in items]),'good_entry_ratio':round(good/len(items)*100,2) if items else 0,'had_profit_ratio':round(had/len(items)*100,2) if items else 0})
print('\n=== BY CLOSE REASON ===')
for reason,items in sorted(by_reason.items()): print(reason,{'count':len(items),'avg_mfe_pct':avg([x.get('mfe_pct') for x in items]),'avg_final_pnl_pct':avg([x.get('final_pnl_pct_est') for x in items]),'be_had_profit_count':sum(1 for x in items if (x.get('be_damage') or {}).get('had_profit_before_be')),'small_green_possible_count':sum(1 for x in items if (x.get('fee_cover_hint') or {}).get('small_green_possible'))})
