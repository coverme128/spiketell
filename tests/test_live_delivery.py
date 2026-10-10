import asyncio
import copy
import json
import sqlite3
from datetime import timedelta

import pytest

from app.calibration import Calibration
from app.domain.market import timestamp
from app.measurements import record_expected, record_valid, report, minutes
from app.preparation import Preparation
from app.providers.live import Finalizer
from app.providers.public import SourceError, instrument, get_text
from app.repo.store import Store, dump


def test_migrates_existing_v1_without_losing_watchlist(tmp_path):
    path = tmp_path/'old.sqlite3'
    from app.config import ROOT
    db = sqlite3.connect(path)
    db.executescript((ROOT/'app/repo/migrations/001_initial.sql').read_text())
    db.execute('INSERT INTO watchlist VALUES (?,1,?,?)',('SH.600000','2026-10-09T09:00:00+08:00','2026-10-09T09:00:00+08:00'))
    db.commit();db.close()
    migrated = Store(path)
    assert migrated.rows('SELECT symbol FROM watchlist')[0][0]=='SH.600000'
    assert [r[0] for r in migrated.rows('SELECT version FROM schema_versions ORDER BY version')]==[1,2,3,4]
    migrated.close()
    reopened = Store(path)
    assert len(reopened.rows('SELECT * FROM watchlist'))==1
    reopened.close()


def test_finalization_requires_post_close_stability_and_resets_on_revision(case):
    bar = case['bars'][-1]
    end = timestamp(bar['bar_end_at'])
    finalizer = Finalizer()
    assert finalizer.accept([bar],end+timedelta(seconds=2))==[]
    assert finalizer.accept([bar],end+timedelta(seconds=8))==[]
    assert finalizer.accept([bar],end+timedelta(seconds=12))==[]
    changed = {**bar,'amount_cny':'4000001'}
    assert finalizer.accept([changed],end+timedelta(seconds=13))==[]
    assert finalizer.accept([changed],end+timedelta(seconds=18))==[changed]
    assert Finalizer().accept([changed],end+timedelta(seconds=25))==[]


def quote_value(at):
    return {'f57':'600000','f58':'浦发银行','f189':19991110,'f51':11,'f52':9,'f86':int(at.timestamp()),'f47':1000,'f60':10,'f43':10.1,'f48':100000}


@pytest.mark.parametrize('name,risk',[('浦发银行','NORMAL'),('*ST测试','ST'),('退市测试','DELISTED'),('N测试','NEW')])
def test_instrument_real_fields_and_risk_restrictions(name,risk):
    at = timestamp('2026-10-09T10:00:00+08:00')
    raw = quote_value(at);raw['f58']=name
    meta = instrument('SH.600000',raw,at,{'valid_from':'2025-01-01'})
    assert meta['risk_status']==risk
    assert meta['list_date']=='1999-11-10'
    assert meta['limits_verified'] and meta['suspended'] is False


def test_yesterdays_quote_cannot_certify_today_trading():
    at = timestamp('2026-10-10T10:00:00+08:00')
    meta = instrument('SH.600000',quote_value(at-timedelta(days=1)),at,{'valid_from':'2025-01-01'})
    assert meta['suspended'] is None and not meta['limits_verified']


def test_oversized_response_and_429_are_bounded(monkeypatch):
    class Response:
        status_code=200
        headers={}
        closed=False
        def iter_content(self):yield b'x'*20
        def close(self):self.closed=True
    response=Response()
    monkeypatch.setattr('app.providers.public.requests.get',lambda *a,**k:response)
    with pytest.raises(SourceError,match='RESPONSE_TOO_LARGE'):get_text('https://example.invalid',limit=10)
    assert response.closed
    response.status_code=429;response.headers={'Retry-After':'120'}
    with pytest.raises(SourceError) as error:get_text('https://example.invalid')
    assert error.value.code=='PROVIDER_RATE_LIMITED' and error.value.retry_after==120


def test_unknown_history_cannot_become_high_baseline(engine,store,case):
    bar = case['bars'][-1]
    with store.transaction() as db:
        for date in ('2026-09-30','2026-09-29','2026-09-28','2026-09-24','2026-09-23'):
            db.execute('INSERT INTO baseline_amounts VALUES (?,?,?,?,?,?,?)',(bar['symbol'],date,bar['bar_start_at'][11:16],'sina/minute','1000000',case['now'],'UNKNOWN'))
    signal = engine.ingest(bar,timestamp(case['now']),allow_signals=True)
    assert signal['turnover_burst'] is None and signal['priority']!='HIGH'


def test_qualified_history_supplies_real_baseline_without_fake_ohlc(engine,store,case):
    bar = case['bars'][-1]
    with store.transaction() as db:
        for date in ('2026-09-30','2026-09-29','2026-09-28','2026-09-24','2026-09-23'):
            db.execute('INSERT INTO baseline_amounts VALUES (?,?,?,?,?,?,?)',(bar['symbol'],date,bar['bar_start_at'][11:16],'sina/minute','1000000',case['now'],'end'))
    signal = engine.ingest(bar,timestamp(case['now']),allow_signals=True)
    assert signal['priority']=='HIGH' and signal['turnover_burst']=='4'
    assert not store.rows("SELECT 1 FROM minute_bars WHERE bar_start_at<'2026-10-09'")


def test_expected_coverage_keeps_unknown_metadata_in_denominator(store):
    at = timestamp('2026-10-09T09:32:10+08:00')
    with store.transaction() as db:
        for s in ('SH.600000','SZ.000001'):
            db.execute('INSERT INTO watchlist VALUES (?,1,?,?)',(s,'2026-10-09T09:00:00+08:00',at.isoformat()))
    record_expected(store,at,{'trading_dates':['2026-10-09']})
    record_expected(store,at,{'trading_dates':['2026-10-09']})
    result=report(store)
    assert result['expected_eligible_symbol_minutes']==4
    assert result['valid_final_symbol_minutes']==0
    assert result['visible_alert_p95_seconds'] is None
    assert result['complete_sessions']==0 and len(list(minutes(at.date())))==237


def test_calibration_cannot_infer_from_historical_or_static_labels(store):
    at=timestamp('2026-10-09T10:00:15+08:00')
    calibration=Calibration(store,lambda:{})
    for offset in (0,10,20):
        observation=at+timedelta(seconds=offset)
        row={'时间':'2026-10-09 10:01:00','收盘':'10.1','成交量':'100','成交额':'100000'}
        calibration.observe('eastmoney','SH.600000',row,quote_value(observation),observation)
    assert not calibration.confirmed
    row['时间']='2026-10-08 10:01:00'
    calibration.observe('eastmoney','SH.600000',row,quote_value(at),at)
    assert not calibration.confirmed


def seed_calibration(calibration):
    at=timestamp('2026-10-09T10:00:15+08:00')
    for source in ('eastmoney','sina'):
        for symbol in ('SH.600000','SZ.000001'):
            for step in range(3):
                observed=at+timedelta(seconds=step*10)
                row={'时间':'2026-10-09 10:01:00','收盘':'10.1','成交量':str(100+step),'成交额':str(100000+1000*step)} if source=='eastmoney' else {'day':'2026-10-09 10:01:00','close':'10.1','volume':str(10000+100*step),'amount':str(100000+1000*step)}
                qt=quote_value(observed);qt['f48']=100000+1000*step
                calibration.observe(source,symbol,row,qt,observed)


def test_live_calibration_requires_two_sources_two_stocks_and_confirmed_close(store,monkeypatch):
    at=timestamp('2026-10-09T10:01:12+08:00')
    ev={'provider':{'personal_use_confirmed':True},'calendar':{'source':'TEST','checked_at':at.isoformat(),'valid_from':'2026-10-09','valid_to':'2026-10-09','trading_dates':['2026-10-09']},'clock':{'source':'TEST','checked_at':at.isoformat(),'offset_seconds':0}}
    calibration=Calibration(store,lambda:ev)
    seed_calibration(calibration)
    assert len(calibration.confirmed)==4
    monkeypatch.setattr('app.calibration.now',lambda:at)
    async def fetch(key,function,symbol):
        em=[{'时间':f'2026-10-09 10:0{minute}:00','开盘':'10','最高':'10.2','最低':'9.9','收盘':'10.1','成交量':'100','成交额':'100000'} for minute in (1,2)]
        if key.startswith('em:'):return em
        if key.startswith('si:'):return [{'day':r['时间'],'open':'10','high':'10.2','low':'9.9','close':'10.1','volume':'10000','amount':'100000'} for r in em]
        return quote_value(at)
    monkeypatch.setattr(calibration.transport,'call',fetch)
    asyncio.run(calibration.step())
    assert store.evidence('provider') is None
    at+=timedelta(seconds=10)
    asyncio.run(calibration.step())
    qualified=store.evidence('provider')
    assert qualified['timestamp_semantics']=='end' and qualified['history_timestamp_semantics']=='end'
    assert qualified['finalization_verified'] and not qualified['capacity_verified']
    assert len(qualified['timestamp_samples'])==4


def test_preparation_persists_real_source_amounts_without_emitting_episodes(store,monkeypatch):
    at=timestamp('2026-10-10T10:00:00+08:00')
    monkeypatch.setattr('app.preparation.now',lambda:at)
    prep=Preparation(store,lambda:{'calendar':{'valid_from':'2025-01-01','trading_dates':['2026-10-09']},'provider':{}})
    async def fetch(key,fn,symbol):
        if key.startswith('metadata'):return quote_value(at-timedelta(days=1))
        return [{'day':'2026-10-09 10:01:00','open':'10','high':'10.2','low':'9.9','close':'10.1','volume':'10000','amount':'100000'}]
    monkeypatch.setattr(prep.transport,'call',fetch)
    asyncio.run(prep.prepare('SH.600000'))
    assert prep.status('SH.600000')['state']=='WAITING_SESSION'
    assert prep.baseline_status('SH.600000',at)['historical_days']==1
    assert not prep.baseline_status('SH.600000',at)['semantics_verified']
    assert not store.rows('SELECT * FROM episodes')


def test_qualified_runtime_final_bar_to_live_event_and_repeat_dedup(engine,store,case,monkeypatch):
    from app.runtime import Runtime
    from app.providers.akshare import FetchResult
    from app.main import stream_payload
    at=timestamp(case['now']);bar=case['bars'][-1];symbol=bar['symbol']
    meta={'name':'Test','board':'MAIN','risk_status':'NORMAL','metadata_source':'TEST','checked_at':at.isoformat(),
          'suspended':False,'ordinary_a':True,'limits_verified':True,'list_date':'2000-01-01'}
    ev={'provider':{'name':'akshare','personal_use_confirmed':True,'rights_evidence':'TEST','timestamp_semantics':'end',
                    'timestamp_samples':['TEST1','TEST2'],'finalization_verified':True,'capacity_verified':True,'qualified_pool_size':1},
        'calendar':{'source':'TEST','checked_at':at.isoformat(),'valid_from':at.date().isoformat(),'valid_to':at.date().isoformat(),'trading_dates':[at.date().isoformat()]},
        'clock':{'source':'TEST','checked_at':at.isoformat(),'offset_seconds':0},'instruments':{symbol:meta}}
    monkeypatch.setattr('app.runtime.now',lambda:at);monkeypatch.setattr('app.main.now',lambda:at)
    monkeypatch.setattr('app.runtime.evidence',lambda:ev)
    rt=Runtime(store);rt.last_poll=at-timedelta(minutes=1)
    with store.transaction() as db:
        db.execute("UPDATE watchlist SET added_at='2026-10-09T09:00:00+08:00'")
        db.execute('INSERT INTO provider_health VALUES (?,?)',(symbol,dump({'bar_end_at':(at-timedelta(seconds=70)).isoformat()})))
        for day in ('2026-09-23','2026-09-24','2026-09-28','2026-09-29','2026-09-30'):
            db.execute('INSERT INTO baseline_amounts VALUES (?,?,?,?,?,?,?)',(symbol,day,bar['bar_start_at'][11:16],'sina/minute','1000000',at.isoformat(),'end'))
    async def fetch(*args):return FetchResult(bars=[bar],lag={symbol:10},coverage={symbol:1})
    monkeypatch.setattr('app.providers.live.LiveProvider.fetch_final_bars',fetch)
    asyncio.run(rt.poll());asyncio.run(rt.poll())
    assert len(store.rows('SELECT * FROM episodes'))==1
    assert len(store.rows('SELECT * FROM alert_outbox'))==1
    row=store.rows('SELECT * FROM episode_events')[0]
    payload=json.loads(row['payload'])
    assert payload['alert_kind']=='HIGH_NEW' and payload['delivery_mode']=='LIVE'
    assert '"delivery_mode":"LIVE"' in stream_payload(row,False,rt)
    assert '"delivery_mode":"REPLAY"' in stream_payload(row,True,rt)
    assert report(store)['valid_final_symbol_minutes']==1
    assert not rt.radar()['historical_cards']


def test_calibration_rejects_price_match_without_matching_trade_amount(store):
    calibration=Calibration(store,lambda:{})
    at=timestamp('2026-10-09T10:00:15+08:00')
    for step in range(3):
        current=at+timedelta(seconds=step*10)
        qt=quote_value(current);qt['f48']=100000+step*90000
        row={'时间':'2026-10-09 10:01:00','收盘':'10.1','成交量':str(100+step),'成交额':str(100000+step*1000)}
        calibration.observe('eastmoney','SH.600000',row,qt,current)
    assert not calibration.confirmed


def test_missing_visible_receipt_is_not_removed_from_delivery_report(engine,store,case):
    bar=case['bars'][-1];at=timestamp(case['now'])
    engine.ingest(bar,at,allow_signals=True,notify=True,baseline=case['prior_same_slot_amounts'])
    event_id=store.rows('SELECT event_id FROM episode_events')[0][0]
    with store.transaction() as db:
        db.execute('INSERT INTO browser_presence VALUES (?,?,1)',('test-browser',(at-timedelta(seconds=1)).isoformat()))
    result=report(store)
    assert result['expected_visible_alerts']==1 and result['missing_visible_receipts']==[event_id]
    assert not result['meets_numeric_targets'] and result['visible_alert_p95_seconds'] is None


def test_lunch_gap_does_not_hide_late_afternoon_recovery(store):
    morning=timestamp('2026-10-09T11:30:10+08:00')
    afternoon=timestamp('2026-10-09T13:05:10+08:00')
    calendar={'trading_dates':['2026-10-09']}
    record_expected(store,morning,calendar);record_expected(store,afternoon,calendar)
    assert store.rows('SELECT max_gap_seconds FROM session_observations')[0][0]>=300
