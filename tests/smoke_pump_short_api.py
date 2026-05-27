from pathlib import Path
import os, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from api_server import APIServer
def test_device():
    with tempfile.TemporaryDirectory() as td:
        old=os.getcwd(); os.chdir(td)
        try:
            api=object.__new__(APIServer); latest=APIServer._write_advisor_device_report(api, {'type':'телефон','mode':'мобільний','width':390,'height':844,'dpr':3,'touch':True,'userAgent':'test'})
            assert latest['available'] is True; assert latest['last']['type']=='телефон'; read=APIServer._read_advisor_device_report_latest(api); assert read['available'] is True
        finally: os.chdir(old)
def test_missing():
    with tempfile.TemporaryDirectory() as td:
        old=os.getcwd(); os.chdir(td)
        try:
            api=object.__new__(APIServer); p=APIServer._read_pump_short_advisor_payload(api); assert p['available'] is False; assert p['items']==[]
        finally: os.chdir(old)
if __name__=='__main__': test_device(); test_missing(); print('OK: smoke_pump_short_api')
