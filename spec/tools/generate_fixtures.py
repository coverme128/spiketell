"""Deterministic synthetic fixtures: NEVER treated as live market data."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))


def mkbars(close='10.12', amount='4000000', *, high=None, quality='VALID'):
    base=datetime(2026, 10, 9, 9, 39, tzinfo=TZ)
    bars=[]
    for i in range(21):
        dt=base+timedelta(minutes=i)
        prev='10' if i < 18 else ('9.98' if i == 18 else '9.99' if i == 19 else '10')
        if i == 0:
            op='10'; cl='10'
        elif i == 17:
            op='10'; cl='10'
        elif i == 18:
            op='10'; cl='9.98'
        elif i == 19:
            op='9.98'; cl='9.99'
        elif i == 20:
            op='9.99'; cl='10'
        else:
            op=cl='10'
        # Need 20 previous, then the 22nd is the spike: see below
        bars.append({'symbol':'SH.600000','bar_start_at':dt.isoformat(),
            'bar_end_at':(dt+timedelta(minutes=1)).isoformat(),
            'open':op,'high':str(max(float(op),float(cl))),
            'low':str(min(float(op),float(cl))), 'close':cl,
            'volume_shares':100000, 'amount_cny':'1000000',
            'source':'fixture','received_at':(dt+timedelta(minutes=1,seconds=9)).isoformat(),
            'is_final':True,'quality':'VALID'})
    # last previous close is 10, close of 09:58 is 10. Latest spike is 09:59.
    # fix last 4 closes to 9.98, 9.99, 10, spike, with no future bars.
    bars[-4]['open']='10'; bars[-4]['close']='9.98'; bars[-4]['high']='10'; bars[-4]['low']='9.98'
    bars[-3]['open']='9.98'; bars[-3]['close']='9.99'; bars[-3]['high']='9.99'; bars[-3]['low']='9.98'
    bars[-2]['open']='9.99'; bars[-2]['close']='10'; bars[-2]['high']='10'; bars[-2]['low']='9.99'
    last=bars[-1]
    last['open']='10'; last['close']=close; last['high']=str(max(float(close),float(high or close)))
    last['low']='10' if float(close)>=10 else close
    last['amount_cny']=amount
    last['quality']=quality
    return bars

base=mkbars()
BASE=["1000000"]*5
scenarios=[
  {"id":"S01_HIGH_SPIKE","bars":base,"prior_same_slot_amounts":BASE,"now":"2026-10-09T10:00:10+08:00","expected":{"triggered":True,"priority":"HIGH","score":75,"error":None,"turnover_burst":"4","breakout20":True,"persistence3":True}},
  {"id":"S02_NO_TRIGGER","bars":mkbars(close='10.02'),"prior_same_slot_amounts":BASE,"now":"2026-10-09T10:00:10+08:00","expected":{"triggered":False,"priority":"LOW","score":0,"error":"NO_TRIGGER"}},
  {"id":"S03_LOW_TURNOVER","bars":mkbars(amount='500000'),"prior_same_slot_amounts":BASE,"now":"2026-10-09T10:00:10+08:00","expected":{"triggered":False,"error":"LOW_TURNOVER"}},
  {"id":"S04_MISSING_BASELINE","bars":base,"prior_same_slot_amounts":[],"now":"2026-10-09T10:00:10+08:00","expected":{"triggered":True,"priority":"MEDIUM","score":55,"turnover_burst":None,"error":None}},
  {"id":"S05_UPPER_WICK_AND_PULLBACK","bars":mkbars(high='10.30'),"prior_same_slot_amounts":BASE,"now":"2026-10-09T10:00:10+08:00","expected":{"triggered":True,"priority":"MEDIUM","score":45,"error":None}},
  {"id":"S06_STALE","bars":base,"prior_same_slot_amounts":BASE,"now":"2026-10-09T10:03:00+08:00","expected":{"triggered":False,"error":"STALE_BAR"}},
  {"id":"S07_NON_FINAL","bars":mkbars(quality='PARTIAL'),"prior_same_slot_amounts":BASE,"now":"2026-10-09T10:00:10+08:00","expected":{"triggered":False,"error":"INVALID_BAR"}},
  {"id":"S08_LUNCH_GAP","bars":base[:-1]+[dict(base[-1],bar_start_at='2026-10-09T13:00:00+08:00',bar_end_at='2026-10-09T13:01:00+08:00')],"prior_same_slot_amounts":BASE,"now":"2026-10-09T13:01:10+08:00","expected":{"triggered":False,"error":"INSUFFICIENT_CONTIGUOUS_BARS"}},
  {"id":"S09_CLOSE_AUCTION","bars":base[:-1]+[dict(base[-1],bar_start_at='2026-10-09T14:58:00+08:00',bar_end_at='2026-10-09T14:59:00+08:00')],"prior_same_slot_amounts":BASE,"now":"2026-10-09T14:59:10+08:00","expected":{"triggered":False,"error":"INVALID_BAR"}},
  {"id":"S10_FUTURE_BAR","bars":base,"prior_same_slot_amounts":BASE,"now":"2026-10-09T09:59:50+08:00","expected":{"triggered":False,"error":"FUTURE_BAR"}}
]
path=ROOT/'fixtures'/'rule_scenarios.json'
path.write_text(json.dumps({'data_mode':'SIMULATION','description':'Synthetic OHLCV with independent expected assertions; never a real market quote','cases':scenarios},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Generated {len(scenarios)} synthetic scenarios into {path}')
