from __future__ import annotations

import re
from datetime import datetime, timedelta, time
from decimal import Decimal
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def now() -> datetime:
    return datetime.now(TZ)


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() != timedelta(hours=8):
        raise ValueError("EXPECTED_SHANGHAI_OFFSET")
    return result


def symbol_id(value: str) -> str:
    value = value.strip().upper()
    if re.fullmatch(r"\d{6}\.(SH|SZ)", value):
        code, exchange = value.split(".")
        value = f"{exchange}.{code}"
    if re.fullmatch(r"\d{6}", value):
        value = ("SH." if value.startswith("6") else "SZ.") + value
    if not re.fullmatch(r"(SH|SZ)\.\d{6}", value):
        raise ValueError("INVALID_SYMBOL")
    exchange, code = value.split(".")
    if not ((exchange == "SH" and code.startswith(("600", "601", "603", "605", "688"))) or
            (exchange == "SZ" and code.startswith(("000", "001", "002", "003", "300", "301")))):
        raise ValueError("NOT_SUPPORTED")
    return value


def session(at: datetime, calendar: dict | None) -> str:
    if not calendar:
        return "UNKNOWN"
    date = at.date().isoformat()
    try:
        if not calendar["source"] or not calendar["valid_from"] <= date <= calendar["valid_to"]:
            return "UNKNOWN"
        checked = timestamp(calendar["checked_at"])
        if checked > at or (at - checked).days > 370:
            return "UNKNOWN"
        if date not in calendar["trading_dates"]:
            return "CLOSED"
    except (KeyError, ValueError, TypeError):
        return "UNKNOWN"
    t = at.time().replace(tzinfo=None)
    if time(9, 30) <= t < time(11, 30) or time(13) <= t < time(14, 57):
        return "CONTINUOUS"
    if time(9, 15) <= t < time(9, 25):
        return "OPEN_AUCTION"
    if time(11, 30) <= t < time(13):
        return "MIDDAY_BREAK"
    if time(14, 57) <= t < time(15):
        return "CLOSE_AUCTION"
    return "CLOSED"


def adjacent(a: str, b: str) -> bool:
    left, right = timestamp(a), timestamp(b)
    return (right - left == timedelta(minutes=1) or
            (left.date() == right.date() and left.time() == time(11, 29) and right.time() == time(13)))


def validate_bar(bar: dict) -> None:
    if symbol_id(bar["symbol"]) != bar["symbol"]:
        raise ValueError("INVALID_SYMBOL")
    start, end = timestamp(bar["bar_start_at"]), timestamp(bar["bar_end_at"])
    received = timestamp(bar["received_at"])
    if start.second or start.microsecond or end - start != timedelta(minutes=1):
        raise ValueError("INVALID_INTERVAL")
    t = start.time()
    if not (time(9, 30) <= t < time(11, 30) or time(13) <= t < time(14, 57)):
        raise ValueError("NON_CONTINUOUS_BAR")
    vals = [Decimal(str(bar[k])) for k in ("open", "high", "low", "close", "amount_cny")]
    if not all(x.is_finite() for x in vals):
        raise ValueError("NON_FINITE_PRICE")
    o, h, l, c, amount = vals
    volume = Decimal(str(bar["volume_shares"]))
    if not volume.is_finite() or volume < 0 or volume != volume.to_integral_value():
        raise ValueError("INVALID_VOLUME")
    if not 0 < l <= min(o, c) <= max(o, c) <= h or amount < 0:
        raise ValueError("INVALID_OHLC")
    if bar["is_final"] is not True or bar["quality"] != "VALID" or not bar["source"]:
        raise ValueError("INVALID_FINAL_QUALITY")
    if end > received:
        raise ValueError("FUTURE_BAR")


def metadata_reason(meta: dict | None, at: datetime) -> str | None:
    if not meta:
        return "METADATA_UNKNOWN"
    try:
        if not meta["metadata_source"] or timestamp(meta["checked_at"]).date() != at.date():
            return "METADATA_STALE"
        if timestamp(meta["checked_at"]) > at:
            return "METADATA_FUTURE"
        if meta["board"] not in ("MAIN", "CHINEXT", "STAR") or meta["risk_status"] != "NORMAL":
            return "INSTRUMENT_RESTRICTED"
        if meta["suspended"] is not False or meta["ordinary_a"] is not True or meta["limits_verified"] is not True:
            return "INSTRUMENT_RESTRICTED"
        if not meta["list_date"] or meta["list_date"] > at.date().isoformat():
            return "LIST_DATE_UNKNOWN"
    except (KeyError, ValueError, TypeError):
        return "METADATA_UNKNOWN"
    return None
