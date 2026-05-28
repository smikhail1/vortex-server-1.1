
import asyncio, json, time
from pathlib import Path
from typing import Any, Dict, List
SCHEMA_VERSION='1.8.21m-a'
LATEST_PATH=Path('_runtime/pump_short_advisor_latest.json')
SUMMARY_PATH=Path('_runtime/pump_short_advisor_summary.jsonl')

def sf(v,d=0.0):
    try:
        if v is None or v=='': return float(d)
        return float(v)
    except Exception: return float(d)
def si(v,d=0):
    try:
        if v is None or v=='': return int(d)
        return int(float(v))
    except Exception: return int(d)
def ss(v,d=''):
    try: return d if v is None else str(v)
    except Exception: return d
def sym(v): return ss(v).strip().upper()
def clean(cs):
    out=[]
    for c in cs or []:
        try:
            x={'ts':si(c.get('ts')), 'open':sf(c.get('open')), 'high':sf(c.get('high')), 'low':sf(c.get('low')), 'close':sf(c.get('close')), 'volume':sf(c.get('volume')), 'quote_volume':sf(c.get('quote_volume'))}
            if x['high']>0 and x['low']>0 and x['close']>0 and x['high']>=x['low']: out.append(x)
        except Exception: pass
    out.sort(key=lambda x:x.get('ts',0)); return out
def pct(a,b): return 0.0 if not b else (a-b)/b*100.0
def ema(vals,period):
    if not vals: return 0.0
    k=2.0/(period+1.0); e=vals[0]
    for v in vals[1:]: e=v*k+e*(1-k)
    return e
def rsi(vals,period=14):
    if len(vals)<period+1: return 50.0
    gains=[]; losses=[]; recent=vals[-(period+1):]
    for a,b in zip(recent[:-1],recent[1:]):
        d=b-a; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains)/period; al=sum(losses)/period
    if al==0: return 100.0 if ag>0 else 50.0
    rs=ag/al; return 100-100/(1+rs)
def local_high_age(c,lookback=24):
    r=c[-lookback:] if len(c)>=lookback else list(c)
    if not r: return 0
    hs=[x['high'] for x in r]; return len(r)-1-hs.index(max(hs))
def lower_high(c,lookback=24):
    r=c[-lookback:] if len(c)>=lookback else list(c)
    if len(r)<12: return False
    m=len(r)//2; return max(x['high'] for x in r[m:]) < max(x['high'] for x in r[:m])*0.995
def support(c,lookback=18):
    r=c[-lookback:] if len(c)>=lookback else list(c)
    return min((x['low'] for x in r), default=0.0)
def vol_ratio(c,short=6,long=30):
    if len(c)<max(short,long): return 0.0
    a=sum(x.get('volume',0) for x in c[-short:])/short; b=sum(x.get('volume',0) for x in c[-long:])/long
    return 0.0 if b<=0 else a/b

def analyze_symbol(symbol,candles_30m,candles_4h=None):
    symbol=sym(symbol); c=clean(candles_30m); c4=clean(candles_4h or [])
    if len(c)<30: return {'symbol':symbol,'available':False,'phase':'NO_DATA','score':0,'reason':'not_enough_candles','waiting_for':'more_data','notes':['Недостатньо свічок']}
    closes=[x['close'] for x in c]; price=closes[-1]
    i6=max(0,len(c)-13); i24=max(0,len(c)-49)
    pump6=pct(price,c[i6]['close']); pump24=pct(price,c[i24]['close'])
    ema20=ema(closes[-60:],20); ema50=ema(closes[-80:],50)
    de20=pct(price,ema20) if ema20 else 0; de50=pct(price,ema50) if ema50 else 0
    rs=rsi(closes); vr=vol_ratio(c); hage=local_high_age(c); lh=lower_high(c); sup=support(c); bd=pct(price,sup) if sup else 0
    pump_detected=pump24>=18 or pump6>=9; early_pump_watch=(not pump_detected) and (pump24>=8 or pump6>=4) and vr>=1.5; over=de20>=6 or de50>=10 or rs>=72
    score=0; notes=[]
    if early_pump_watch: score+=14; notes.append('Ранній розгін: стежимо, але SHORT ще зарано')
    if pump_detected: score+=20; notes.append('Виявлено сильний памп')
    if vr>=2: score+=12; notes.append('Обʼєм вище середнього')
    elif vr<0.8: notes.append('Обʼєм слабкий')
    if over: score+=15; notes.append('Ціна далеко від балансу')
    if hage>=4 and pump_detected: score+=10; notes.append('Після максимуму минуло кілька свічок')
    if lh and pump_detected: score+=16; notes.append('Є ознака lower high')
    near=0<=bd<=2.5; broken=price<sup*0.995 if sup else False
    if near and pump_detected: score+=10; notes.append('Ціна близько до підтримки')
    if broken and pump_detected: score+=18; notes.append('Підтримку пробито')
    ctx4='no_data'
    if len(c4)>=20:
        cc=[x['close'] for x in c4]; e4=ema(cc[-40:],20); ctx4='above_ema20' if cc[-1]>e4 else 'below_ema20'
        if ctx4=='below_ema20': score+=8; notes.append('4H контекст слабшає')
    if early_pump_watch: phase='EARLY_PUMP_WATCH'; wait='pump_confirmation'; score=max(score,30)
    elif not pump_detected: phase='NO_PUMP'; wait='pump'; score=min(score,25); notes=notes or ['Пампу не виявлено']
    elif broken and lh: phase='SHORT_CANDIDATE'; wait='breakdown_retest_confirmation'
    elif near and (lh or hage>=6): phase='BREAKDOWN_WATCH'; wait='breakdown'
    elif lh or hage>=6: phase='DISTRIBUTION_WATCH'; wait='support_test'
    elif over: phase='OVEREXTENDED'; wait='cooldown_or_lower_high'
    else: phase='PUMP_DETECTED'; wait='distribution_signs'
    return {'symbol':symbol,'available':True,'phase':phase,'score':max(0,min(100,int(round(score)))),'price':round(price,8),'pump_pct_6h':round(pump6,2),'pump_pct_24h':round(pump24,2),'volume_ratio':round(vr,2),'rsi14':round(rs,2),'distance_ema20_pct':round(de20,2),'distance_ema50_pct':round(de50,2),'recent_high_age_bars':hage,'lower_high_detected':bool(lh),'support_level':round(sup,8),'breakdown_distance_pct':round(bd,2),'context_4h':ctx4,'waiting_for':wait,'notes':notes[:8]}
async def get_symbols(state):
    out=[]
    try:
        if hasattr(state,'get_pool'): out.extend(await state.get_pool('fut') or [])
    except Exception: pass
    if not out:
        try:
            d=await state.get_dashboard_state(); out.extend((d.get('system') or {}).get('fut_pool') or [])
        except Exception: pass
    res=[]; seen=set()
    for x in out:
        s=sym(x)
        if s and s not in seen: res.append(s); seen.add(s)
    return res
def build_snapshot(symbols,candle_service):
    rows=[]
    for s in symbols or []:
        try:
            snap=candle_service.get_symbol_snapshot(s,'fut') if candle_service else {}
            rows.append(analyze_symbol(s,snap.get('candles_30m') or [],snap.get('candles_4h') or []))
        except Exception as e:
            rows.append({'symbol':sym(s),'available':False,'phase':'ERROR','score':0,'reason':ss(e)[:160],'waiting_for':'fix_error','notes':['Помилка аналізу']})
    pc={}
    for r in rows: pc[r.get('phase') or 'UNKNOWN']=pc.get(r.get('phase') or 'UNKNOWN',0)+1
    pr={'SHORT_CANDIDATE':1,'BREAKDOWN_WATCH':2,'DISTRIBUTION_WATCH':3,'OVEREXTENDED':4,'PUMP_DETECTED':5,'EARLY_PUMP_WATCH':6,'NO_PUMP':9,'NO_DATA':10,'ERROR':11}
    imp=sorted(rows,key=lambda x:(pr.get(x.get('phase'),99),-si(x.get('score')),x.get('symbol') or ''))[:40]
    return {'schema':'vortex.pump_short_advisor.v1','schema_version':SCHEMA_VERSION,'ts':time.time(),'available':True,'symbols_count':len(rows),'phase_counts':pc,'important':imp,'items':rows,'note':'Read-only advisor. Не відкриває угоди та не впливає на стратегію.'}
def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8'); tmp.replace(path)
def append_jsonl(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f: f.write(json.dumps(data,ensure_ascii=False,sort_keys=True)+'\n')
async def pump_short_advisor_loop(state,candle_service,logger=None):
    while True:
        try:
            snap=build_snapshot(await get_symbols(state),candle_service); write_json(LATEST_PATH,snap); append_jsonl(SUMMARY_PATH,{'ts':snap.get('ts'),'schema_version':SCHEMA_VERSION,'symbols_count':snap.get('symbols_count'),'phase_counts':snap.get('phase_counts')})
            if logger: logger.info('PUMP_SHORT_ADVISOR','snapshot updated',{'symbols':snap.get('symbols_count'),'phase_counts':snap.get('phase_counts')})
            if state:
                try:
                    c=snap.get('phase_counts') or {}; await state.add_sys_log('📉 [PUMP SHORT ADVISOR]', f"оновлено | early={c.get('EARLY_PUMP_WATCH',0)} short={c.get('SHORT_CANDIDATE',0)} breakdown={c.get('BREAKDOWN_WATCH',0)} distribution={c.get('DISTRIBUTION_WATCH',0)}")
                except Exception: pass
        except Exception as e:
            if logger: logger.warning('PUMP_SHORT_ADVISOR','loop failed',{'error':ss(e)[:220]})
        await asyncio.sleep(30)

# ===== VORTEX 21m-i trade plan wrapper =====
def _tp_safe_float_21mi(v, default=0.0):
    try:
        if v is None or v == "":
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _tp_clean_candles_21mi(candles):
    out = []
    for c in candles or []:
        if not isinstance(c, dict):
            continue
        try:
            item = {
                "ts": int(float(c.get("ts", 0) or 0)),
                "open": _tp_safe_float_21mi(c.get("open"), 0.0),
                "high": _tp_safe_float_21mi(c.get("high"), 0.0),
                "low": _tp_safe_float_21mi(c.get("low"), 0.0),
                "close": _tp_safe_float_21mi(c.get("close"), 0.0),
                "volume": _tp_safe_float_21mi(c.get("volume"), 0.0),
            }
            if item["high"] > 0 and item["low"] > 0 and item["close"] > 0 and item["high"] >= item["low"]:
                out.append(item)
        except Exception:
            pass
    out.sort(key=lambda x: x.get("ts", 0))
    return out


def _tp_atr_21mi(candles, period=14):
    c = _tp_clean_candles_21mi(candles)
    if len(c) < 2:
        return 0.0
    trs = []
    prev = c[0]["close"]
    for x in c[1:]:
        tr = max(
            x["high"] - x["low"],
            abs(x["high"] - prev),
            abs(x["low"] - prev),
        )
        trs.append(tr)
        prev = x["close"]
    recent = trs[-period:] if len(trs) >= period else trs
    if not recent:
        return 0.0
    return sum(recent) / len(recent)


def _tp_round_21mi(v):
    try:
        v = float(v)
    except Exception:
        return 0.0
    if v >= 100:
        return round(v, 2)
    if v >= 1:
        return round(v, 4)
    return round(v, 8)


def _tp_rr_21mi(entry, stop, target):
    risk = stop - entry
    if risk <= 0:
        return 0.0
    reward = entry - target
    return round(max(0.0, reward / risk), 2)


def _build_trade_plan_21mi(row, candles_30m=None, candles_4h=None):
    # Plan appears only for a strong SHORT_CANDIDATE.
    # No plan for watch/early/no-pump states.
    if not isinstance(row, dict):
        return None

    phase = row.get("phase")
    score = int(_tp_safe_float_21mi(row.get("score"), 0))

    if phase != "SHORT_CANDIDATE" or score < 55:
        return None

    price = _tp_safe_float_21mi(row.get("price"), 0.0)
    support = _tp_safe_float_21mi(row.get("support_level"), 0.0)
    if price <= 0 or support <= 0:
        return None

    c = _tp_clean_candles_21mi(candles_30m or [])
    if len(c) < 20:
        return None

    atr = _tp_atr_21mi(c, 14)
    if atr <= 0:
        atr = max(price * 0.01, 0.00000001)

    recent = c[-24:] if len(c) >= 24 else c
    recent_high = max(x["high"] for x in recent)
    recent_low = min(x["low"] for x in recent)

    entry_center = support
    entry_from = support - atr * 0.25
    entry_to = support + atr * 0.15

    stop = max(entry_to + atr * 1.2, support + atr * 1.2)
    if recent_high < support + atr * 3.0:
        stop = max(stop, recent_high + atr * 0.25)

    risk = stop - entry_center
    if risk <= 0:
        return None

    tp1 = entry_center - risk * 1.0
    tp2 = entry_center - risk * 2.0
    tp3 = entry_center - risk * 3.0

    structural_target = recent_low if recent_low < entry_center else None

    return {
        "available": True,
        "quality": "GOOD_ENTRY_ONLY",
        "side": "SHORT",
        "entry_type": "breakdown_retest",
        "status": "actionable_after_retest",
        "entry_zone": {
            "from": _tp_round_21mi(entry_from),
            "to": _tp_round_21mi(entry_to),
            "center": _tp_round_21mi(entry_center),
        },
        "stop": _tp_round_21mi(stop),
        "tp1": _tp_round_21mi(tp1),
        "tp2": _tp_round_21mi(tp2),
        "tp3": _tp_round_21mi(tp3),
        "rr": {
            "tp1": _tp_rr_21mi(entry_center, stop, tp1),
            "tp2": _tp_rr_21mi(entry_center, stop, tp2),
            "tp3": _tp_rr_21mi(entry_center, stop, tp3),
        },
        "atr_30m": _tp_round_21mi(atr),
        "structure": {
            "support": _tp_round_21mi(support),
            "recent_high": _tp_round_21mi(recent_high),
            "recent_low": _tp_round_21mi(recent_low),
            "structural_target": _tp_round_21mi(structural_target) if structural_target else None,
        },
        "management": [
            "Вхід тільки після breakdown + retest знизу.",
            "TP1: закрити 30-50% і перевести stop у BE.",
            "TP2: основна фіксація.",
            "TP3: тільки якщо імпульс сильний і ринок підтримує SHORT.",
        ],
        "warning": "Не входити, якщо ціна повернулась вище support/retest-зони.",
    }


try:
    _orig_analyze_symbol_21mi
except NameError:
    _orig_analyze_symbol_21mi = analyze_symbol

    def analyze_symbol(symbol, candles_30m, candles_4h=None):
        row = _orig_analyze_symbol_21mi(symbol, candles_30m, candles_4h)
        if isinstance(row, dict):
            row["trade_plan"] = _build_trade_plan_21mi(row, candles_30m, candles_4h)
        return row
# ===== END VORTEX 21m-i trade plan wrapper =====

