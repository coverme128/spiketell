import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.domain.market import now
from app.lock import InstanceLock
from app.main import create_app, stream_payload


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv("RADAR_EVIDENCE",str(tmp_path/'missing.json'))
    monkeypatch.setenv("RADAR_MODE","LIVE")
    with TestClient(create_app(tmp_path/'api.sqlite3',scheduler=False)) as c:
        yield c


def test_liveness_not_readiness(client):
    assert client.get('/api/v1/health/live').json()=={'up':True}
    ready=client.get('/api/v1/health/ready')
    assert ready.status_code==503
    assert ready.json()['status']=='STOPPED'
    assert client.get('/api/v1/radar').json()['top_cards']==[]


def test_batch_import_partial_and_duplicate(client):
    result=client.post('/api/v1/watchlist',json={'symbols':['600000','000001.SZ','bad','SH.000001','600000']}).json()['items']
    assert [r['status'] for r in result]==['ADDED','ADDED','REJECTED','REJECTED','ALREADY_EXISTS']
    assert result[3]['reason']=='NOT_SUPPORTED'
    assert len(client.get('/api/v1/watchlist').json())==2
    assert client.patch('/api/v1/watchlist/SH.600000',json={'enabled':False}).status_code==200
    assert not client.get('/api/v1/watchlist').json()[0]['enabled']
    for _ in range(2): assert client.delete('/api/v1/watchlist/SH.600000').status_code==204


def test_invalid_settings_and_watchlist_limits(client):
    assert client.patch('/api/v1/settings',json={'max_watchlist':100}).status_code==400
    assert client.patch('/api/v1/settings',json={'quiet_mode':'true'}).status_code==400
    assert client.patch('/api/v1/settings',json={'quiet_mode':None}).status_code==400
    assert client.patch('/api/v1/settings',json={'fake':True}).status_code==400
    assert client.patch('/api/v1/settings',json={'max_watchlist':1,'quiet_mode':True}).status_code==200
    result=client.post('/api/v1/watchlist',json={'symbols':['600000','000001']}).json()['items']
    assert result[1]['reason']=='WATCHLIST_LIMIT'
    assert client.get('/api/v1/settings').json()['quiet_mode'] is True
    assert client.post('/api/v1/watchlist',json={'symbols':[]}).status_code==400


def test_local_origin_and_host_guards(client):
    assert client.post('/api/v1/watchlist',json={'symbols':['600000']},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/v1/radar',headers={'Host':'evil.example'}).status_code==400
    assert client.get('/api/v1/radar',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403


def test_unknown_episode_and_cursor(client):
    assert client.get('/api/v1/episodes/not-here').status_code==404
    assert client.get('/api/v1/events/stream',headers={'Last-Event-ID':'abc'}).status_code==400
    assert client.get('/api/v1/events/stream',headers={'Last-Event-ID':'-1'}).status_code==400


def test_single_instance_lock(tmp_path):
    path=tmp_path/'lock';first=InstanceLock(path);second=InstanceLock(path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError,match='SCHEDULER_ALREADY_RUNNING'):second.acquire()
    finally:first.release()
    second.acquire();second.release()


def test_sse_replay_delivery_mode(client,case):
    from app.domain.market import timestamp
    rt=client.app.state.runtime
    client.post('/api/v1/watchlist',json={'symbols':[case['bars'][-1]['symbol']]})
    for bar in case['bars'][:-1]:rt.engine.ingest(bar,timestamp(case['now']))
    rt.engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,notify=True,baseline=case['prior_same_slot_amounts'])
    row=rt.store.rows('SELECT * FROM episode_events')[0]
    message=stream_payload(row,True,rt)
    assert 'event: episode' in message
    assert '"delivery_mode":"REPLAY"' in message
    assert client.get('/api/v1/episodes').json()['items'][0]['feed_health']=='STOPPED'
    detail=client.get('/api/v1/episodes/'+json.loads(row['payload'])['episode_id']).json()
    assert len(detail['bars'])==21


def test_diagnostics_exposes_blockers(client):
    diagnostics=client.get('/api/v1/diagnostics').json()
    assert diagnostics['database_check']=='ok'
    assert 'PROVIDER_RIGHTS_UNVERIFIED' in diagnostics['feed']['reasons']
    assert 'window_start' in diagnostics


def test_source_consent_does_not_bypass_timestamp_or_capacity(client):
    response=client.post('/api/v1/setup/source',json={'personal_use_confirmed':True})
    assert response.status_code==200
    assert response.json()['provider']['personal_use_confirmed'] is True
    reasons=client.get('/api/v1/health/ready').json()['reasons']
    assert 'UNKNOWN_TIMESTAMP_SEMANTICS' in reasons and 'FINALIZATION_UNVERIFIED' in reasons and 'CAPACITY_UNVERIFIED' in reasons


def test_ignore_and_full_csv_keep_episode_audit(client,case):
    from app.domain.market import timestamp
    rt=client.app.state.runtime
    client.post('/api/v1/watchlist',json={'symbols':[case['bars'][-1]['symbol']]})
    for bar in case['bars'][:-1]:rt.engine.ingest(bar,timestamp(case['now']))
    rt.engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,notify=True,baseline=case['prior_same_slot_amounts'])
    row=rt.store.rows('SELECT * FROM episode_events')[0]
    episode=json.loads(row['payload'])['episode_id']
    assert client.post('/api/v1/episodes/'+episode+'/ignore').status_code==204
    assert client.get('/api/v1/episodes/'+episode).json()['metrics']['ignored'] is True
    exported=client.get('/api/v1/episodes/export?format=csv')
    assert exported.status_code==200 and episode in exported.text and 'spike_rules_v1.0.2' in exported.text
    assert len(rt.store.rows('SELECT * FROM episode_events'))==1


def test_history_clear_requires_confirmation_and_preserves_today(client,case,monkeypatch):
    from app.domain.market import timestamp
    at=timestamp(case['now']);monkeypatch.setattr('app.main.now',lambda:at)
    rt=client.app.state.runtime
    client.post('/api/v1/watchlist',json={'symbols':[case['bars'][-1]['symbol']]})
    for bar in case['bars'][:-1]:rt.engine.ingest(bar,at)
    rt.engine.ingest(case['bars'][-1],at,allow_signals=True,baseline=case['prior_same_slot_amounts'])
    assert client.delete('/api/v1/history').status_code==400
    assert client.delete('/api/v1/history?confirm=CLEAR_PAST_HISTORY').json()['deleted_episodes']==0
    at+=timedelta(days=1)
    cleared=client.delete('/api/v1/history?confirm=CLEAR_PAST_HISTORY').json()
    assert cleared['deleted_episodes']==1
    from pathlib import Path
    assert Path(cleared['backup']).exists()
    assert rt.store.rows('SELECT * FROM minute_bars')


def test_notification_receipt_requires_verified_browser_time(client):
    assert client.post('/api/v1/notifications/receipt',json={'event_id':'a'*24,'kind':'PAGE_VISIBLE','browser_at':(now()-timedelta(minutes=1)).isoformat()}).status_code==400
    assert client.post('/api/v1/notifications/receipt',json={'event_id':'a'*24,'kind':'PAGE_VISIBLE','browser_at':now().isoformat()}).status_code==404


def test_card_amount_evidence_without_changing_frozen_card(client,case):
    from app.domain.market import timestamp
    rt=client.app.state.runtime
    client.post('/api/v1/watchlist',json={'symbols':[case['bars'][-1]['symbol']]})
    for bar in case['bars'][:-1]:rt.engine.ingest(bar,timestamp(case['now']))
    rt.engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,baseline=case['prior_same_slot_amounts'])
    result=client.get('/api/v1/episodes').json();card=result['items'][0]
    assert result['card_evidence'][card['episode_id']]['amount_cny']=='4000000'
    assert 'amount_cny' not in card


def test_simulation_database_cannot_be_opened_live(tmp_path,monkeypatch):
    path=tmp_path/'isolation.sqlite3'
    monkeypatch.setenv('RADAR_MODE','SIMULATION')
    with TestClient(create_app(path,scheduler=False)) as client:
        assert client.get('/api/v1/radar').json()['feed']['data_mode']=='SIMULATION'
    monkeypatch.setenv('RADAR_MODE','LIVE')
    with pytest.raises(RuntimeError,match='SEPARATE_DATABASES'):
        with TestClient(create_app(path,scheduler=False)):pass


def test_v102_contract_and_auditable_diagnostic_without_episode(client):
    from tests.test_scenarios_v102 import scenario, seed
    from app.domain.market import timestamp
    import jsonschema
    from app.config import ROOT
    rt=client.app.state.runtime
    case=scenario('F210');engine=seed(rt.store,case)
    engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,baseline=[])
    response=client.get('/api/v1/scenario-diagnostics?date='+case['now'][:10])
    row=response.json()['items'][0]
    assert row['event_types']==['BREAKOUT_UNVERIFIED'] and row['decision']['turnover_burst'] is None
    assert not rt.store.rows('SELECT * FROM episodes')
    contract=client.get('/openapi.json').json()['components']['schemas']
    assert 'primary_scenario' in contract['SpikeCard']['properties']
    assert 'REVERSAL_OBSERVED' in contract['EpisodeEvent']['properties']['event_type']['pattern']
    case=scenario('F202')
    # Independent symbol avoids mixing scenario fixture histories.
    for bar in case['bars']:bar['symbol']='SH.600000'
    engine=seed(rt.store,case)
    engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,baseline=[])
    event=json.loads(rt.store.rows('SELECT payload FROM episode_events')[0][0])
    jsonschema.validate(event,contract['EpisodeEvent'])
    detail=client.get('/api/v1/episodes/'+event['episode_id']).json()
    assert detail['decisions'][0]['details']['rapid_attention']
    assert detail['card']['primary_scenario']=='RAPID_RISE'
