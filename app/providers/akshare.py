"""AKShare boundary: explicit timestamp qualification, bounded subprocess requests."""
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.domain.market import TZ, now, symbol_id, validate_bar
from app.providers.errors import read_worker_error


@dataclass
class FetchResult:
    bars: list[dict] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    coverage: dict[str, int] = field(default_factory=dict)
    lag: dict[str, float] = field(default_factory=dict)
    provider_clock: str | None = None
    excluded_rows: dict[str, dict[str, int]] = field(default_factory=dict)


class Provider(Protocol):
    async def fetch_final_bars(self, symbols: list[str], from_cursor: dict[str, str]) -> FetchResult: ...


def normalize(row, symbol, semantics, received):
    if semantics not in ("start", "end"):
        raise ValueError("UNKNOWN_TIMESTAMP_SEMANTICS")
    label = datetime.fromisoformat(str(row["时间"]))
    label = label.replace(tzinfo=TZ) if label.tzinfo is None else label.astimezone(TZ)
    start = label if semantics == "start" else label - timedelta(minutes=1)
    end = start + timedelta(minutes=1)
    if end > received:
        raise ValueError("PARTIAL")
    volume = Decimal(str(row["成交量"])) * 100
    if not volume.is_finite() or volume != volume.to_integral_value():
        raise ValueError("INVALID_VOLUME")
    bar = {"symbol": symbol_id(symbol), "bar_start_at": start.isoformat(), "bar_end_at": end.isoformat(),
           "open": str(row["开盘"]), "high": str(row["最高"]), "low": str(row["最低"]), "close": str(row["收盘"]),
           "volume_shares": int(volume), "amount_cny": str(row["成交额"]), "source": "akshare/eastmoney",
           "received_at": received.isoformat(), "is_final": True, "quality": "VALID"}
    validate_bar(bar)
    return bar


class AKShareProvider:
    def __init__(self, semantics):
        self.semantics = semantics
        self.concurrency = max(1, min(5, int(os.getenv("RADAR_CONCURRENCY", "3"))))
        self.timeout = float(os.getenv("RADAR_REQUEST_TIMEOUT", "20"))

    async def fetch_final_bars(self, symbols, from_cursor):
        result = FetchResult()
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch(symbol):
            async with semaphore:
                proc = None
                try:
                    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.providers.worker", symbol,
                        from_cursor.get(symbol, ""), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    raw, stderr = await asyncio.wait_for(proc.communicate(), self.timeout)
                    if proc.returncode:
                        result.errors[symbol] = read_worker_error(stderr)
                        return
                    rows = json.loads(raw)
                    if not isinstance(rows, list) or len(rows) > 2000:
                        raise ValueError("PROVIDER_ROW_LIMIT")
                    received = now()
                    accepted, excluded, invalid = normalize_rows(rows, symbol, self.semantics, received)
                    result.excluded_rows[symbol] = excluded
                    if invalid:
                        result.errors[symbol] = "PROVIDER_INVALID_RESPONSE"
                    result.bars.extend(accepted)
                    result.coverage[symbol] = len(accepted)
                    if accepted:
                        result.lag[symbol] = (received - datetime.fromisoformat(accepted[-1]["bar_end_at"])).total_seconds()
                    else:
                        result.errors[symbol] = "NO_FINAL_BARS"
                except asyncio.TimeoutError:
                    result.errors[symbol] = "PROVIDER_TIMEOUT"
                except (ValueError, KeyError, OSError):
                    result.errors[symbol] = "PROVIDER_INVALID_RESPONSE"
                finally:
                    if proc and proc.returncode is None:
                        proc.kill()
                        await proc.wait()

        await asyncio.gather(*(fetch(s) for s in symbols))
        return result


def normalize_rows(rows, symbol, semantics, received):
    accepted, excluded, invalid = [], {}, False
    for row in rows:
        try:
            # AKShare documents open=0 on earlier dates. Do not invent OHLC or
            # let that historical limitation discard valid current-day bars.
            label = datetime.fromisoformat(str(row["时间"]))
            if label.date() < received.date() and Decimal(str(row["开盘"])) == 0:
                reason = "HISTORICAL_OPEN_UNAVAILABLE"
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            accepted.append(normalize(row, symbol, semantics, received))
        except (ValueError, KeyError, TypeError, ArithmeticError) as error:
            reason = str(error) if str(error) in ("PARTIAL", "NON_CONTINUOUS_BAR") else "INVALID_ROW"
            excluded[reason] = excluded.get(reason, 0) + 1
            if reason == "INVALID_ROW":
                invalid = True
    return sorted(accepted, key=lambda b: b["bar_start_at"]), excluded, invalid
