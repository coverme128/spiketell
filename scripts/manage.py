"""Operational CLI: bounded provider probes, replay, backup, NTP and calendars."""
import argparse
import asyncio
import json
import os
import socket
import sqlite3
import struct
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.config import evidence
from app.domain.market import now, symbol_id, timestamp
from app.repo.store import Store, dump
from app.providers.errors import read_worker_error


def replay(path):
    from app.domain.engine import Engine
    store=Store(path)
    with store.transaction() as db:
        mode=db.execute("SELECT value FROM settings WHERE key='data_mode'").fetchone()
        if mode and json.loads(mode[0])!='SIMULATION':
            raise SystemExit('Refusing to write fixtures into a LIVE database')
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('data_mode','\"SIMULATION\"')")
    fixture=json.loads((ROOT/'spec/fixtures/rule_scenarios.json').read_text())
    case=fixture['cases'][0]
    symbol=case['bars'][-1]['symbol']
    with store.transaction() as db:
        db.execute('INSERT OR IGNORE INTO watchlist VALUES (?,1,?,?)',(symbol,case['now'],case['now']))
        db.execute('INSERT OR REPLACE INTO instruments VALUES (?,?)',(symbol,dump({'name':'合成测试股票 · 非实盘'})))
    engine=Engine(store,'SIMULATION')
    for bar in case['bars'][:-1]:engine.ingest(bar,timestamp(case['now']))
    result=engine.ingest(case['bars'][-1],timestamp(case['now']),allow_signals=True,baseline=case['prior_same_slot_amounts'])
    print(dump({'data_mode':'SIMULATION','result':result,'episodes':len(store.rows('SELECT * FROM episodes')),'database':str(path)}))
    store.close()


async def probe(symbols,output):
    # Raw reachability only. No assumed start/end label and no "final" claim.
    observations=[]
    for symbol in symbols:
        started=time.monotonic()
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','app.providers.worker',symbol,'',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            raw,stderr=await asyncio.wait_for(process.communicate(),25)
            rows=json.loads(raw) if process.returncode==0 else []
            observations.append({'symbol':symbol,'status':'RAW_RESPONSE_ONLY' if rows else 'REQUEST_FAILED','error':read_worker_error(stderr) if process.returncode else None,'rows':len(rows),'zero_open_rows':sum(str(r.get('开盘')) in ('0','0.0') for r in rows),'elapsed_seconds':round(time.monotonic()-started,3),'ingest_time':now().isoformat(),'raw_latest_labels':[r.get('时间') for r in rows[-2:]],'samples':rows[-2:]})
        except asyncio.TimeoutError:
            process.kill();await process.wait()
            observations.append({'symbol':symbol,'status':'TIMEOUT','elapsed_seconds':round(time.monotonic()-started,3),'ingest_time':now().isoformat()})
    report={'observed_at':now().isoformat(),'status':'RAW_FEED_REACHABLE' if all(o['status']=='RAW_RESPONSE_ONLY' for o in observations) else 'DATA_PROVIDER_BLOCKED','release_status':'DATA_PROVIDER_BLOCKED','transport':os.getenv('RADAR_HTTP_TRANSPORT','curl'),'purpose':'Raw reachability; not live qualification','observations':observations,'timestamp_semantics':'UNVERIFIED','load_10_30_50':'PENDING_QUALIFIED_SYMBOL_POOL_AND_TRADING_SESSION','rights':'UNVERIFIED'}
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(dump(report))


def update_config(key,value):
    path=Path(os.getenv('RADAR_EVIDENCE','config/runtime.json'))
    data=evidence();data[key]=value
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(path)


def clock_check(host):
    from app.timecheck import measure_clock
    result=measure_clock(host)
    update_config('clock',result);print(dump(result))


def calendar_refresh(valid_from,valid_to):
    import akshare as ak
    frame=ak.tool_trade_date_hist_sina()
    dates=[str(v)[:10] for v in frame['trade_date']]
    if not dates or valid_from<min(dates) or valid_to>max(dates):
        raise SystemExit('Provider calendar does not cover requested range; no config written')
    value={'source':'akshare/tool_trade_date_hist_sina','checked_at':now().isoformat(),'valid_from':valid_from,'valid_to':valid_to,'trading_dates':[d for d in dates if valid_from<=d<=valid_to]}
    update_config('calendar',value);print(dump(value))


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('replay');p.add_argument('--db',default='data/simulation.sqlite3')
    p=sub.add_parser('probe');p.add_argument('--symbols',default='SH.600000,SZ.000001');p.add_argument('--output',default='evidence/provider-probe.json')
    p=sub.add_parser('backup');p.add_argument('destination');p.add_argument('--db',default='data/radar.sqlite3')
    p=sub.add_parser('restore');p.add_argument('source');p.add_argument('--db',required=True)
    p=sub.add_parser('clock');p.add_argument('--host',default='time.cloudflare.com')
    p=sub.add_parser('calendar');p.add_argument('--valid-from',required=True);p.add_argument('--valid-to',required=True)
    args=parser.parse_args()
    if args.command=='replay':replay(args.db)
    elif args.command=='probe':asyncio.run(probe([symbol_id(s) for s in args.symbols.split(',')],args.output))
    elif args.command=='backup':
        store=Store(args.db);store.backup(args.destination);store.close();print('Backup complete')
    elif args.command=='restore':
        if Path(args.db).exists():raise SystemExit('Restore target must not exist; stop server and choose a new path')
        with sqlite3.connect(f'file:{Path(args.source).resolve()}?mode=ro',uri=True) as source:
            if source.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Backup integrity check failed')
            with sqlite3.connect(args.db) as target:source.backup(target)
        print('Restore complete')
    elif args.command=='clock':clock_check(args.host)
    elif args.command=='calendar':calendar_refresh(args.valid_from,args.valid_to)


if __name__=='__main__':main()
