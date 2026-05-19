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
rows=load_jsonl('_runtime/trade_diagnostics.jsonl')
def cur(r): return float(r.get('final_pnl_pct_est',0.0) or 0.0)
def fee(r):
    final=cur(r); mfe=float(r.get('mfe_pct',0.0) or 0.0); return 0.02 if mfe>=0.06 and final<0.02 else final
def delay15(r):
    final=cur(r); mfe=float(r.get('mfe_pct',0.0) or 0.0); reason=str(r.get('close_reason','')).upper(); return max(final,min(mfe*0.35,0.08)) if reason in {'BU','BE','BREAKEVEN','AGGRESSIVE_BE'} and mfe>0.04 else final
def stall(r):
    final=cur(r); mfe=float(r.get('mfe_pct',0.0) or 0.0); reason=str(r.get('close_reason','')).upper(); return max(final,min(mfe*0.50,0.12)) if reason in {'BU','BE','BREAKEVEN'} and mfe>0 else final
variants={'current':cur,'delay_be_15_shadow':delay15,'fee_cover_exit_shadow':fee,'stall_hold_shadow':stall}; by=defaultdict(list)
for r in rows: by[r.get('setup_type') or 'UNKNOWN'].append(r)
payload={'schema':'vortex.shadow_variant_results.v1','schema_version':'1.8.19d','generated_at':time.time(),'rows':len(rows),'by_setup':{}}
for setup,items in by.items():
    current=sum(cur(r) for r in items); block={'count':len(items),'variants':{}}
    for name,fn in variants.items():
        val=sum(fn(r) for r in items); block['variants'][name]={'sum_pnl_pct_est':round(val,8),'delta_vs_current_pct':round(val-current,8)}
    payload['by_setup'][setup]=block
Path('_runtime/shadow_variant_results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8'); print(json.dumps(payload,ensure_ascii=False,indent=2))
