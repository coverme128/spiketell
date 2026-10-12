"""Observe live changing bars against a timestamped quote, then confirm closes.

Historical labels alone cannot qualify a source. Empty, stale or unchanging
samples leave the source unqualified and collect an inspectable explanation.
"""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from app.domain.market import TZ, now, session
from app.providers.akshare import normalize_rows
from app.providers.live import Finalizer
from app.providers.public import eastmoney_rows, sina_rows, quote, SourceError, Transport


class Calibration:
    def __init__(self, store, evidence, transport=None):
        self.store,self.evidence = store,evidence
        self.transport = transport or Transport(3)
        self.observations = {}
        self.finalizer = Finalizer()
        self.confirmed = {}

    def observe(self, source, symbol, row, quoted, at):
        label_key,close_key,volume_key = ('时间','收盘','成交量') if source=='eastmoney' else ('day','close','volume')
        label = datetime.fromisoformat(row[label_key]).replace(tzinfo=TZ)
        quote_at = datetime.fromtimestamp(int(quoted['f86']),TZ)
        if not 0<=(at-quote_at).total_seconds()<=5 or not 12<=at.second<=48:
            return
        if abs(Decimal(str(row[close_key]))-Decimal(str(quoted['f43'])))>Decimal('.01'):
            return
        offset = (label-at.replace(second=0,microsecond=0)).total_seconds()
        if offset not in (0,60):
            return
        semantics = 'start' if offset==0 else 'end'
        key = (source,symbol,label.isoformat())
        observations = self.observations.setdefault(key,[])
        value = {'at':at.isoformat(),'label':label.isoformat(),'close':str(row[close_key]),
                 'volume':str(row[volume_key]),'quote_at':quote_at.isoformat(),'quote_close':str(quoted['f43']),
                 'amount':str(row['成交额'] if source=='eastmoney' else row['amount']),
                 'quote_amount':str(quoted['f48']),'quote_volume':str(quoted.get('f47','0')),
                 'semantics':semantics}
        if not observations or observations[-1]['at']!=value['at']:
            observations.append(value)
        if len(observations)>=3:
            span = (datetime.fromisoformat(observations[-1]['at'])-datetime.fromisoformat(observations[0]['at'])).total_seconds()
            changes = len({(o['close'],o['volume']) for o in observations})
            flow_matches = 0
            volume_matches = 0
            for left,right in zip(observations,observations[1:]):
                minute_delta = Decimal(right['amount'])-Decimal(left['amount'])
                quote_delta = Decimal(right['quote_amount'])-Decimal(left['quote_amount'])
                if minute_delta>0 and quote_delta>0 and abs(minute_delta-quote_delta)<=max(Decimal('100'),quote_delta*Decimal('.01')):
                    flow_matches += 1
                    row_volume = Decimal(right['volume'])-Decimal(left['volume'])
                    quote_volume = Decimal(right['quote_volume'])-Decimal(left['quote_volume'])
                    # Eastmoney minute and quote volumes are both in lots.
                    if source=='eastmoney' and row_volume>0 and quote_volume>0 and abs(row_volume-quote_volume)<=1:
                        volume_matches += 1
            if span>=15 and changes>=2 and flow_matches>=2 and len({o['semantics'] for o in observations})==1:
                self.confirmed[(source,symbol)] = {'semantics':semantics,'observations':observations[-5:],'amount_delta_matches':flow_matches,'volume_delta_matches':volume_matches}

    async def step(self):
        at = now();ev = self.evidence()
        provider = ev.get('provider',{})
        if not provider.get('personal_use_confirmed') or provider.get('finalization_verified'):
            return
        if session(at,ev.get('calendar'))!='CONTINUOUS':
            self.store.save_evidence('calibration_status',{'state':'WAITING_SESSION','message':'将在连续竞价时段自动采样核验，不使用休市标签作结论'})
            return
        clock = ev.get('clock',{})
        from app.config import qualification_reasons
        if 'CLOCK_UNVERIFIED' in qualification_reasons(ev,at):
            return
        symbols = ['SH.600000','SZ.000001']
        raw = {}
        try:
            for symbol in symbols:
                em,si,qt = await asyncio.gather(self.transport.call('em:'+symbol,eastmoney_rows,symbol),
                    self.transport.call('si:'+symbol,sina_rows,symbol),self.transport.call('qt:'+symbol,quote,symbol),return_exceptions=True)
                if isinstance(em,Exception):raise em
                if isinstance(qt,Exception):raise qt
                if isinstance(si,Exception):si=[]
                observed = now()
                self.observe('eastmoney',symbol,em[-1],qt,observed)
                if si:self.observe('sina',symbol,si[-1],qt,observed)
                raw[symbol] = (em,si,observed)
            keys = [(source,symbol) for source in ('eastmoney','sina') for symbol in symbols]
            available = [self.confirmed[key] for key in keys if key in self.confirmed]
            state = {'state':'OBSERVING','observed_at':now().isoformat(),'qualified_sample_count':len(available),
                     'required_sample_count':4,'message':'对照实时报价观察两只股票的分钟边界与收盘后稳定性'}
            if len(available)==4:
                em_semantics = {self.confirmed[('eastmoney',s)]['semantics'] for s in symbols}
                si_semantics = {self.confirmed[('sina',s)]['semantics'] for s in symbols}
                if len(em_semantics)!=1 or len(si_semantics)!=1:
                    state.update(state='CONFLICT',message='两股分钟标签语义不一致，继续阻断信号')
                else:
                    em_kind,si_kind = next(iter(em_semantics)),next(iter(si_semantics))
                    checks = []
                    for symbol,(em,si,observed) in raw.items():
                        bars,_,invalid = normalize_rows(em,symbol,em_kind,observed)
                        final = [b for b in self.finalizer.accept(bars,observed) if 0<=(observed-datetime.fromisoformat(b['bar_end_at'])).total_seconds()<=60]
                        lookup = {(datetime.fromisoformat(r['day'])-(timedelta(minutes=1) if si_kind=='end' else timedelta())).isoformat():r for r in si}
                        matched = []
                        for bar in final:
                            other = lookup.get(datetime.fromisoformat(bar['bar_start_at']).replace(tzinfo=None).isoformat())
                            if other and abs(Decimal(bar['close'])-Decimal(other['close']))<=Decimal('.01') and abs(Decimal(bar['amount_cny'])-Decimal(other['amount']))<=max(Decimal('100'),Decimal(bar['amount_cny'])*Decimal('.01')):
                                matched.append(bar['bar_end_at'])
                        checks.append({'symbol':symbol,'matched_final_minutes':matched,'invalid':invalid})
                    state['cross_source_checks'] = checks
                    if all(c['matched_final_minutes'] and not c['invalid'] for c in checks):
                        samples = [{'source':key[0],'symbol':key[1],**self.confirmed[key]} for key in keys]
                        qualified = {**provider,'name':'akshare','timestamp_semantics':em_kind,'history_timestamp_semantics':si_kind,
                                     'timestamp_samples':samples,'finalization_verified':True,
                                     'finalization_policy':'two_identical_post_close_observations_5s_apart_min_close_age_8s',
                                     'qualified_at':now().isoformat(),'cross_source_checks':checks,'capacity_verified':False}
                        self.store.save_evidence('provider',qualified)
                        state.update(state='QUALIFIED',message='盘中时间语义与分钟稳定性已取得样本，准备验证股票池吞吐')
                        # Re-map staged historical labels using measured semantics.
                        with self.store.transaction() as db:
                            db.execute("DELETE FROM preparation")
            if state['state']!='QUALIFIED':
                self.qualify_primary(provider,raw,state)
            self.store.save_evidence('calibration_status',state)
        except (SourceError,ValueError,KeyError,TypeError,ArithmeticError) as error:
            self.store.save_evidence('calibration_status',{'state':'RETRYING','message':'采样暂时失败，将自动重试',
                                      'error':error.code if isinstance(error,SourceError) else 'CALIBRATION_INVALID_SAMPLE','at':now().isoformat()})

    def qualify_primary(self, provider, raw, state):
        """Qualify live OHLCV independently from optional historical baselines.

        Two symbols must each have changing minute amount AND volume matching
        timestamped quote deltas, then the observed minute must close and remain
        identical in two post-close reads. No guessed labels or historical HIGH.
        """
        symbols=['SH.600000','SZ.000001']
        samples=[self.confirmed.get(('eastmoney',s)) for s in symbols]
        state['primary_qualified_samples']=sum(bool(s and s.get('volume_delta_matches',0)>=2) for s in samples)
        state['primary_required_samples']=2
        state['history_status']='UNVERIFIED'
        if not all(s and s.get('amount_delta_matches',0)>=2 and s.get('volume_delta_matches',0)>=2 for s in samples):
            return
        kinds={s['semantics'] for s in samples}
        if len(kinds)!=1:
            state.update(state='CONFLICT',message='主行情源两股的分钟标签语义不一致，继续阻断')
            return
        kind=next(iter(kinds));checks=[]
        for symbol,sample in zip(symbols,samples):
            rows,_,observed=raw[symbol]
            bars,excluded,invalid=normalize_rows(rows,symbol,kind,observed)
            final=self.finalizer.accept(bars,observed)
            label=datetime.fromisoformat(sample['observations'][-1]['label'])
            end=label+(timedelta(minutes=1) if kind=='start' else timedelta())
            matching=[]
            for b in final:
                if datetime.fromisoformat(b['bar_end_at'])!=end or not 0<=(observed-end).total_seconds()<=90:
                    continue
                shares=Decimal(b['volume_shares']);amount=Decimal(b['amount_cny'])
                # Bound the currency unit using observed prices and shares;
                # allow one rounded lot, never a 100x unit mismatch.
                tolerance=Decimal(b['high'])*100
                last=sample['observations'][-1]
                if shares>=Decimal(last['volume'])*100 and amount>=Decimal(last['amount']) and shares>0 and Decimal(b['low'])*shares-tolerance<=amount<=Decimal(b['high'])*shares+tolerance:
                    matching.append(b)
            checks.append({'symbol':symbol,'observed_label':label.isoformat(),'confirmed_final_bars':matching,'invalid':invalid})
        state['primary_close_checks']=checks
        if not all(c['confirmed_final_bars'] and not c['invalid'] for c in checks):return
        qualified={**provider,'name':'akshare','timestamp_semantics':kind,'history_timestamp_semantics':'UNKNOWN',
                   'timestamp_samples':[{'source':'eastmoney','symbol':s,**sample} for s,sample in zip(symbols,samples)],
                   'finalization_verified':True,'finalization_policy':'two_identical_post_close_observations_5s_apart_min_close_age_8s',
                   'qualified_at':now().isoformat(),'primary_close_checks':checks,'capacity_verified':False,
                   'qualification_method':'two_symbols_quote_amount_volume_deltas_and_observed_final_close',
                   'history_warning':'HISTORY_SOURCE_NOT_ALIGNED; unverified baselines cannot enable HIGH or VOLUME_BREAKOUT'}
        self.store.save_evidence('provider',qualified)
        state.update(state='QUALIFIED',message='主行情分钟边界、成交单位及收盘稳定性已核验；历史基准尚未核验，先验证股票池采集')
        with self.store.transaction() as db:db.execute('DELETE FROM preparation')

    async def run(self):
        while True:
            await self.step()
            await asyncio.sleep(10)
