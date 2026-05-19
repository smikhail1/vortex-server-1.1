import json,time
from pathlib import Path
from collections import defaultdict
def load_jsonl(path):
    p=Path(path); out=[]
    if not p.exists(): return out
    for line in p.read_text(encoding='utf-8').splitlines():
        try: out.append(json.loads(line))
        except Exception: pass
    return out
def avg(v):
    v=[float(x) for x in v if isinstance(x,(int,float))]
    return round(sum(v)/len(v),8) if v else 0.0
rows=load_jsonl('_runtime/trade_diagnostics.jsonl'); by=defaultdict(list)
for r in rows: by[r.get('close_reason','UNKNOWN')].append(r)
payload={'schema':'vortex.exit_diagnostics_summary.v1','schema_version':'1.8.19d','generated_at':time.time(),'count':len(rows),'by_close_reason':{}}
for reason,items in by.items(): payload['by_close_reason'][reason]={'count':len(items),'avg_mfe_pct':avg([x.get('mfe_pct') for x in items]),'avg_mae_pct':avg([x.get('mae_pct') for x in items]),'avg_final_pnl_pct':avg([x.get('final_pnl_pct_est') for x in items]),'avg_exit_gave_back_pct':avg([(x.get('entry_quality') or {}).get('exit_gave_back_pct') for x in items]),'be_had_profit_count':sum(1 for x in items if (x.get('be_damage') or {}).get('had_profit_before_be')),'small_green_possible_count':sum(1 for x in items if (x.get('fee_cover_hint') or {}).get('small_green_possible'))}
Path('_runtime/exit_diagnostics_summary.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8'); print(json.dumps(payload,ensure_ascii=False,indent=2))
