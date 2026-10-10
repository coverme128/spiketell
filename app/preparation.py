"""Prepare real instruments and historical evidence without emitting alerts."""
import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal

from app.domain.market import now, timestamp, metadata_reason, session
from app.providers.public import Transport, SourceError, quote, instrument, sina_rows
from app.repo.store import dump


class Preparation:
    def __init__(self, store, evidence):
        self.store, self.evidence = store, evidence
        self.transport = Transport()
        self.pending = set()
        self.lock = asyncio.Lock()

    def status(self, symbol):
        rows = self.store.rows('SELECT payload FROM preparation WHERE symbol=?',(symbol,))
        return json.loads(rows[0][0]) if rows else {'state':'QUEUED','message':'等待获取证券资料和历史基准'}

    def save(self, symbol, **fields):
        status = {**self.status(symbol),**fields,'updated_at':now().isoformat()}
        with self.store.transaction() as db:
            db.execute('INSERT INTO preparation VALUES (?,?) ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload',(symbol,dump(status)))

    def baseline_status(self, symbol, at=None):
        at = at or now()
        args=(symbol,at.date().isoformat())
        totals=self.store.rows("SELECT COUNT(DISTINCT session_date) AS days,COUNT(*) AS n,SUM(semantics NOT IN ('start','end')) AS unqualified FROM baseline_amounts WHERE symbol=? AND session_date<?",args)[0]
        ready=self.store.rows("SELECT COUNT(*) FROM (SELECT slot FROM baseline_amounts WHERE symbol=? AND session_date<? AND semantics IN ('start','end') AND CAST(amount_cny AS REAL)>0 GROUP BY slot HAVING COUNT(DISTINCT session_date)>=5)",args)[0][0]
        return {'historical_days':totals['days'], 'slots_with_five_days':ready,
                'total_continuous_slots':237,'semantics_verified':bool(totals['n']) and not totals['unqualified']}

    async def prepare(self, symbol, force=False):
        if symbol in self.pending:
            return
        self.pending.add(symbol)
        self.save(symbol,state='FETCHING',message='正在核验证券资料')
        try:
            at = now(); ev = self.evidence()
            value = await self.transport.call('metadata:'+symbol,quote,symbol)
            at = now()
            meta = instrument(symbol,value,at,ev.get('calendar'))
            with self.store.transaction() as db:
                db.execute('INSERT INTO instruments VALUES (?,?) ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload',(symbol,dump(meta)))
            status = self.status(symbol)
            # Keep a measured price-regime warning until the history is rechecked.
            if status.get('baseline_warning'):
                meta['baseline_warning'] = status['baseline_warning']
                with self.store.transaction() as db:
                    db.execute('UPDATE instruments SET payload=? WHERE symbol=?',(dump(meta),symbol))
            history_due = force or status.get('history_checked_date') != at.date().isoformat()
            if history_due:
                self.save(symbol,message='正在下载真实历史成交额')
                rows = await self.transport.call('history:'+symbol,sina_rows,symbol)
                semantics = ev.get('provider',{}).get('history_timestamp_semantics','UNKNOWN')
                reference_date = timestamp(meta['quote_at']).date().isoformat()
                prior_rows = [r for r in rows if r['day'][:10]<reference_date]
                regime_changed = False
                if prior_rows:
                    previous_close = Decimal(str(max(prior_rows,key=lambda r:r['day'])['close']))
                    reference_close = Decimal(meta['previous_close_cny'])
                    regime_changed = abs(previous_close-reference_close)>max(Decimal('.02'),reference_close*Decimal('.002'))
                if regime_changed:
                    # A changed ex-right/reference price invalidates a naive
                    # cross-day comparison; keep evidence but withhold HIGH.
                    semantics = 'UNKNOWN'
                    meta['baseline_warning'] = 'PRICE_REGIME_CHANGED'
                    with self.store.transaction() as db:
                        db.execute('UPDATE instruments SET payload=? WHERE symbol=?',(dump(meta),symbol))
                history = []
                for row in rows:
                    label = datetime.fromisoformat(row['day'])
                    amount = Decimal(str(row['amount']))
                    if not amount.is_finite() or amount<0:
                        raise SourceError('HISTORY_INVALID_AMOUNT')
                    if label.date()>=at.date() or label.date().isoformat() not in ev.get('calendar',{}).get('trading_dates',[]):
                        continue
                    # Preserve raw labels while unqualified; the engine will
                    # never use UNKNOWN records as a trading baseline.
                    slot = (label-timedelta(minutes=1) if semantics=='end' else label).strftime('%H:%M')
                    if semantics!='UNKNOWN' and not ('09:30'<=slot<'11:30' or '13:00'<=slot<'14:57'):
                        continue
                    history.append((symbol,label.date().isoformat(),slot,'sina/minute',str(amount),at.isoformat(),semantics))
                if not regime_changed:
                    meta.pop('baseline_warning',None)
                with self.store.transaction() as db:
                    db.execute('UPDATE instruments SET payload=? WHERE symbol=?',(dump(meta),symbol))
                    db.execute('INSERT INTO source_snapshots VALUES (?,?,?,?) ON CONFLICT(symbol,source) DO UPDATE SET observed_at=excluded.observed_at,payload=excluded.payload',(symbol,'sina/minute',at.isoformat(),dump(rows)))
                    db.execute('DELETE FROM baseline_amounts WHERE symbol=? AND source=?',(symbol,'sina/minute'))
                    db.executemany('INSERT INTO baseline_amounts VALUES (?,?,?,?,?,?,?) ON CONFLICT(symbol,session_date,slot,source) DO NOTHING',history)
                self.save(symbol,history_checked_date=at.date().isoformat(),baseline_warning='PRICE_REGIME_CHANGED' if regime_changed else None)
            reason = metadata_reason(meta,at)
            self.save(symbol,state='WAITING_SESSION' if meta['suspended'] is None else 'RESTRICTED' if reason else 'PREPARED',
                      message='已获取资料，等待交易时段核验' if meta['suspended'] is None else '风险或上市状态不满足监控条件' if reason else '资料准备完成',
                      error=None,baseline=self.baseline_status(symbol,at),metadata_checked_date=at.date().isoformat())
        except (SourceError,ValueError,KeyError,TypeError,ArithmeticError) as error:
            self.save(symbol,state='ERROR',message='准备未完成，将自动重试',error=error.code if isinstance(error,SourceError) else 'METADATA_INVALID')
        finally:
            self.pending.discard(symbol)

    async def refresh_due(self):
        at = now()
        symbols = []
        for row in self.store.rows('SELECT symbol FROM watchlist WHERE enabled=1'):
            state = self.status(row['symbol'])
            if state.get('state')=='WAITING_SESSION' and state.get('metadata_checked_date')==at.date().isoformat() and session(at,self.evidence().get('calendar'))!='CONTINUOUS':
                continue
            age = (at-timestamp(state['updated_at'])).total_seconds() if state.get('updated_at') else float('inf')
            # A pre-calendar import may temporarily classify an old listing as NEW.
            # Retry restrictions instead of stranding that stock until tomorrow.
            retry_restricted = state.get('state')=='RESTRICTED' and age>=300
            if retry_restricted or state.get('metadata_checked_date')!=at.date().isoformat() or state.get('state') in ('ERROR','WAITING_SESSION','QUEUED'):
                if age>=60:
                    symbols.append(row['symbol'])
        await asyncio.gather(*(self.prepare(s) for s in symbols))
