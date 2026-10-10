"""Replay actual historical prices with an explicitly virtual clock, isolated DB.

This validates data/engine integration, never live latency, timestamp semantics,
source rights or delivery to a real browser. It does not write production data.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime,timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.config import PROFILE
from app.domain.engine import Engine
from app.domain.market import TZ,now,symbol_id,validate_bar
from app.providers.public import Transport,sina_rows,quote
from app.repo.store import Store,dump


async def main(args):
    transport=Transport(3)
    observed=now()
    report={'observed_at':observed.isoformat(),'source_kind':'REAL_HISTORICAL_PRICES',
            'execution_mode':'SIMULATION','clock':'VIRTUAL_BAR_END_PLUS_20_SECONDS',
            'candidate_semantics':args.semantics,'semantics_verified':False,
            'rule_version':PROFILE['rule_version'],'counts':{},'live_qualification':False,
            'explanation':'Historical integration only. Receipt times are replay-clock values; no live notification or performance claim.'}
    with tempfile.TemporaryDirectory(prefix='spiketell-real-replay-') as folder:
        store=Store(Path(folder)/'replay.sqlite3');engine=Engine(store,'SIMULATION')
        for symbol in args.symbols.split(','):
            symbol=symbol_id(symbol)
            raw,info=await asyncio.gather(transport.call('history:'+symbol,sina_rows,symbol),transport.call('quote:'+symbol,quote,symbol))
            with store.transaction() as db:
                db.execute('INSERT INTO watchlist VALUES (?,1,?,?)',(symbol,observed.isoformat(),observed.isoformat()))
                db.execute('INSERT INTO instruments VALUES (?,?)',(symbol,dump({'name':info['f58']})))
            rejected=Counter();results=Counter();days=set()
            for row in sorted(raw,key=lambda r:r['day']):
                label=datetime.fromisoformat(row['day']).replace(tzinfo=TZ)
                start=label-timedelta(minutes=1) if args.semantics=='end' else label
                end=start+timedelta(minutes=1)
                virtual=end+timedelta(seconds=20)
                if end>=observed:continue
                bar={'symbol':symbol,'bar_start_at':start.isoformat(),'bar_end_at':end.isoformat(),
                     'open':str(row['open']),'high':str(row['high']),'low':str(row['low']),'close':str(row['close']),
                     'volume_shares':int(Decimal(str(row['volume']))),'amount_cny':str(row['amount']),
                     'source':'sina/minute','received_at':virtual.isoformat(),'is_final':True,'quality':'VALID'}
                try:validate_bar(bar)
                except ValueError as error:rejected[str(error)]+=1;continue
                engine.close_old_sessions(virtual)
                signal=engine.ingest(bar,virtual,allow_signals=True,notify=False)
                results[signal.get('priority','LOW') if isinstance(signal,dict) and signal.get('triggered') else 'NO_TRIGGER']+=1
                days.add(start.date().isoformat())
            episodes=[json.loads(r[0]) for r in store.rows('SELECT payload FROM episodes WHERE symbol=?',(symbol,))]
            report['counts'][symbol]={'name':info['f58'],'raw_rows':len(raw),'session_dates':sorted(days),
                                      'minute_results':dict(results),'excluded':dict(rejected),'episodes':len(episodes)}
        assert not any(json.loads(r[0])['delivery_mode']=='LIVE' for r in store.rows('SELECT payload FROM episode_events'))
        report['event_count']=len(store.rows('SELECT * FROM episode_events'))
        report['all_delivery_modes']=sorted({json.loads(r[0])['delivery_mode'] for r in store.rows('SELECT payload FROM episode_events')})
        report['database_check']=store.rows('PRAGMA quick_check')[0][0]
        store.close()
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--symbols',default='SH.600000,SZ.000001,SZ.300308,SH.688981')
    parser.add_argument('--semantics',choices=['start','end'],required=True)
    parser.add_argument('--output',default='evidence/real-history-replay.json')
    asyncio.run(main(parser.parse_args()))
