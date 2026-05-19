import json, time
from pathlib import Path
from collections import defaultdict

def load_jsonl(path):
    p=Path(path); rows=[]
    if not p.exists(): return rows
    for line in p.read_text(encoding='utf-8').splitlines():
        try: rows.append(json.loads(line))
        except Exception: pass
    return rows

def avg(v):
    vals=[float(x) for x in v if isinstance(x,(int,float))]
    return round(sum(vals)/len(vals),8) if vals else 0.0

def build_fee_cover_shadow_guard(source_path='_runtime/trade_diagnostics.jsonl',output_path='_runtime/fee_cover_shadow_guard.json'):
    rows=load_jsonl(source_path); by=defaultdict(list)
    for r in rows: by[r.get('setup_type') or 'UNKNOWN'].append(r)
    payload={'schema':'vortex.fee_cover_shadow_guard.v1','schema_version':'1.8.19e','generated_at':time.time(),'source':source_path,'rows':len(rows),'notes':['analytics_only','no execution changes','fee-cover opportunity detector'],'by_setup':{},'overall':{}}
    total_candidates=0; total_be_profit=0
    for setup,items in by.items():
        cand=[]; be_profit=0
        for r in items:
            mfe=float(r.get('mfe_pct',0.0) or 0.0); final=float(r.get('final_pnl_pct_est',0.0) or 0.0)
            hint=r.get('fee_cover_hint') if isinstance(r.get('fee_cover_hint'),dict) else {}
            be=r.get('be_damage') if isinstance(r.get('be_damage'),dict) else {}
            if be.get('had_profit_before_be'): be_profit+=1
            if hint.get('small_green_possible') or (mfe>=0.06 and final<=0.02): cand.append(r)
        total_candidates+=len(cand); total_be_profit+=be_profit
        payload['by_setup'][setup]={'count':len(items),'candidate_count':len(cand),'candidate_pct':round(len(cand)/len(items)*100.0,2) if items else 0.0,'be_had_profit_count':be_profit,'avg_candidate_mfe_pct':avg([x.get('mfe_pct') for x in cand]),'avg_candidate_final_pct':avg([x.get('final_pnl_pct_est') for x in cand]),'avg_candidate_left_on_table_pct':avg([(x.get('entry_quality') or {}).get('exit_gave_back_pct') for x in cand]),'recommendation':'watch_fee_cover_exit' if len(cand)>=3 else 'collect_more'}
    payload['overall']={'candidate_count':total_candidates,'be_had_profit_count':total_be_profit,'candidate_pct':round(total_candidates/len(rows)*100.0,2) if rows else 0.0,'recommendation':'fee_cover_shadow_guard_supported' if total_candidates>=10 else 'collect_more'}
    Path(output_path).write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
    return payload

if __name__=='__main__': print(json.dumps(build_fee_cover_shadow_guard(),ensure_ascii=False,indent=2))
