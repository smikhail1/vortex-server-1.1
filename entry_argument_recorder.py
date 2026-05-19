import json, time
from pathlib import Path
from validators import safe_float, safe_str
class EntryArgumentRecorder:
    """VORTEX v1.8.19d analytics-only entry argument snapshots."""
    def __init__(self,path="_runtime/entry_argument_snapshots.jsonl",logger=None):
        self.path=Path(path); self.logger=logger; self.path.parent.mkdir(parents=True, exist_ok=True)
    def record(self,snapshot):
        snapshot=snapshot if isinstance(snapshot,dict) else {}; ta=snapshot.get('ta') if isinstance(snapshot.get('ta'),dict) else {}; analysis=snapshot.get('analysis') if isinstance(snapshot.get('analysis'),dict) else {}; watch=snapshot.get('watch') if isinstance(snapshot.get('watch'),dict) else {}; planner=snapshot.get('planner') if isinstance(snapshot.get('planner'),dict) else {}; dq=snapshot.get('data_quality') if isinstance(snapshot.get('data_quality'),dict) else {}
        row={'schema':'vortex.entry_arguments.v1','schema_version':'1.8.19d','ts':time.time(),'symbol':safe_str(snapshot.get('symbol')).upper(),'market':safe_str(snapshot.get('market')).upper(),'side':safe_str(snapshot.get('side')).upper(),'setup_type':safe_str(snapshot.get('setup_type')),'entry':safe_float(snapshot.get('entry'),0.0),'score':safe_float(analysis.get('score') or watch.get('score'),0.0),'args_text':safe_str(snapshot.get('args_text')),'ta':{'price':safe_float(ta.get('price'),0.0),'adx':safe_float(ta.get('adx'),0.0),'rsi':safe_float(ta.get('rsi'),0.0),'atr_pct':safe_float(ta.get('atr_pct'),0.0),'ema_gap_pct':safe_float(ta.get('ema_gap_pct'),0.0),'volume_ratio':safe_float(ta.get('volume_ratio'),0.0),'change_pct':safe_float(ta.get('change_pct'),0.0),'range_pct':safe_float(ta.get('range_pct'),0.0),'trend':safe_str(ta.get('trend')),'signal':safe_str(ta.get('signal')),'timeframe':safe_str(ta.get('timeframe'))},'watch':{'status':safe_str(watch.get('status')),'confirmed':bool(watch.get('confirmed')),'confirmation_status':safe_str(watch.get('confirmation_status')),'confirmation_reason':safe_str(watch.get('confirmation_reason')),'trigger_price':safe_float(watch.get('trigger_price'),0.0)},'planner':{'present':bool(snapshot.get('planner_present')),'symbol':safe_str(planner.get('symbol')).upper(),'score':safe_float(planner.get('score'),0.0),'setup_type':safe_str(planner.get('setup_type'))},'data_quality':{'score':safe_float(dq.get('score'),0.0),'missing_fields':dq.get('missing_fields',[]),'warnings':dq.get('warnings',[])}}
        try:
            with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
        except Exception as exc:
            try: self.logger.warning('ANALYTICS','entry argument write failed',{'error':str(exc)})
            except Exception: pass
        return row
