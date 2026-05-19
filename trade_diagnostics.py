import json, time
from pathlib import Path
from validators import safe_float, safe_str

class TradeDiagnosticsRecorder:
    """VORTEX v1.8.19d analytics-only MFE/MAE tracker."""
    def __init__(self, active_path="_runtime/trade_diagnostics_active.json", output_path="_runtime/trade_diagnostics.jsonl", logger=None):
        self.active_path=Path(active_path); self.output_path=Path(output_path); self.logger=logger
        self.active_path.parent.mkdir(parents=True, exist_ok=True); self.output_path.parent.mkdir(parents=True, exist_ok=True)
    def _load(self):
        try: return json.loads(self.active_path.read_text(encoding="utf-8")) if self.active_path.exists() else {}
        except Exception: return {}
    def _save(self,d):
        try: self.active_path.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
        except Exception: pass
    def _key(self,symbol,market): return f"{safe_str(market).upper()}:{safe_str(symbol).upper()}"
    def _sign(self,side): return -1 if safe_str(side).upper() in {"SHORT","SELL"} else 1
    def _pnl_pct(self,entry,price,side):
        if entry<=0 or price<=0: return 0.0
        return ((price-entry)/entry*100.0)*self._sign(side)
    def update_position(self, *, pos, market, current_price, snapshot=None):
        try:
            pos=pos if isinstance(pos,dict) else {}; symbol=safe_str(pos.get('symbol')).upper()
            if not symbol: return
            entry=safe_float(pos.get('entry'),0.0); price=safe_float(current_price,0.0)
            if entry<=0 or price<=0: return
            side=safe_str(pos.get('side') or ('BUY' if safe_str(market).upper()=='SPOT' else 'LONG')).upper()
            now=time.time(); key=self._key(symbol,market); active=self._load(); row=active.get(key)
            if not isinstance(row,dict):
                row={'schema':'vortex.trade_diagnostics.active.v1','schema_version':'1.8.19d','symbol':symbol,'market':safe_str(market).upper(),'side':side,'setup_type':safe_str(pos.get('setup_type')),'args_text':safe_str(pos.get('args_text')),'entry_price':entry,'first_seen_ts':now,'mfe_pct':0.0,'mae_pct':0.0,'time_to_mfe_sec':0,'time_in_profit_sec':0,'updates':0,'last_ts':now,'last_price':price}
            pnl=self._pnl_pct(entry,price,side); prev=safe_float(row.get('last_ts'),now); dt=max(0.0,now-prev)
            if pnl>safe_float(row.get('mfe_pct'),0.0): row['mfe_pct']=round(pnl,8); row['time_to_mfe_sec']=int(now-safe_float(row.get('first_seen_ts'),now))
            if pnl<safe_float(row.get('mae_pct'),0.0): row['mae_pct']=round(pnl,8)
            if pnl>0: row['time_in_profit_sec']=int(safe_float(row.get('time_in_profit_sec'),0)+dt)
            row['updates']=int(safe_float(row.get('updates'),0))+1; row['last_pnl_pct']=round(pnl,8); row['last_price']=price; row['last_ts']=now
            active[key]=row; self._save(active)
        except Exception as exc:
            try: self.logger.warning('ANALYTICS','trade diagnostics update failed',{'error':str(exc)})
            except Exception: pass
    def finalize_close(self, *, data, fallback_pos, market):
        data=data if isinstance(data,dict) else {}; fallback_pos=fallback_pos if isinstance(fallback_pos,dict) else {}
        symbol=safe_str(data.get('symbol') or fallback_pos.get('symbol')).upper()
        if not symbol: return {}
        active=self._load(); key=self._key(symbol,market); row=active.get(key,{}) if isinstance(active.get(key,{}),dict) else {}; now=time.time()
        entry=safe_float(data.get('entry') or fallback_pos.get('entry') or row.get('entry_price'),0.0)
        exit_price=safe_float(data.get('exit_price') or data.get('price') or row.get('last_price'),0.0)
        side=safe_str(data.get('side') or fallback_pos.get('side') or row.get('side')).upper(); reason=safe_str(data.get('reason'),'CLOSE').upper()
        final_pct=self._pnl_pct(entry,exit_price,side) if entry>0 and exit_price>0 else 0.0; mfe=safe_float(row.get('mfe_pct'),0.0); mae=safe_float(row.get('mae_pct'),0.0)
        diag={'schema':'vortex.trade_diagnostics.v1','schema_version':'1.8.19d','ts':now,'symbol':symbol,'market':safe_str(market).upper(),'side':side,'setup_type':safe_str(data.get('setup_type') or fallback_pos.get('setup_type') or row.get('setup_type')),'args_text':safe_str(data.get('args_text') or fallback_pos.get('args_text') or row.get('args_text')),'entry_price':entry,'exit_price':exit_price,'close_reason':reason,'pnl_net':safe_float(data.get('pnl_net'),0.0),'final_pnl_pct_est':round(final_pct,8),'hold_sec':int(safe_float(data.get('hold_sec'),0.0) or max(0.0,now-safe_float(row.get('first_seen_ts'),now))),'mfe_pct':round(mfe,8),'mae_pct':round(mae,8),'time_to_mfe_sec':int(safe_float(row.get('time_to_mfe_sec'),0)),'time_in_profit_sec':int(safe_float(row.get('time_in_profit_sec'),0)),'updates':int(safe_float(row.get('updates'),0)),'entry_quality':{'had_positive_excursion':mfe>0,'mfe_gt_abs_mae':mfe>abs(mae),'mfe_minus_final_pct':round(mfe-final_pct,8),'exit_gave_back_pct':round(max(0.0,mfe-final_pct),8)},'be_damage':{'is_be_like':reason in {'BU','BE','BREAKEVEN','AGGRESSIVE_BE'},'had_profit_before_be':reason in {'BU','BE','BREAKEVEN','AGGRESSIVE_BE'} and mfe>0,'potential_pct_left':round(max(0.0,mfe-final_pct),8)},'fee_cover_hint':{'small_green_possible':mfe>0.04 and final_pct<=0.02,'mfe_pct_threshold_used':0.04}}
        try:
            with self.output_path.open('a',encoding='utf-8') as f: f.write(json.dumps(diag,ensure_ascii=False,sort_keys=True)+'\n')
        except Exception: pass
        try: active.pop(key,None); self._save(active)
        except Exception: pass
        try: self.logger.info('ANALYTICS','trade diagnostics recorded',{'symbol':symbol,'market':safe_str(market).upper(),'reason':reason,'mfe_pct':diag['mfe_pct'],'mae_pct':diag['mae_pct']})
        except Exception: pass
        return diag
