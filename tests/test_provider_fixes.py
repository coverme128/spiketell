import asyncio
from datetime import timedelta
from http.client import RemoteDisconnected
from types import SimpleNamespace

import pytest

from app.domain.market import timestamp
from app.providers.akshare import AKShareProvider, normalize_rows
from app.providers.errors import classify_error, read_worker_error
from app.providers.worker import fetch_frame


def row(at="2026-10-09 10:00:00", open_price="10"):
    return {"时间":at,"开盘":open_price,"收盘":"10.1","最高":"10.2","最低":"9.9","成交量":"100","成交额":"101000"}


def test_zero_open_history_does_not_discard_current_bars():
    bars, excluded, invalid = normalize_rows([row("2026-10-08 10:00:00", "0"), row()], "SH.600000", "end", timestamp("2026-10-09T10:00:10+08:00"))
    assert len(bars) == 1 and not invalid
    assert excluded == {"HISTORICAL_OPEN_UNAVAILABLE":1}
    assert bars[0]["open"] == "10"  # No invented historical open or baseline.


def test_current_zero_open_is_still_invalid():
    bars, excluded, invalid = normalize_rows([row(open_price="0")], "SH.600000", "end", timestamp("2026-10-09T10:00:10+08:00"))
    assert bars == [] and invalid and excluded == {"INVALID_ROW":1}


def test_partial_and_auction_rows_do_not_invalidate_complete_data():
    bars, excluded, invalid = normalize_rows([row("2026-10-09 09:30:00"), row(), row("2026-10-09 10:01:00")], "SH.600000", "end", timestamp("2026-10-09T10:00:10+08:00"))
    assert len(bars) == 1 and not invalid
    assert excluded == {"NON_CONTINUOUS_BAR":1,"PARTIAL":1}


def test_error_chain_preserved_without_secret_text():
    error = ConnectionError("https://user:secret@example.invalid/?token=PRIVATE", RemoteDisconnected("closed"))
    detail = classify_error(error)
    assert detail["error"] == "PROVIDER_REMOTE_DISCONNECTED"
    assert "secret" not in str(detail) and "PRIVATE" not in str(detail)
    assert read_worker_error(b'log line\n{"error":"PROVIDER_REMOTE_DISCONNECTED"}\n') == detail["error"]


@pytest.mark.parametrize("fail", [False, True])
def test_transport_replacement_is_local_and_restored(fail):
    original = object()
    namespace = {"requests":original, "fail":fail}
    exec("def call(**kwargs):\n    assert callable(requests.get)\n    if fail: raise ValueError('test')\n    return kwargs\n", namespace)
    ak = SimpleNamespace(stock_zh_a_hist_min_em=namespace["call"])
    if fail:
        with pytest.raises(ValueError):fetch_frame(ak,"600000","2026-10-09 09:30:00","curl")
    else:
        assert fetch_frame(ak,"600000","2026-10-09 09:30:00","curl")["adjust"] == ""
    assert namespace["requests"] is original


def test_worker_error_reaches_provider_diagnostics(monkeypatch):
    class Process:
        returncode = 1
        async def communicate(self):
            return b"", b'{"error":"PROVIDER_REMOTE_DISCONNECTED"}'
    async def create(*args, **kwargs):return Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    result = asyncio.run(AKShareProvider("end").fetch_final_bars(["SH.600000"], {}))
    assert result.errors == {"SH.600000":"PROVIDER_REMOTE_DISCONNECTED"}


def test_mixed_invalid_symbol_cannot_signal_or_count_as_valid(store, case, monkeypatch):
    import json
    import time
    from app.providers.akshare import FetchResult
    from app.repo.store import dump
    from app.runtime import Runtime

    bar = case['bars'][-1]
    at = timestamp(case['now'])
    symbol = bar['symbol']
    metadata = {'name':'Test','board':'MAIN','risk_status':'NORMAL','metadata_source':'TEST',
                'checked_at':at.isoformat(),'suspended':False,'ordinary_a':True,
                'limits_verified':True,'list_date':'2000-01-01'}
    evidence = {'provider':{'name':'akshare','personal_use_confirmed':True,'rights_evidence':'TEST',
                           'timestamp_semantics':'end','timestamp_samples':['a','b'],
                           'finalization_verified':True,'capacity_verified':True},
                'clock':{'source':'TEST','checked_at':at.isoformat(),'offset_seconds':0},
                'calendar':{'source':'TEST','checked_at':at.isoformat(),
                            'valid_from':at.date().isoformat(),'valid_to':at.date().isoformat(),
                            'trading_dates':[at.date().isoformat()]},
                'instruments':{symbol:metadata}}
    monkeypatch.setattr('app.runtime.now', lambda:at)
    monkeypatch.setattr('app.runtime.evidence', lambda:evidence)
    rt = Runtime(store)
    rt.start_mono = time.monotonic()
    rt.last_poll = at - timedelta(minutes=1)
    with store.transaction() as db:
        db.execute('INSERT INTO watchlist VALUES (?,1,?,?)', (symbol,at.isoformat(),at.isoformat()))
        db.execute('INSERT INTO provider_health VALUES (?,?)',
                   (symbol,dump({'bar_end_at':(at-timedelta(seconds=60)).isoformat()})))
    async def fetch(*args):
        return FetchResult(bars=[bar],errors={symbol:'PROVIDER_INVALID_RESPONSE'},lag={symbol:10})
    monkeypatch.setattr('app.providers.live.LiveProvider.fetch_final_bars', fetch)
    decisions = []
    monkeypatch.setattr(rt.engine, 'ingest', lambda *args, **kwargs:decisions.append(kwargs))
    asyncio.run(rt.poll())
    assert len(decisions) == 1 and decisions[0]['allow_signals'] is False
    sample = json.loads(store.rows('SELECT payload FROM poll_samples')[0][0])
    assert sample['valid_symbols'] == 0
    assert rt.watchlist(at)[0]['source_state'] == 'PROVIDER_INVALID_RESPONSE'
