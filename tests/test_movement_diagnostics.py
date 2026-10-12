import copy
import json
import pytest
from app.movement_diagnostics import replay, movement, trace
from app.domain.market import timestamp
from app.domain.rules import evaluate
from tests.test_api import client


def test_replay_same_rules_no_mutation(engine,store,case):
    bar=case['bars'][-1];engine.ingest(bar,timestamp(case['now']),allow_signals=True,baseline=[])
    before=list(store.db.iterdump())
    r=replay(store,bar['symbol'],bar['bar_start_at'][:10],case['bars'][0]['bar_start_at'][11:16],bar['bar_end_at'][11:16])
    last=r['minutes'][-1]
    assert last['replay']==evaluate(case['bars'],[],bar['bar_end_at'])
    assert last['actual_trace']['engine_trace']['episode_id']
    assert list(store.db.iterdump())==before
    assert r['minutes'][0]['actual_reason']=='BEFORE_MONITOR_START'


def test_missing_not_no_movement(store):
    r=replay(store,'SZ.300124','2026-10-12','09:30','09:33')
    assert r['coverage']=={'expected':3,'present':0,'missing':3}
    assert all(m['actual_reason']=='DATA_MISSING' for m in r['minutes'])


def test_candidate_threshold():
    assert not movement({'triggered':False,'diagnostics':[]})
    assert movement({'triggered':True,'priority':'LOW'})
    assert movement({'diagnostics':['BREAKOUT_UNVERIFIED']})


def test_no_receipt_never_sent(engine,store,case):
    b=case['bars'][-1];s=engine.ingest(b,timestamp(case['now']),allow_signals=True,notify=True,baseline=case['prior_same_slot_amounts'])
    t=trace(store,b['symbol'],b['bar_start_at'],s)
    assert t['reason_code']=='DELIVERY_UNCONFIRMED'
    event=t['events'][0]
    with store.transaction() as db:
        db.execute('INSERT INTO notification_receipts VALUES (?,?,?,?,?)',(event['event_id'],'OS_FAILED',case['now'],case['now'],'0'))
    assert trace(store,b['symbol'],b['bar_start_at'],s)['reason_code']=='ALERT_DELIVERY_FAILED'
    assert engine.ingest(b,timestamp(case['now']),allow_signals=True,notify=True)=='DUPLICATE'
    assert len(store.rows('SELECT * FROM alert_outbox'))==1


def test_diagnostic_api_validation_and_no_start(client):
    assert client.get('/api/v1/movement-diagnostics',params={'symbol':'300124','date':'2026-10-12','start':'bad'}).status_code==422
    result=client.get('/api/v1/movement-diagnostics',params={'symbol':'300124','date':'2026-10-12'}).json()
    assert result['mode']=='HISTORICAL_REPLAY_NOT_LIVE'
    assert client.get('/api/v1/radar').json()['movements']['health']['state']=='NOT_STARTED'
