import copy
import json
from datetime import timedelta

import jsonschema
import pytest

from app.config import ROOT
from app.domain.engine import Engine
from app.domain.market import timestamp
from app.repo.store import Store


def trigger(engine,case):
    return engine.ingest(case["bars"][-1],timestamp(case["now"]),allow_signals=True,notify=True,baseline=case["prior_same_slot_amounts"])


def latest(store):
    return json.loads(store.rows("SELECT payload FROM episodes ORDER BY rowid DESC LIMIT 1")[0][0])


def advance(bar,close=None):
    b=copy.deepcopy(bar)
    for key in ("bar_start_at","bar_end_at","received_at"):
        b[key]=(timestamp(b[key])+timedelta(minutes=1)).isoformat()
    if close:
        b.update(open=close,close=close,high=close,low=close)
    return b


def test_atomic_creation_and_restart_dedup(engine,store,case):
    result=trigger(engine,case)
    assert result["priority"]=="HIGH"
    assert latest(store)["state"]=="NEW"
    assert len(store.rows("SELECT * FROM alert_outbox"))==1
    sequence=store.sequence()
    reopened=Store(store.path)
    try:
        assert trigger(Engine(reopened),case)=="DUPLICATE"
        assert reopened.sequence()==sequence
        assert len(reopened.rows("SELECT * FROM episodes"))==1
    finally: reopened.close()


def test_expiry_and_immutable_history(engine,store,case):
    trigger(engine,case); bar=case["bars"][-1]
    for state in ("WEAKENING","WEAKENING","EXPIRED"):
        bar=advance(bar,"10.04")
        engine.ingest(bar,timestamp(bar["received_at"]),allow_signals=True)
        assert latest(store)["state"]==state
    assert len(store.rows("SELECT * FROM episode_events"))==4
    assert json.loads(store.rows("SELECT payload FROM episode_events ORDER BY sequence LIMIT 1")[0][0])["next_state"]=="NEW"


def test_revision_is_append_only_and_invalidates(engine,store,case):
    trigger(engine,case);bar=copy.deepcopy(case["bars"][-1]);bar["close"]=bar["open"]
    assert engine.ingest(bar,timestamp(case["now"]),allow_signals=True)=="CORRECTION"
    assert latest(store)["state"]=="INVALIDATED"
    assert len(store.rows("SELECT * FROM minute_bars WHERE bar_start_at=?",(bar["bar_start_at"],)))==2
    assert len(store.rows("SELECT * FROM alert_outbox"))==1
    assert len(store.rows("SELECT * FROM bar_decisions"))==1


def test_delayed_recovery_never_notifies(engine,store,case):
    at=timestamp(case["now"])+timedelta(minutes=10)
    assert engine.ingest(case["bars"][-1],at,allow_signals=True,notify=True)=="EVIDENCE_ONLY"
    assert not store.rows("SELECT * FROM alert_outbox")


def test_disabled_watch_has_no_signal(engine,store,case):
    with store.transaction() as db: db.execute("UPDATE watchlist SET enabled=0")
    assert trigger(engine,case)=="DISABLED"
    assert not store.rows("SELECT * FROM episodes")


def test_day_switch_closes_episode(engine,store,case):
    trigger(engine,case)
    engine.close_old_sessions(timestamp(case["now"])+timedelta(days=1))
    assert latest(store)["state"]=="EXPIRED"
    assert store.sequence()==2


def test_cross_provider_dedup(engine,store,case):
    trigger(engine,case);bar=copy.deepcopy(case["bars"][-1]);bar["source"]="other"
    assert engine.ingest(bar,timestamp(case["now"]),allow_signals=True)=="DUPLICATE"


def test_card_matches_frozen_schema(engine,store,case):
    trigger(engine,case)
    schema=json.loads((ROOT/"app/contracts/spike_card.v1.0.2.schema.json").read_text())
    jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker()).validate(engine.card(latest(store)))


def test_cooldown_and_quiet_window(engine,store,case):
    trigger(engine,case);bar=case["bars"][-1]
    for _ in range(3):
        bar=advance(bar,"10.04");engine.ingest(bar,timestamp(bar["received_at"]),allow_signals=True)
    assert latest(store)["state"]=="EXPIRED"
    bar=advance(bar,"10.30");engine.ingest(bar,timestamp(bar["received_at"]),allow_signals=True,baseline=["1000000"]*5)
    assert len(store.rows("SELECT * FROM episodes"))==1
    for _ in range(15):
        bar=advance(bar,"10.30");engine.ingest(bar,timestamp(bar["received_at"]),allow_signals=True)
    bar=advance(bar,"10.60");engine.ingest(bar,timestamp(bar["received_at"]),allow_signals=True,baseline=["1000000"]*5)
    assert len(store.rows("SELECT * FROM episodes"))==2


def test_gap_invalidates_and_cannot_reopen(engine,store,case):
    trigger(engine,case)
    bar=advance(advance(case["bars"][-1]),"10.60")
    engine.ingest(bar,timestamp(bar["received_at"]),allow_signals=True)
    assert latest(store)["state"]=="INVALIDATED"
    assert len(store.rows("SELECT * FROM episodes"))==1


def test_baseline_uses_distinct_prior_dates(engine,store,case):
    bar=copy.deepcopy(case["bars"][-1])
    for days in range(1,6):
        past=copy.deepcopy(bar)
        for key in ("bar_start_at","bar_end_at","received_at"):
            past[key]=(timestamp(past[key])-timedelta(days=days)).isoformat()
        past["amount_cny"]="1000000"
        engine.ingest(past,timestamp(case["now"]))
    result=engine.ingest(bar,timestamp(case["now"]),allow_signals=True)
    assert result["turnover_burst"]=="4"


def test_future_bar_rejected(engine,case):
    with pytest.raises(ValueError,match="FUTURE_BAR"):
        engine.ingest(case["bars"][-1],timestamp(case["now"])-timedelta(minutes=1),allow_signals=True)


def test_backup_restore(engine,store,case,tmp_path):
    trigger(engine,case);path=tmp_path/'backup.sqlite3';store.backup(path)
    backup=Store(path)
    try:
        assert backup.sequence()==store.sequence()
        assert backup.rows("PRAGMA integrity_check")[0][0]=="ok"
    finally: backup.close()
