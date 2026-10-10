"""Completed bars require two identical post-close observations, never a timer alone."""
import asyncio
from collections import Counter
from datetime import timedelta

from app.domain.market import now, timestamp
from app.providers.akshare import FetchResult, normalize_rows
from app.providers.public import SourceError, Transport, eastmoney_rows


class Finalizer:
    def __init__(self, minimum_observation_seconds=5, minimum_close_age_seconds=8):
        self.seen = {}
        self.observation_gap = minimum_observation_seconds
        self.close_age = minimum_close_age_seconds

    def accept(self, bars, observed):
        accepted = []
        for bar in bars:
            key = (bar['symbol'],bar['bar_start_at'])
            value = tuple(bar[k] for k in ('open','high','low','close','volume_shares','amount_cny'))
            end = timestamp(bar['bar_end_at'])
            previous = self.seen.get(key)
            # Historical completed sessions cannot become live signals; the
            # engine's freshness guard still applies independently.
            if end.date()<observed.date():
                accepted.append(bar)
                continue
            if (observed-end).total_seconds()<self.close_age:
                continue
            if previous and previous[0]==value and (observed-previous[1]).total_seconds()>=self.observation_gap:
                accepted.append(bar)
            else:
                if not previous or previous[0]!=value:
                    self.seen[key] = (value,observed)
        cutoff = (observed-timedelta(days=1)).isoformat()
        self.seen = {key:value for key,value in self.seen.items() if key[1]>=cutoff}
        return accepted


class LiveProvider:
    def __init__(self, semantics, transport=None, finalizer=None):
        self.semantics = semantics
        self.transport = transport or Transport()
        self.finalizer = finalizer or Finalizer()

    async def fetch_final_bars(self, symbols, from_cursor, confirm=True):
        result = FetchResult()

        async def collect(symbol):
            try:
                rows = await self.transport.call('minute:'+symbol,eastmoney_rows,symbol)
                at = now()
                bars,excluded,invalid = normalize_rows(rows,symbol,self.semantics,at)
                if from_cursor.get(symbol):
                    cutoff = timestamp(from_cursor[symbol])-timedelta(minutes=25)
                    bars = [b for b in bars if timestamp(b['bar_start_at'])>=cutoff]
                final = self.finalizer.accept(bars,at)
                excluded['AWAITING_FINAL_CONFIRMATION'] = len(bars)-len(final)
                result.bars.extend(final)
                result.coverage[symbol] = len(final)
                result.excluded_rows[symbol] = dict(Counter(excluded))
                if invalid:
                    result.errors[symbol] = 'PROVIDER_INVALID_RESPONSE'
                elif not final:
                    result.errors[symbol] = 'AWAITING_FINAL_CONFIRMATION'
                if final:
                    result.lag[symbol] = (at-timestamp(final[-1]['bar_end_at'])).total_seconds()
            except SourceError as error:
                result.errors[symbol] = error.code

        await asyncio.gather(*(collect(s) for s in symbols))
        if confirm and symbols:
            # A second bounded round verifies stability after the close. No
            # partial first observation is stored as a final minute in the DB.
            await asyncio.sleep(self.finalizer.observation_gap)
            result = FetchResult()
            await asyncio.gather(*(collect(s) for s in symbols))
        return result
