"""Production acceptance; synthetic cases never count as live feed evidence."""
import copy
import importlib.util
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import jsonschema
import pytest

from app.config import PROFILE, ROOT
from app.domain.engine import Engine
from app.domain.market import timestamp
from app.domain.rules import evaluate, first_attention_alert
from app.domain.rules_v100 import evaluate as legacy_evaluate
from app.repo.store import Store, dump
from app.runtime import Runtime
from tests.test_engine import advance, latest

DELTA=ROOT/'spec/upgrades/A_Share_Spike_Radar_V1_0_2_Four_Scenarios_Closure'
CASES=json.loads((DELTA/'fixtures/four_scenario_full_bars.json').read_text())['cases']
module=importlib.util.spec_from_file_location('independent_oracle',DELTA/'reference/scenario_oracle_v102.py')
oracle=importlib.util.module_from_spec(module);module.loader.exec_module(oracle)


def scenario(id):
    case=copy.deepcopy(next(c for c in CASES if c['id'].startswith(id+'_')))
    # Bundle fixtures omit transport fields. Explicit virtual receipts only in tests.
    for bar in case['bars']:
        bar.update(source='SYNTHETIC_V102',received_at=(timestamp(bar['bar_end_at'])+timedelta(seconds=5)).isoformat())
    return case


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_production_matches_independent_oracle(case):
    actual=evaluate(case['bars'],case['prior_same_slot_amounts'],case['now'])
    reference=oracle.evaluate(case['bars'],case['prior_same_slot_amounts'],case['now'])
    # All mathematical and policy fields agree. Production adds localized reasons.
    for key,value in reference.items():
        if key=='risks' and reference['error']=='DIAGNOSTIC_ONLY': continue
        if key=='risks':value=[v.replace('成交历史不足','成交基准积累中') for v in value]
        assert actual[key]==value,(case['id'],key,actual)
    assert first_attention_alert(actual)==oracle.first_attention_alert(reference,episode_is_new=True,already_first_attention=False)


def seed(store,case):
    engine=Engine(store,mode='SIMULATION')
    with store.transaction() as db:
        db.execute('INSERT OR IGNORE INTO watchlist VALUES (?,1,?,?)',(case['bars'][-1]['symbol'],case['now'],case['now']))
    for bar in case['bars'][:-1]: engine.ingest(bar,timestamp(case['now']))
    return engine


@pytest.mark.parametrize('id,alert',[('F202','RAPID_NEW'),('F204','ACCEL_NEW'),('F208','BREAKOUT_NEW'),('F219','HIGH_NEW')])
def test_F219_F221_real_transaction_first_alert_and_restart(store,id,alert):
    case=scenario(id);engine=seed(store,case)
    result=engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,notify=True,baseline=case['prior_same_slot_amounts'])
    assert len(store.rows('SELECT * FROM episodes'))==1
    assert len(store.rows('SELECT * FROM bar_decisions'))==1
    ep=latest(store);card=engine.card(ep)
    jsonschema.validate(card,json.loads((ROOT/'app/contracts/spike_card.v1.0.2.schema.json').read_text()))
    assert store.rows('SELECT kind FROM alert_outbox')[0][0]==alert
    # SQL guard also blocks a competing first kind, even if a future caller errs.
    with store.transaction() as db:
        db.execute('INSERT OR IGNORE INTO alert_outbox VALUES (?,?,?,?)',('competing',ep['episode_id'],'ACCEL_NEW' if alert!='ACCEL_NEW' else 'RAPID_NEW',case['now']))
    assert len(store.rows('SELECT * FROM alert_outbox'))==1
    reopened=Store(store.path)
    try:
        assert Engine(reopened).ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,notify=True)=='DUPLICATE'
        assert len(reopened.rows('SELECT * FROM alert_outbox'))==1
    finally: reopened.close()


@pytest.mark.parametrize('id',['F203','F210','F215','F216','F217'])
def test_no_new_card_or_alert_for_diagnostic_or_veto(store,id):
    case=scenario(id);engine=seed(store,case)
    result=engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,notify=True,baseline=case['prior_same_slot_amounts'])
    assert not store.rows('SELECT * FROM episodes')
    assert not store.rows('SELECT * FROM alert_outbox')
    assert store.rows('SELECT * FROM bar_decisions')
    assert not result['is_attention_eligible']


@pytest.mark.parametrize('triggered',[True,False])
def test_F218_reversal_weakens_original_episode_and_exits_top(store,triggered):
    case=scenario('F202');engine=seed(store,case)
    engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,baseline=[])
    before=latest(store);bar=advance(case['bars'][-1])
    from decimal import Decimal as D
    close=D(case['bars'][-1]['close'])
    bar.update(open=str(close),low=str(close),high=str(close*D('1.04')),close=str(close*(D('1.01') if triggered else 1)))
    result=engine.ingest(bar,timestamp(bar['received_at']),allow_signals=True,notify=True,baseline=['1000000']*5)
    ep=latest(store)
    assert result['triggered']==triggered and ep['episode_id']==before['episode_id']
    assert ep['state']=='WEAKENING' and ep['priority']=='LOW'
    event=json.loads(store.rows('SELECT payload FROM episode_events ORDER BY sequence DESC LIMIT 1')[0][0])
    assert event['event_type']=='REVERSAL_OBSERVED' and event['alert_kind'] is None
    assert len(store.rows('SELECT * FROM alert_outbox'))==1
    rt=Runtime(store);card=engine.card(ep);card['feed_health']='HEALTHY'
    rt.cards=lambda at=None:[card];rt.feed=lambda at=None:{'monitored_count':1,'available_count':1}
    assert rt.radar()['top_cards']==[] and rt.radar()['risk_cards']==[card]


def test_F220_F221_change_scenarios_then_high_upgrade_once(store):
    case=scenario('F208');engine=seed(store,case)
    engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,baseline=case['prior_same_slot_amounts'])
    before=latest(store);bar=case['bars'][-1]
    from decimal import Decimal as D
    for _ in range(4):
        bar=advance(bar,str(D(bar['close'])*D('1.02')))
        engine.ingest(bar,timestamp(bar['received_at']),allow_signals=True,notify=True,baseline=['1000000']*5)
    assert latest(store)['episode_id']==before['episode_id']
    assert [r[0] for r in store.rows('SELECT kind FROM alert_outbox ORDER BY rowid')]==['BREAKOUT_NEW','HIGH_UPGRADE']
    assert 'RAPID_RISE' in latest(store)['matched_scenarios']
    assert any(r[0]=='SCENARIOS_CHANGED' for r in store.rows('SELECT event_type FROM episode_events'))


def test_F228_migrate_preserves_old_event_bytes_and_version(tmp_path,case):
    path=tmp_path/'legacy.sqlite3';db=sqlite3.connect(path)
    db.executescript((ROOT/'app/repo/migrations/001_initial.sql').read_text())
    signal=legacy_evaluate(case['bars'],case['prior_same_slot_amounts'],case['now'])
    ep={'episode_id':'legacy_episode_00000001','symbol':case['bars'][-1]['symbol'],'session_date':case['now'][:10],
        'trigger_bar_start_at':case['bars'][-1]['bar_start_at'],'trigger_close':case['bars'][-1]['close'],
        'state':'ACTIVE','score':signal['score'],'priority':signal['priority'],'signal':signal,'bar':case['bars'][-1],
        'updated_at':case['now'],'data_mode':'LIVE','weak':0,'nontrigger':0}
    old_event=dump({'rule_version':'spike_rules_v1.0.1','score':signal['score'],'original':'immutable'})
    db.execute('INSERT INTO episodes VALUES (?,?,?,?,?)',(ep['episode_id'],ep['symbol'],ep['session_date'],ep['state'],dump(ep)))
    db.execute('INSERT INTO episode_events(event_id,episode_id,event_type,bar_start_at,recorded_at,payload) VALUES (?,?,?,?,?,?)',('old_event_00000001',ep['episode_id'],'CREATED',ep['bar']['bar_start_at'],case['now'],old_event))
    db.execute('INSERT INTO alert_outbox VALUES (?,?,?,?)',('old_alert',ep['episode_id'],'RAPID_NEW',case['now']))
    db.commit();db.close()
    store=Store(path)
    try:
        engine=Engine(store);old=latest(store)
        assert engine.card(old)['rule_version']=='spike_rules_v1.0.1'
        assert store.rows('SELECT payload FROM episode_events')[0][0]==old_event
        assert (tmp_path/'legacy-before-v102.sqlite3').exists()
        with store.transaction() as db:
            db.execute('INSERT INTO watchlist VALUES (?,1,?,?)',(ep['symbol'],case['now'],case['now']))
            db.execute('INSERT INTO alert_outbox VALUES (?,?,?,?)',('new_first',ep['episode_id'],'HIGH_NEW',case['now']))
        assert len(store.rows('SELECT * FROM alert_outbox'))==1
        bar=advance(ep['bar'],'10.50')
        engine.ingest(bar,timestamp(bar['received_at']),allow_signals=True,notify=True)
        closed=latest(store)
        assert closed['state']=='EXPIRED' and closed['score']==signal['score']
        assert engine.card(closed)['rule_version']=='spike_rules_v1.0.1'
        assert store.rows('SELECT payload FROM episode_events ORDER BY sequence LIMIT 1')[0][0]==old_event
        assert json.loads(store.rows('SELECT payload FROM episode_events ORDER BY sequence DESC LIMIT 1')[0][0])['rule_version']=='spike_rules_v1.0.1'
    finally: store.close()


def test_documented_S05_version_conflict():
    from tests.conftest import FIXTURE
    case=next(c for c in FIXTURE['cases'] if c['id'].startswith('S05'))
    old=legacy_evaluate(case['bars'],case['prior_same_slot_amounts'],case['now'])
    new=evaluate(case['bars'],case['prior_same_slot_amounts'],case['now'])
    assert old['priority']=='MEDIUM' and new['priority']=='LOW'
    assert old['score']==new['raw_score'] and new['force_weakening']


def test_profile_is_complete_and_unchanged_from_supplement():
    assert PROFILE==json.loads((DELTA/'contracts/rule_profile.v1.0.2.json').read_text())


@pytest.mark.parametrize('case',__import__('tests.conftest',fromlist=['FIXTURE']).FIXTURE['cases'],ids=lambda c:c['id'])
def test_current_engine_preserves_original_expectations_except_documented_veto(case):
    result=evaluate(case['bars'],case['prior_same_slot_amounts'],case['now'])
    for key,value in case['expected'].items():
        if case['id']=='S05_UPPER_WICK_AND_PULLBACK' and key=='priority':
            assert result[key]=='LOW' and result['force_weakening']
        else:
            assert result[key]==value
