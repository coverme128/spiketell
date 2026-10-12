"""Read-only observability. Replay calls production evaluate, never Engine.ingest."""
import json
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from app.config import PROFILE
from app.domain.rules import evaluate, has_contiguous_tail


def movement(signal):
    return bool(signal.get('triggered') or signal.get('force_weakening') or signal.get('diagnostics'))


def classification(signal):
    if not movement(signal): return 'TRIGGER_NOT_MET'
    if not signal.get('is_attention_eligible'): return 'CANDIDATE_FILTERED'
    return 'QUALIFIED'


def amounts(store, symbol, start):
    values = {}
    for r in store.rows("SELECT payload FROM minute_bars WHERE symbol=? AND bar_start_at<? AND substr(bar_start_at,12,5)=? ORDER BY revision", (symbol,start[:10],start[11:16])):
        b=json.loads(r[0]); values[b['bar_start_at'][:10]]=b['amount_cny']
    for r in store.rows("SELECT session_date,amount_cny FROM baseline_amounts WHERE symbol=? AND session_date<? AND slot=? AND semantics IN ('start','end') ORDER BY session_date DESC",(symbol,start[:10],start[11:16])):
        values.setdefault(r[0],r[1])
    meta=store.rows('SELECT payload FROM instruments WHERE symbol=?',(symbol,))
    if meta and json.loads(meta[0][0]).get('baseline_warning')=='PRICE_REGIME_CHANGED': return []
    return [values[d] for d in sorted(values,reverse=True)]


def trace(store, symbol, start, signal):
    events=[json.loads(r[0]) for r in store.rows('SELECT payload FROM episode_events WHERE bar_start_at=?',(start,))]
    events=[e for e in events if e['symbol']==symbol]
    receipts=[dict(r) for e in events for r in store.rows('SELECT * FROM notification_receipts WHERE event_id=?',(e['event_id'],))]
    kinds={r['kind'] for r in receipts}
    alerts=[e for e in events if e.get('alert_kind')]
    code=classification(signal)
    if alerts:
        code=('ALERT_SENT' if 'OS_SHOWN' in kinds else 'ALERT_DELIVERY_FAILED' if 'OS_FAILED' in kinds else 'ALERT_SUPPRESSED' if 'OS_SUPPRESSED' in kinds else 'DELIVERY_UNCONFIRMED')
    elif code=='QUALIFIED': code='EPISODE_SUPPRESSED' if not events else 'ALERT_SUPPRESSED'
    return {'reason_code':code,'events':events,'receipts':receipts,'alert_decisions':len(alerts),
            'delivery_evidence':'browser_onshow' if 'OS_SHOWN' in kinds else 'unconfirmed',
            'engine_trace':signal.get('processing_trace'),'historical_trace_inferred':not bool(signal.get('processing_trace'))}


def replay(store, symbol, date, start='09:30', end='11:03'):
    import re
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) or any(not re.fullmatch(r'\d{2}:\d{2}',v) for v in (start,end)): raise ValueError('INVALID_TIME_RANGE')
    left=datetime.fromisoformat(f'{date}T{start}:00+08:00'); right=datetime.fromisoformat(f'{date}T{end}:00+08:00')
    if right<=left or right-left>timedelta(days=1): raise ValueError('INVALID_TIME_RANGE')
    bars={}
    for r in store.rows('SELECT payload FROM minute_bars WHERE symbol=? AND bar_start_at>=? AND bar_start_at<? ORDER BY bar_start_at,revision',(symbol,date,right.isoformat())):
        b=json.loads(r[0]);bars[b['bar_start_at']]=b
    saved={r[0]:json.loads(r[1]) for r in store.rows('SELECT bar_start_at,payload FROM bar_decisions WHERE symbol=? AND bar_start_at LIKE ?',(symbol,date+'%'))}
    first=min(saved,default=None)
    output=[];at=left
    while at<right:
        slot=at.isoformat();at+=timedelta(minutes=1)
        if not ('09:30'<=slot[11:16]<'11:30' or '13:00'<=slot[11:16]<'14:57'):continue
        bar=bars.get(slot)
        if not bar:
            output.append({'bar_start_at':slot,'actual_reason':'DATA_MISSING','bar':None});continue
        window=[bars[k] for k in sorted(bars) if k<=slot];base=amounts(store,symbol,slot)
        signal=evaluate(window,base,bar['bar_end_at'])
        returns={f'ret{n}_pct':str((Decimal(bar['close'])/Decimal(window[-n-1]['close'])-1)*100) if has_contiguous_tail(window,n+1) else None for n in (1,3,5)}
        prev=[]
        for i in range(max(1,len(window)-11),len(window)-1):
            if has_contiguous_tail(window[:i+1],2):prev.append(abs(float(Decimal(window[i]['close'])/Decimal(window[i-1]['close'])-1)*100))
        actual=saved.get(slot)
        reason=trace(store,symbol,slot,actual)['reason_code'] if actual else 'BEFORE_MONITOR_START' if first and slot<first else 'DATA_STALE' if (datetime.fromisoformat(bar['received_at'])-datetime.fromisoformat(bar['bar_end_at'])).total_seconds()>PROFILE['max_bar_age_seconds'] else 'NO_RECORDED_DECISION'
        output.append({'bar_start_at':slot,'bar':bar,**returns,'previous_10_abs_return_median_pct':median(prev) if prev else None,
          'turnover_minimum_met':Decimal(bar['amount_cny'])>=Decimal(PROFILE['min_turnover_cny']),
          'baseline_valid_sessions':sum(Decimal(v)>0 for v in base),'baseline_valid':sum(Decimal(v)>0 for v in base)>=PROFILE['volume_baseline']['min_previous_sessions'],
          'replay':signal,'candidate':movement(signal),'qualified_scenarios':signal['matched_scenarios'],
          'data_stale_at_receive':(datetime.fromisoformat(bar['received_at'])-datetime.fromisoformat(bar['bar_end_at'])).total_seconds()>PROFILE['max_bar_age_seconds'],
          'actual_reason':reason,'actual_decision':actual,'actual_trace':trace(store,symbol,slot,actual) if actual else None,
          'conditions':{'profile':PROFILE['trigger'],'rapid_attention':PROFILE['rapid_attention'],'scenario_requirements':PROFILE['scenarios'],'rejection':signal['error'],'risks':signal['risks']}})
    maxima={}
    for n in (1,3,5):
        available=[r for r in output if r.get(f'ret{n}_pct') is not None]
        best=max(available,key=lambda r:Decimal(r[f'ret{n}_pct']),default=None)
        maxima[f'max_{n}m']=None if best is None else {'pct':best[f'ret{n}_pct'],'bar_end_at':best['bar']['bar_end_at']}
    return {'symbol':symbol,'date':date,'interval':'bar_start >= start; bar_end <= end','start':start,'end':end,'mode':'HISTORICAL_REPLAY_NOT_LIVE','rule_version':PROFILE['rule_version'],'first_actual_decision_bar_start':first,
      'baseline_caveat':'Uses currently retained verified prior-date evidence; original decision is authoritative for historical baseline state.',
      'coverage':{'expected':len(output),'present':sum(r['bar'] is not None for r in output),'missing':sum(r['bar'] is None for r in output)},**maxima,'minutes':output}


def overview(runtime, date):
    store=runtime.store;items=[]
    for r in store.rows('SELECT symbol,bar_start_at,payload FROM bar_decisions WHERE bar_start_at LIKE ? ORDER BY bar_start_at DESC',(date+'%',)):
        signal=json.loads(r[2])
        if not movement(signal):continue
        t=trace(store,r[0],r[1],signal)
        meta=store.rows('SELECT payload FROM instruments WHERE symbol=?',(r[0],))
        items.append({'symbol':r[0],'name':json.loads(meta[0][0]).get('name',r[0]) if meta else r[0], 'bar_start_at':r[1],
          'scenarios':signal['matched_scenarios'] or signal['diagnostics'],'ret1_pct':signal['ret1_pct'],'ret3_pct':signal['ret3_pct'],
          'priority':signal['priority'],'state':t['reason_code'],'reason':'；'.join(signal['risks']) or ('历史成交基准不足，放量未确认' if 'BREAKOUT_UNVERIFIED' in signal['diagnostics'] else '评分未达到关注等级' if not signal['is_attention_eligible'] else '已达到关注资格；Episode 合并或通知状态见追踪'),
          'qualified':bool(signal['matched_scenarios']),'trace':t})
    feed=runtime.feed();first=store.rows('SELECT MIN(bar_start_at) FROM bar_decisions WHERE bar_start_at LIKE ?',(date+'%',))[0][0]
    started=None
    if first:
        row=store.rows('SELECT payload FROM bar_decisions WHERE bar_start_at=? LIMIT 1',(first,))
        started=json.loads(row[0][0]).get('processing_trace',{}).get('recorded_at')
        if not started:
            row=store.rows('SELECT payload FROM minute_bars WHERE bar_start_at=? ORDER BY revision LIMIT 1',(first,))
            started=json.loads(row[0][0])['received_at'] if row else None
    receipts={r[0]:r[1] for r in store.rows('SELECT kind,COUNT(*) FROM notification_receipts WHERE received_at LIKE ? GROUP BY kind',(date+'%',))}
    missing=store.rows("SELECT COUNT(*) FROM minute_coverage WHERE bar_end_at LIKE ? AND eligibility='EXPECTED' AND valid_received_at IS NULL",(date+'%',))[0][0]
    absent=store.rows("SELECT COUNT(*) FROM minute_coverage c WHERE c.bar_end_at LIKE ? AND c.eligibility='EXPECTED' AND NOT EXISTS (SELECT 1 FROM minute_bars b WHERE b.symbol=c.symbol AND json_extract(b.payload,'$.bar_end_at')=c.bar_end_at)",(date+'%',))[0][0]
    status='NOT_STARTED' if not first else 'OUTSIDE_SESSION' if feed['session'] not in ('CONTINUOUS','UNKNOWN') else 'DATA_UNAVAILABLE' if feed['status']=='STOPPED' else 'DATA_DELAYED' if feed['status']!='HEALTHY' else 'MOVEMENTS_FOUND' if items else 'NO_MOVEMENT'
    return {'items':items,'health':{'state':status,'first_decision_bar_start':first,'monitor_started_at':started,'monitor_start_evidence':'decision time or original bar receipt proxy; not process boot','expected_stocks':feed['monitored_count'],'valid_stocks':feed['available_count'], 'latest_bar_end_at':feed['last_bar_end_at'],'feed_status':feed['status'],'feed_reasons':feed['reasons'],'missing_stock_minutes':absent,'uncovered_stock_minutes':missing,'coverage_definition':'expected stock-minutes since watchlist addition; uncovered includes delayed receipts and pre-monitor calibration',
       'candidate_count':len(items),'qualified_count':sum(i['qualified'] for i in items),'count_unit':'stock-minute; not episodes',
       'high_alert_count':store.rows("SELECT COUNT(*) FROM alert_outbox WHERE created_at LIKE ? AND kind IN ('HIGH_NEW','HIGH_UPGRADE')",(date+'%',))[0][0], 'notification_receipts':receipts,'notification_state':'DELIVERY_FAILED' if receipts.get('OS_FAILED',0)>receipts.get('OS_SHOWN',0) else 'NO_FAILURE_RECEIPT'}}
