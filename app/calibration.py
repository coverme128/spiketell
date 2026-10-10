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
                 'quote_amount':str(quoted['f48']),
                 'semantics':semantics}
        if not observations or observations[-1]['at']!=value['at']:
            observations.append(value)
        if len(observations)>=3:
            span = (datetime.fromisoformat(observations[-1]['at'])-datetime.fromisoformat(observations[0]['at'])).total_seconds()
            changes = len({(o['close'],o['volume']) for o in observations})
            flow_matches = 0
            for left,right in zip(observations,observations[1:]):
                minute_delta = Decimal(right['amount'])-Decimal(left['amount'])
                quote_delta = Decimal(right['quote_amount'])-Decimal(left['quote_amount'])
                if minute_delta>0 and quote_delta>0 and abs(minute_delta-quote_delta)<=max(Decimal('100'),quote_delta*Decimal('.01')):
                    flow_matches += 1
            if span>=15 and changes>=2 and flow_matches>=2 and len({o['semantics'] for o in observations})==1:
                self.confirmed[(source,symbol)] = {'semantics':semantics,'observations':observations[-5:]}

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
                    self.transport.call('si:'+symbol,sina_rows,symbol),self.transport.call('qt:'+symbol,quote,symbol))
                observed = now()
                self.observe('eastmoney',symbol,em[-1],qt,observed)
                self.observe('sina',symbol,si[-1],qt,observed)
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
            self.store.save_evidence('calibration_status',state)
        except (SourceError,ValueError,KeyError,TypeError,ArithmeticError) as error:
            self.store.save_evidence('calibration_status',{'state':'RETRYING','message':'采样暂时失败，将自动重试',
                                      'error':error.code if isinstance(error,SourceError) else 'CALIBRATION_INVALID_SAMPLE','at':now().isoformat()})

    async def run(self):
        while True:
            await self.step()
            await asyncio.sleep(10)
