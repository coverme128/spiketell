"""Actual-network input/preparation check in an isolated DB; never certifies intraday gates."""
import json,os,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from app.main import create_app
from app.domain.market import now

result={'checked_at':now().isoformat(),'evidence_kind':'ACTUAL_NETWORK_ISOLATED_USER_INPUT','injected_market_data':False,'production_watchlist_modified':False,'intraday_verified':False,'stocks':[]}
with tempfile.TemporaryDirectory(prefix='spiketell-personal-input-') as tmp:
    os.environ['RADAR_EVIDENCE']=str(Path(tmp)/'empty.json')
    os.environ['RADAR_MODE']='LIVE'
    with TestClient(create_app(Path(tmp)/'radar.sqlite3',scheduler=True)) as client:
        # Wait for actual automatic bootstrap, with a bounded deadline.
        for _ in range(45):
            setup=client.get('/api/v1/setup').json()
            if setup['calendar_ready'] and setup['clock_ready']:break
            time.sleep(1)
        result['setup_before_input']=setup
        for symbol in ('600000','000001'):
            start=time.monotonic()
            response=client.post('/api/v1/watchlist',json={'symbols':[symbol]}).json()
            item={'input':symbol,'add_response':response,'add_seconds':round(time.monotonic()-start,3)}
            added=response['items'][0]
            if added['status']=='ADDED':
                canonical=added['symbol']
                item['preparation']=client.post('/api/v1/watchlist/'+canonical+'/prepare').json()
                item['verification']=client.get('/api/v1/watchlist/'+canonical+'/verification').json()
            result['stocks'].append(item)
        result['setup_after_input']=client.get('/api/v1/setup').json()
        result['feed']=client.get('/api/v1/radar').json()['feed']
        result['database_integrity']=client.app.state.runtime.store.rows('PRAGMA integrity_check')[0][0]
        result['episodes']=client.app.state.runtime.store.rows('SELECT COUNT(*) FROM episodes')[0][0]
result['input_and_history_check_passed']=all(s.get('verification',{}).get('baseline',{}).get('historical_days',0)>0 and s.get('verification',{}).get('name') for s in result['stocks']) and result['database_integrity']=='ok'
path=ROOT/'evidence/minute-only/real-user-input.json';path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'input_and_history_check_passed':bool(result['input_and_history_check_passed']),'intraday_verified':False,'stocks':[{'input':s['input'],'result':s['add_response'],'state':s.get('verification',{}).get('state'),'name':s.get('verification',{}).get('name'),'baseline':s.get('verification',{}).get('baseline')} for s in result['stocks']]},ensure_ascii=False,indent=2))
