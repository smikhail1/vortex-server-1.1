from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from pump_short_advisor import analyze_symbol, build_snapshot
def make(n=80):
    out=[]; price=1.0
    for i in range(n):
        price *= 1.002 if i<45 else (1.018 if i<60 else 0.996)
        out.append({'ts':i,'open':price*.995,'high':price*(1.02 if i==60 else 1.006),'low':price*.994,'close':price,'volume':1000*(4 if 50<=i<=65 else 1),'quote_volume':100000})
    return out
class Fake:
    def get_symbol_snapshot(self,symbol,market='fut'): return {'candles_30m':make(),'candles_4h':make(40)}
def test_analyze():
    r=analyze_symbol('TESTUSDT',make(),make(40)); assert r['available'] is True; assert r['score']>=20
def test_snapshot():
    s=build_snapshot(['TESTUSDT'],Fake()); assert s['available'] is True; assert s['symbols_count']==1; assert len(s['important'])==1
if __name__=='__main__': test_analyze(); test_snapshot(); print('OK: smoke_pump_short_advisor')
