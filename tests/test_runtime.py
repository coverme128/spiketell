import json
import time
from datetime import timedelta

import pytest

from app.domain.market import now
from app.repo.store import dump
from app.runtime import Runtime


def test_partial_health_counts_only_fresh_symbols(store,monkeypatch):
    from datetime import datetime
    from app.domain.market import TZ
    at=datetime(2026,10,9,10,1,10,tzinfo=TZ)
    rt=Runtime(store);rt.started=at;rt.start_mono=time.monotonic()
    ev={'provider':{'name':'akshare','personal_use_confirmed':True,'rights_evidence':'TEST','timestamp_semantics':'end','timestamp_samples':['a','b'],'finalization_verified':True,'capacity_verified':True},'clock':{'source':'TEST','checked_at':at.isoformat(),'offset_seconds':0},'calendar':{'source':'TEST','checked_at':(at-timedelta(hours=1)).isoformat(),'valid_from':'2026-10-01','valid_to':'2026-10-31','trading_dates':['2026-10-09']}}
    monkeypatch.setattr('app.runtime.evidence',lambda:ev)
    meta={'name':'Test','board':'MAIN','risk_status':'NORMAL','metadata_source':'TEST','checked_at':at.isoformat(),'suspended':False,'ordinary_a':True,'limits_verified':True,'list_date':'2000-01-01'}
    with store.transaction() as db:
        for i,symbol in enumerate(['SH.600000','SZ.000001']):
            db.execute('INSERT INTO watchlist VALUES (?,1,?,?)',(symbol,at.isoformat(),at.isoformat()))
            db.execute('INSERT INTO instruments VALUES (?,?)',(symbol,dump(meta)))
            db.execute('INSERT INTO provider_health VALUES (?,?)',(symbol,dump({'bar_end_at':(at-timedelta(seconds=10 if i==0 else 100)).isoformat()})))
    feed=rt.feed(at)
    assert feed['status']=='DEGRADED'
    assert feed['available_count']==1 and feed['monitored_count']==2
    rt.started-=timedelta(seconds=3)
    assert rt.feed(at)['status']=='STOPPED'


def test_adapter_timeout_is_visible(monkeypatch):
    import asyncio
    from app.providers.akshare import AKShareProvider
    async def fail(*args,**kwargs):raise OSError('test')
    monkeypatch.setattr(asyncio,'create_subprocess_exec',fail)
    result=asyncio.run(AKShareProvider('end').fetch_final_bars(['SH.600000'],{}))
    assert result.errors=={'SH.600000':'PROVIDER_INVALID_RESPONSE'}
    assert result.bars==[]
