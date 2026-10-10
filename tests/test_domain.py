import copy
import json
from datetime import timedelta
from decimal import Decimal

import pytest
import jsonschema

from app.config import ROOT, qualification_reasons
from app.domain.market import symbol_id, session, timestamp, validate_bar, metadata_reason
from app.domain.rules import evaluate
from app.providers.akshare import normalize
from tests.conftest import FIXTURE


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c:c["id"])
def test_frozen_fixtures(case):
    # Preserve v1.0.0 expectations; v1.0.2 reversal precedence is tested separately.
    from app.domain.rules_v100 import evaluate as legacy_evaluate
    actual = legacy_evaluate(case["bars"], case["prior_same_slot_amounts"], case["now"])
    for key, value in case["expected"].items():
        assert actual[key] == value


@pytest.mark.parametrize("value,expected", [("600000", "SH.600000"), ("000001.SZ", "SZ.000001"), ("sz.300308", "SZ.300308"), ("SH.688001", "SH.688001")])
def test_symbol_conversions(value, expected):
    assert symbol_id(value) == expected


@pytest.mark.parametrize("value", ["SZ.600000", "SH.000001", "abc", "SH.510300", "900001", "430001", "000001;DROP TABLE watchlist"])
def test_symbol_rejections(value):
    with pytest.raises(ValueError): symbol_id(value)


def calendar():
    return {"source": "TEST_FIXTURE", "checked_at": "2026-10-08T08:00:00+08:00", "valid_from": "2026-10-01", "valid_to": "2026-10-31", "trading_dates": ["2026-10-09"]}


@pytest.mark.parametrize("clock,expected", [("09:29", "CLOSED"), ("09:30", "CONTINUOUS"), ("11:29", "CONTINUOUS"), ("11:30", "MIDDAY_BREAK"), ("11:45", "MIDDAY_BREAK"), ("13:00", "CONTINUOUS"), ("14:56", "CONTINUOUS"), ("14:57", "CLOSE_AUCTION"), ("14:59", "CLOSE_AUCTION"), ("15:00", "CLOSED")])
def test_market_sessions(clock, expected):
    assert session(timestamp(f"2026-10-09T{clock}:00+08:00"), calendar()) == expected


def test_calendar_fail_closed_and_holiday():
    assert session(timestamp("2026-10-09T10:00:00+08:00"), None) == "UNKNOWN"
    assert session(timestamp("2026-10-12T10:00:00+08:00"), calendar()) == "CLOSED"
    assert session(timestamp("2026-11-02T10:00:00+08:00"), calendar()) == "UNKNOWN"


@pytest.mark.parametrize("field,value", [("close", "NaN"), ("high", "Infinity"), ("low", "0"), ("amount_cny", "-1"), ("volume_shares", 0.5), ("quality", "PARTIAL"), ("is_final", False), ("symbol", "SH.notreal")])
def test_invalid_bar(case, field, value):
    bar = case["bars"][-1]; bar[field] = value
    with pytest.raises(ValueError): validate_bar(bar)


def test_exact_threshold_without_rounding(case):
    bars = case["bars"][-2:]
    bars[0].update(close="10", high="10")
    bars[1].update(open="10", low="10", high="10.08", close="10.08")
    assert evaluate(bars, [], case["now"])["triggered"]
    bars[1]["close"] = "10.079999999999"
    assert not evaluate(bars, [], case["now"])["triggered"]


def test_adapter_units_and_time():
    row = {"时间": "2026-10-09 10:00:00", "开盘": "10", "收盘": "10.1", "最高": "10.2", "最低": "9.9", "成交量": "123", "成交额": "123000"}
    at = timestamp("2026-10-09T10:00:10+08:00")
    bar = normalize(row, "600000", "end", at)
    assert bar["volume_shares"] == 12300 and bar["amount_cny"] == "123000"
    assert bar["bar_start_at"] == "2026-10-09T09:59:00+08:00"
    with pytest.raises(ValueError, match="UNKNOWN_TIMESTAMP"): normalize(row, "600000", "unknown", at)
    with pytest.raises(ValueError, match="PARTIAL"): normalize(row, "600000", "start", at)


@pytest.mark.parametrize("status", ["ST", "NEW", "DELISTED", "UNKNOWN"])
def test_metadata_restrictions(status):
    at = timestamp("2026-10-09T10:00:00+08:00")
    assert metadata_reason({"metadata_source":"TEST","checked_at":"2026-10-09T09:00:00+08:00","risk_status":status,"board":"MAIN"},at)


def test_clock_and_timestamp_qualification():
    at=timestamp("2026-10-09T10:00:00+08:00")
    assert "CLOCK_UNVERIFIED" in qualification_reasons({},at)
    assert "UNKNOWN_TIMESTAMP_SEMANTICS" in qualification_reasons({},at)
    assert "CLOCK_UNVERIFIED" in qualification_reasons({"clock":{"source":"TEST","checked_at":at.isoformat(),"offset_seconds":2.01}},at)


def test_no_cross_lunch_returns(case):
    bars=case["bars"][-4:]
    for i,b in enumerate(bars):
        start=timestamp("2026-10-09T11:28:00+08:00")+timedelta(minutes=i) if i<2 else timestamp("2026-10-09T13:00:00+08:00")+timedelta(minutes=i-2)
        b.update(bar_start_at=start.isoformat(),bar_end_at=(start+timedelta(minutes=1)).isoformat(),received_at=(start+timedelta(minutes=1,seconds=10)).isoformat())
    result=evaluate(bars,case["prior_same_slot_amounts"],bars[-1]["received_at"])
    assert result["ret3_pct"] is None
    assert result["breakout20"] is False
