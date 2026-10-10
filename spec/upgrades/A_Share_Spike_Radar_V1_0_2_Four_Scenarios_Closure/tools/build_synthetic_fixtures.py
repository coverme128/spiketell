"""Deterministic FIXTURE builder, no network or market data source."""
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

ROOT=Path(__file__).resolve().parents[1]
TZ=timezone(timedelta(hours=8))
base=datetime(2026,10,9,10,0,tzinfo=TZ)


def bar(i, close, *, open_=None, high=None, low=None, amt='4000000', is_final=True, quality='VALID', at=None):
    st=at or (base+timedelta(minutes=i))
    c=Decimal(str(close)); o=Decimal(str(open_)) if open_ is not None else c
    h=Decimal(str(high)) if high is not None else max(o,c)+Decimal('0.1')
    l=Decimal(str(low)) if low is not None else min(o,c)-Decimal('0.1')
    return {
        'symbol':'SZ.300001', 'bar_start_at':st.isoformat(),
        'bar_end_at':(st+timedelta(minutes=1)).isoformat(),
        'open':str(o),'high':str(h),'low':str(l),'close':str(c),
        'amount_cny':amt,'volume_shares':250000,'is_final':is_final,'quality':quality,
    }


def flat20(): return [bar(i,100,high='100.25',low='99.80',amt='1000000') for i in range(20)]

def case(id,bars,expect,with_hist=True,**extra):
    now=datetime.fromisoformat(bars[-1]['bar_end_at'])+timedelta(seconds=12)
    d={'id':id,'data_mode':'SIMULATION','bars':bars,
       'prior_same_slot_amounts':['1000000']*5 if with_hist else [],
       'now':now.isoformat(),'expect':expect}
    d.update(extra)
    return d

rows=[]
rows.append(case('F201_rapid',[bar(0,100),bar(1,101.00,open_=100,high=101.1,low=99.95)],{'triggered':True,'primary_scenario':'RAPID_RISE'}))
rows.append(case('F202_rapid_cold',[bar(0,100),bar(1,101.90,open_=100,high=102,low=99.95)],{'triggered':True,'priority':'MEDIUM','rapid_attention':True,'turnover_burst':None},False))
rows.append(case('F203_high_only',[bar(0,100),bar(1,100.10,open_=100,high=102.20,low=99.90)],{'triggered':False,'primary_scenario':'SPIKE_REVERSAL','error':'DIAGNOSTIC_ONLY'}))
rows.append(case('F204_accel',[bar(0,100),bar(1,100.40),bar(2,100.99),bar(3,101.83,open_=100.99,high=101.95,low=100.9,amt='6000000')],{'triggered':True,'primary_scenario':'MOMENTUM_ACCELERATION','momentum_acceleration':True}))
rows.append(case('F205_decel',[bar(0,100),bar(1,100.85),bar(2,101.50),bar(3,102.00)],{'triggered':True,'momentum_acceleration':False}))
rows.append(case('F206_mixed',[bar(0,100),bar(1,101),bar(2,100.7),bar(3,102)],{'triggered':True,'momentum_acceleration':False}))
rows.append(case('F207_lunch',[bar(0,100,at=datetime(2026,10,9,11,28,tzinfo=TZ)),bar(1,100.5,at=datetime(2026,10,9,11,29,tzinfo=TZ)),bar(2,101.1,at=datetime(2026,10,9,13,0,tzinfo=TZ)),bar(3,101.55,at=datetime(2026,10,9,13,1,tzinfo=TZ))],{'triggered':False,'momentum_acceleration':False}))
rows.append(case('F208_breakout',flat20()+[bar(20,100.56,open_=100,high=100.65,low=99.95)],{'triggered':True,'primary_scenario':'VOLUME_BREAKOUT','trigger_kinds':['BREAKOUT']}))
w=flat20(); w[4]['low']='98';rows.append(case('F209_wide',w+[bar(20,100.56,open_=100,high=100.65,low=99.95)],{'triggered':False}))
rows.append(case('F210_no_baseline',flat20()+[bar(20,100.56,open_=100,high=100.65,low=99.95)],{'triggered':False,'diagnostics':['BREAKOUT_UNVERIFIED']},False))
rows.append(case('F211_19bars',flat20()[1:]+[bar(20,100.56,open_=100,high=100.65,low=99.95)],{'triggered':False}))
gap=flat20(); gap[10]['bar_start_at']=(base+timedelta(minutes=12)).isoformat();gap[10]['bar_end_at']=(base+timedelta(minutes=13)).isoformat();rows.append(case('F212_gap',gap+[bar(20,100.56,open_=100,high=100.65,low=99.95)],{'triggered':False}))
rows.append(case('F213_exact_boundary',flat20()+[bar(20,Decimal('100.25')*Decimal('1.001'),open_=100,high=100.5,low=99.95)],{'triggered':False}))
border=flat20();
for b in border: b['high']='100.05'
rows.append(case('F214_breakout_boundary',border+[bar(20,100.25,open_=100,high=100.3,low=99.95,amt='2000000')],{'triggered':True,'primary_scenario':'VOLUME_BREAKOUT','turnover_burst':'2'}))
rows.append(case('F215_reversal_only',[bar(0,100),bar(1,100.1,open_=100,high=102.2,low=99.9)],{'triggered':False,'primary_scenario':'SPIKE_REVERSAL'}))
rows.append(case('F216_reversal_triggered',[bar(0,100),bar(1,100.95,open_=100,high=102.3,low=99.9)],{'triggered':True,'priority':'LOW','force_weakening':True,'primary_scenario':'SPIKE_REVERSAL'}))
h=flat20();h[-3]['close']='99.6';h[-3]['low']='99.4';h[-2]['close']='99.8';h[-2]['low']='99.6';h[-1]['close']='100';
rows.append(case('F217_veto_raw_high',h+[bar(20,101.90,open_=100,high=103,low=99,amt='9000000')],{'triggered':True,'priority':'LOW','force_weakening':True,'raw_score_min':65}))
rows.append(case('F219_both',flat20()+[bar(20,101.9,open_=100,high=102,low=99.95)],{'triggered':True,'primary_scenario':'VOLUME_BREAKOUT','scenario_contains':['RAPID_RISE','VOLUME_BREAKOUT']}))
rows.append(case('F222_midday',[bar(0,100,at=datetime(2026,10,9,11,30,tzinfo=TZ)),bar(1,101.2,at=datetime(2026,10,9,11,31,tzinfo=TZ))],{'triggered':False,'error':'INVALID_BAR'}))
rows.append(case('F223_partial',[bar(0,100),bar(1,102,is_final=False)],{'triggered':False,'error':'INVALID_BAR'}))
late=case('F224_late',[bar(0,100),bar(1,102)],{'triggered':False,'error':'STALE_BAR'});late['now']=(datetime.fromisoformat(late['now'])+timedelta(minutes=2)).isoformat();rows.append(late)
rows.append(case('F111_low_amount',[bar(0,100),bar(1,102,open_=100,amt='999999')],{'triggered':False,'error':'LOW_TURNOVER'}))
(ROOT/'fixtures/four_scenario_full_bars.json').write_text(json.dumps({'note':'All records are fictional SIMULATION finalized 1m bars; no backtested alpha claim.','cases':rows},ensure_ascii=False,indent=2)+'\n')
print('fixture cases',len(rows))
