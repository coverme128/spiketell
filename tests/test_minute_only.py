"""Full synthetic minute bars for M101–M114; M113 requires real sessions."""
import asyncio
import json
from datetime import timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.domain.engine import Engine
from app.domain.market import timestamp
from app.domain.rules import evaluate
from app.repo.store import dump, Store
from app.verification import stock_verification, baseline_summary
from app.runtime import Runtime
from tests.test_engine import advance, latest
from tests.test_live_delivery import quote_value


def bars(closes=('100','101.9'), start='2026-10-09T10:00:00+08:00'):
    result=[]
    for i,close in enumerate(closes):
        at=timestamp(start)+timedelta(minutes=i);previous=closes[max(0,i-1)]
        result.append({'symbol':'SH.600000','bar_start_at':at.isoformat(),'bar_end_at':(at+timedelta(minutes=1)).isoformat(),
            'received_at':(at+timedelta(minutes=1,seconds=10)).isoformat(),'source':'SYNTHETIC_MINUTE_ONLY','quality':'VALID','is_final':True,
            'open':previous,'close':close,'high':str(max(Decimal(previous),Decimal(close))),'low':str(min(Decimal(previous),Decimal(close))),
            'amount_cny':'6000000','volume_shares':60000})
    return result


def ingest(store,values,baseline=None):
    e=Engine(store,mode='SIMULATION')
    with store.transaction() as db:db.execute('INSERT OR IGNORE INTO watchlist VALUES (?,1,?,?)',('SH.600000',values[0]['bar_start_at'],values[0]['bar_start_at']))
    for b in values:e.ingest(b,timestamp(b['received_at']),allow_signals=True,notify=True,baseline=baseline or [])
    return e


def test_M101_M105_cold_rapid_is_explained_without_high(store):
    values=bars();e=ingest(store,values);ep=latest(store)
    assert ep['priority']=='MEDIUM' and ep['score']==30
    assert ep['signal']['turnover_burst'] is None
    assert any('RAPID_PRICE_ATTENTION' in s for s in e.card(ep)['reasons'])
    assert '成交基准积累中' in e.card(ep)['risks']
    assert [r[0] for r in store.rows('SELECT kind FROM alert_outbox')]==['RAPID_NEW']


def test_M102_peak_only_diagnostic_has_no_episode(store):
    values=bars(('100','100.1'));values[-1]['high']='102'
    ingest(store,values)
    assert not store.rows('SELECT * FROM episodes') and not store.rows('SELECT * FROM alert_outbox')
    assert json.loads(store.rows('SELECT payload FROM bar_decisions ORDER BY bar_start_at DESC LIMIT 1')[0][0])['force_weakening']


def test_M103_three_minute_continuation_is_not_fake_acceleration():
    values=bars(('100','101','101.69','102.1'))
    result=evaluate(values,[],values[-1]['received_at'])
    assert result['triggered'] and 'PRICE_3M' in result['trigger_kinds']
    assert not result['momentum_acceleration']


def test_M104_first_open_minute_does_not_borrow_previous_close():
    values=bars(('101.9',),start='2026-10-09T09:30:00+08:00')
    result=evaluate(values,[],values[-1]['received_at'])
    assert result['error']=='INSUFFICIENT_CONTIGUOUS_BARS' and not result['triggered']


def test_M106_long_wick_disables_rapid_override():
    values=bars();values[-1]['high']='105'
    result=evaluate(values,[],values[-1]['received_at'])
    assert not result['rapid_attention'] and result['priority']=='LOW'


def test_M107_M108_M114_same_episode_upgrade_and_restart(store):
    values=bars();e=ingest(store,values);id=latest(store)['episode_id'];bar=values[-1]
    for _ in range(2):
        bar=advance(bar,str(Decimal(bar['close'])*Decimal('1.019')))
        e.ingest(bar,timestamp(bar['received_at']),allow_signals=True,notify=True,baseline=[])
    assert latest(store)['episode_id']==id
    assert [r[0] for r in store.rows('SELECT kind FROM alert_outbox')]==['RAPID_NEW']
    for _ in range(2):
        bar=advance(bar,str(Decimal(bar['close'])*Decimal('1.019')))
        e.ingest(bar,timestamp(bar['received_at']),allow_signals=True,notify=True,baseline=['1000000']*5)
    assert latest(store)['priority']=='HIGH'
    assert sorted(r[0] for r in store.rows('SELECT kind FROM alert_outbox'))==['HIGH_UPGRADE','RAPID_NEW']
    reopened=Store(store.path)
    try:
        assert Engine(reopened).ingest(bar,timestamp(bar['received_at']),allow_signals=True,notify=True)=='DUPLICATE'
        assert len(reopened.rows('SELECT * FROM alert_outbox'))==2
    finally:reopened.close()


@pytest.mark.parametrize('start',['2026-10-09T11:30:00+08:00','2026-10-09T14:57:00+08:00'])
def test_M109_noncontinuous_bar_is_rejected(start):
    values=bars(start=start)
    assert evaluate(values,[],values[-1]['received_at'])['error']=='INVALID_BAR'


@pytest.mark.parametrize('delay',[120,1200])
def test_M110_backfill_never_alerts(store,delay):
    values=bars();e=Engine(store)
    for b in values:assert e.ingest(b,timestamp(b['bar_end_at'])+timedelta(seconds=delay),allow_signals=True,notify=True)=='EVIDENCE_ONLY'
    assert not store.rows('SELECT * FROM alert_outbox')


def test_M111_low_turnover_not_rapid():
    values=bars();values[-1]['amount_cny']='999999'
    assert evaluate(values,[],values[-1]['received_at'])['error']=='LOW_TURNOVER'


def test_user_input_to_preparation_capacity_to_current_minute_detection(tmp_path,monkeypatch):
    # Real production HTTP add route + preparation + runtime scheduler, with
    # explicitly injected sources/clock. This does not certify actual live feed.
    from app.providers.akshare import FetchResult
    at=timestamp('2026-10-09T10:00:10+08:00')
    for module in ('app.main','app.runtime','app.preparation','app.verification'):
        monkeypatch.setattr(module+'.now',lambda:at)
    monkeypatch.setenv('RADAR_MODE','LIVE');monkeypatch.setenv('RADAR_EVIDENCE',str(tmp_path/'empty.json'))
    # Prevent independent background tasks while manually advancing production steps.
    async def idle(self):await asyncio.Event().wait()
    monkeypatch.setattr('app.operations.Operations.run',idle);monkeypatch.setattr('app.calibration.Calibration.run',idle);monkeypatch.setattr('app.runtime.Runtime.run',idle)
    with TestClient(create_app(tmp_path/'flow.sqlite3',scheduler=True)) as client:
        rt=client.app.state.runtime
        ev={'calendar':{'source':'INJECTED','checked_at':at.isoformat(),'valid_from':'2025-01-01','valid_to':'2026-12-31','trading_dates':['2026-10-09']},'clock':{'source':'INJECTED','checked_at':at.isoformat(),'offset_seconds':0}}
        for k,v in ev.items():rt.store.save_evidence(k,v)
        async def transport(key,fn,symbol):
            if key.startswith(('metadata:',)):return quote_value(at)
            return []
        monkeypatch.setattr(rt.preparation.transport,'call',transport)
        response=client.post('/api/v1/watchlist',json={'symbols':['600000']})
        assert response.json()['items'][0]['status']=='ADDED'
        client.post('/api/v1/watchlist/SH.600000/prepare')
        assert client.get('/api/v1/setup').json()['eligible_watch_count']==1
        assert client.get('/api/v1/setup').json()['baseline_status']=='UNAVAILABLE'
        values=bars(('100',),start='2026-10-09T09:59:00+08:00')
        async def fetch(*args):return FetchResult(bars=values,coverage={'SH.600000':len(values)},lag={'SH.600000':10})
        monkeypatch.setattr('app.providers.live.LiveProvider.fetch_final_bars',fetch)
        # M112: unknown minute semantics must block even with rights acknowledged.
        client.post('/api/v1/setup/source',json={'personal_use_confirmed':True})
        asyncio.run(rt.poll())
        assert not rt.store.rows('SELECT * FROM minute_bars')
        snapshot=client.get('/api/v1/watchlist/SH.600000/verification').json()
        assert 'UNKNOWN_TIMESTAMP_SEMANTICS' in snapshot['blockers']
        provider=rt.store.evidence('provider');provider.update(timestamp_semantics='end',timestamp_samples=['INJECTED_A','INJECTED_B'],finalization_verified=True,capacity_verified=False)
        rt.store.save_evidence('provider',provider)
        # Three measured rounds, then a new strong minute; no need for history to be HIGH-ready.
        for i in range(4):
            if i:
                at+=timedelta(minutes=1)
                values=[advance(values[-1],'101.9' if i==3 else '100')]
            rt.started=at;rt.start_mono=__import__('time').monotonic()
            asyncio.run(rt.poll())
        result=client.get('/api/v1/watchlist/SH.600000/verification').json()
        assert result['state']=='DETECTING' and result['latest_final_bar']['close']=='101.9'
        assert result['latest_decision']['details']['priority']=='MEDIUM'
        assert result['latest_decision']['details']['turnover_burst'] is None
        radar=client.get('/api/v1/radar').json()
        assert radar['top_cards'][0]['symbol']=='SH.600000'
        event=json.loads(rt.store.rows('SELECT payload FROM episode_events ORDER BY sequence DESC LIMIT 1')[0][0])
        assert event['alert_kind']=='RAPID_NEW' and event['delivery_mode']=='LIVE'
        assert client.get('/api/v1/watchlist/SZ.000001/verification').status_code==404


def test_restricted_before_calendar_is_retried_same_day(store,monkeypatch):
    from app.preparation import Preparation
    at=timestamp('2026-10-09T10:00:00+08:00')
    monkeypatch.setattr('app.preparation.now',lambda:at)
    prep=Preparation(store,lambda:{})
    with store.transaction() as db:
        db.execute('INSERT INTO watchlist VALUES (?,1,?,?)',('SH.600000',at.isoformat(),at.isoformat()))
        db.execute('INSERT INTO preparation VALUES (?,?)',('SH.600000',dump({'state':'RESTRICTED','metadata_checked_date':at.date().isoformat(),'updated_at':(at-timedelta(minutes=6)).isoformat()})))
    called=[]
    async def prepare(symbol):called.append(symbol)
    monkeypatch.setattr(prep,'prepare',prepare)
    asyncio.run(prep.refresh_due())
    assert called==['SH.600000']


def test_zero_amount_history_does_not_count_as_ready(store):
    rt=Runtime(store)
    with store.transaction() as db:
        for date in ('2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-25'):
            db.execute('INSERT INTO baseline_amounts VALUES (?,?,?,?,?,?,?)',('SH.600000',date,'10:00','sina/minute','0','2026-10-09T10:00:00+08:00','end'))
    assert rt.preparation.baseline_status('SH.600000',timestamp('2026-10-09T10:01:00+08:00'))['slots_with_five_days']==0


def test_price_regime_warning_survives_metadata_refresh_until_history_recheck(store,monkeypatch):
    from app.preparation import Preparation
    at=timestamp('2026-10-09T10:00:00+08:00');history_close='8'
    monkeypatch.setattr('app.preparation.now',lambda:at)
    prep=Preparation(store,lambda:{'calendar':{'valid_from':'2025-01-01','trading_dates':['2026-10-08','2026-10-09']},'provider':{'history_timestamp_semantics':'end'}})
    async def fetch(key,fn,symbol):
        if key.startswith('metadata:'):return quote_value(at)
        return [{'day':'2026-10-08 15:00:00','close':history_close,'amount':'1000000'}]
    monkeypatch.setattr(prep.transport,'call',fetch)
    asyncio.run(prep.prepare('SH.600000'))
    assert json.loads(store.rows('SELECT payload FROM instruments')[0][0])['baseline_warning']=='PRICE_REGIME_CHANGED'
    asyncio.run(prep.prepare('SH.600000'))
    assert json.loads(store.rows('SELECT payload FROM instruments')[0][0])['baseline_warning']=='PRICE_REGIME_CHANGED'
    history_close='10'
    asyncio.run(prep.prepare('SH.600000',force=True))
    assert 'baseline_warning' not in json.loads(store.rows('SELECT payload FROM instruments')[0][0])


def test_baseline_summary_counts_qualified_watchlist_and_full_prior_slots(store):
    from app.providers.public import instrument
    from app.measurements import minutes
    at=timestamp('2026-10-09T10:00:00+08:00');rt=Runtime(store)
    meta=instrument('SH.600000',quote_value(at),at,{'valid_from':'2025-01-01'})
    with store.transaction() as db:
        db.execute('INSERT INTO instruments VALUES (?,?)',('SH.600000',dump(meta)))
        db.execute('INSERT INTO watchlist VALUES (?,1,?,?)',('SH.600000',at.isoformat(),at.isoformat()))
        db.execute('INSERT INTO watchlist VALUES (?,1,?,?)',('SZ.000001',at.isoformat(),at.isoformat()))
    initial=baseline_summary(rt,at)
    assert initial['enabled_watch_count']==2 and initial['eligible_watch_count']==1 and initial['baseline_ready_count']==0
    with store.transaction() as db:
        for end in minutes(at.date()):
            slot=(end-timedelta(minutes=1)).strftime('%H:%M')
            for date in ('2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-25'):
                db.execute('INSERT INTO baseline_amounts VALUES (?,?,?,?,?,?,?)',('SH.600000',date,slot,'sina/minute','1000000',at.isoformat(),'end'))
    ready=baseline_summary(rt,at)
    assert ready['baseline_status']=='READY' and ready['baseline_ready_count']==1 and ready['eligible_watch_count']==1
