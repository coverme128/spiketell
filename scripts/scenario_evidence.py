"""Create clearly labeled SIMULATION UI snapshots from the production engine."""
import json
from pathlib import Path
import sys
import tempfile
from decimal import Decimal

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.repo.store import Store
from app.domain.engine import Engine
from app.domain.market import timestamp
from tests.test_scenarios_v102 import scenario, seed
from tests.test_engine import latest, advance

cards=[];events=[];facts={}
with tempfile.TemporaryDirectory() as tmp:
    for id in ('F202','F204','F208','F219'):
        with_store=Store(Path(tmp)/(id+'.sqlite3'))
        try:
            case=scenario(id);engine=seed(with_store,case)
            engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,baseline=case['prior_same_slot_amounts'])
            if id=='F219':
                b=advance(case['bars'][-1]);p=Decimal(b['close']);b.update(open=str(p),low=str(p),close=str(p),high=str(p*Decimal('1.04')))
                engine.ingest(b,timestamp(b['received_at']),allow_signals=True)
            ep=latest(with_store);card=engine.card(ep);card['name']='模拟样本 '+id
            cards.append(card);facts[card['episode_id']]={'amount_cny':ep['bar']['amount_cny'],'source':ep['bar']['source']}
            events.extend(json.loads(r[0]) for r in with_store.rows('SELECT payload FROM episode_events'))
        finally: with_store.close()
feed={'status':'STOPPED','session':'CLOSED','updated_at':cards[-1]['updated_at'],'available_count':0,'monitored_count':0,'last_bar_end_at':None,'reasons':['SIMULATION_ONLY'],'data_mode':'SIMULATION','release_status':'IMPLEMENTED_PENDING_RUNTIME'}
output=ROOT/'evidence/v1.0.2';output.mkdir(exist_ok=True)
(output/'ui-simulation.json').write_text(json.dumps({'feed':feed,'monitored_count':0,'available_count':0,'today_episode_count':4,'high_count':0,'top_cards':cards[:3],'all_cards':cards[:3],'risk_cards':cards[3:],'historical_cards':[],'cursor':0,'card_evidence':facts},ensure_ascii=False,indent=2)+'\n')
(output/'scenario-events-simulation.json').write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n')
print('SIMULATION only: production engine snapshots for four scenarios; no live readiness evidence.')
