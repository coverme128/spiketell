"""Measure a supplied pool. Never equate request timing with visible alert timing."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from datetime import timedelta
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.config import evidence
from app.domain.market import now, session, symbol_id, metadata_reason, timestamp
from app.providers.akshare import AKShareProvider


async def measure(pool, rounds, output):
    config=evidence();provider=config.get('provider',{})
    if not provider.get('personal_use_confirmed') or not provider.get('rights_evidence'):
        raise SystemExit('DATA_PROVIDER_BLOCKED: confirm source rights first')
    if provider.get('timestamp_semantics') not in ('start','end') or not provider.get('finalization_verified'):
        raise SystemExit('DATA_PROVIDER_BLOCKED: timestamp/finalization evidence required')
    symbols=list(dict.fromkeys(symbol_id(s) for s in pool))
    if len(symbols)<50:raise SystemExit('Provide at least 50 real qualified symbols; no synthetic pool is generated')
    provider=AKShareProvider(provider['timestamp_semantics'])
    report={'status':'INSUFFICIENT_EVIDENCE','started_at':now().isoformat(),'samples':[],'visible_alert_latency':'NOT_MEASURED_BY_THIS_COMMAND'}
    for size in (10,30,50):
        cursors={}
        for number in range(rounds):
            at=now()
            if session(at,config.get('calendar'))!='CONTINUOUS':raise SystemExit('NO_SESSION: run during a verified continuous auction session')
            if any(metadata_reason(config.get('instruments',{}).get(s),at) for s in symbols[:size]):raise SystemExit('METADATA_UNVERIFIED')
            started=time.monotonic();result=await provider.fetch_final_bars(symbols[:size],cursors)
            sample={'pool_size':size,'round':number+1,'observed_at':now().isoformat(),'elapsed_seconds':time.monotonic()-started,'valid_latest_symbols':sum(0<=lag<=90 and symbol not in result.errors for symbol,lag in result.lag.items()),'errors':result.errors,'lag_seconds':result.lag}
            for b in result.bars:cursors[b['symbol']]=max(cursors.get(b['symbol'],''),b['bar_start_at'])
            report['samples'].append(sample)
            Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(sample,ensure_ascii=False),flush=True)
            if number+1<rounds:await asyncio.sleep(max(1,60-(time.monotonic()-started)))
        if size!=50:await asyncio.sleep(60)
    print('Load observations saved. Two complete sessions and browser-visible latency still require separate evidence.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--symbols-file',required=True);p.add_argument('--rounds',type=int,default=3);p.add_argument('--output',default='evidence/load-measurements.json');a=p.parse_args()
    if a.rounds<1:raise SystemExit('rounds must be positive')
    pool=Path(a.symbols_file).read_text().replace(',',' ').split()
    asyncio.run(measure(pool,a.rounds,a.output))
