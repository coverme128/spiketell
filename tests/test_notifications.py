import copy
import json
from datetime import timedelta
from decimal import Decimal

from app.domain.market import timestamp
from tests.test_engine import advance, latest


def test_medium_to_high_one_upgrade(engine,store,case):
    bar=case['bars'][-1]
    signal=engine.ingest(bar,timestamp(case['now']),allow_signals=True,notify=True,baseline=[])
    assert signal['priority']=='MEDIUM'
    for _ in range(5):
        close=str(Decimal(bar['close'])*Decimal('1.02'))
        bar=advance(bar,close)
        engine.ingest(bar,timestamp(bar['received_at']),allow_signals=True,notify=True,baseline=['1000000']*5)
    assert len(store.rows('SELECT * FROM episodes'))==1
    kinds=[r['kind'] for r in store.rows('SELECT * FROM alert_outbox')]
    assert kinds.count('HIGH_UPGRADE')==1 and 'HIGH_NEW' not in kinds
    assert latest(store)['state'] in ('ACTIVE','STRENGTHENING')


def test_simulated_events_never_live(engine,store,case):
    engine.mode='SIMULATION'
    engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,notify=True,baseline=case['prior_same_slot_amounts'])
    event=json.loads(store.rows('SELECT payload FROM episode_events')[0][0])
    assert event['delivery_mode']=='SIMULATION'
    assert event['card']['data_mode']=='SIMULATION'


def test_source_revision_of_history_invalidates(engine,store,case):
    engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,notify=True,baseline=case['prior_same_slot_amounts'])
    bar=copy.deepcopy(case['bars'][0]);bar['high']='20'
    engine.ingest(bar,timestamp(case['now']))
    assert latest(store)['state']=='INVALIDATED'
    assert store.sequence()==2
