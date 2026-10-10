import copy
import itertools

from app.domain.rules import evaluate
from app.runtime import Runtime


def test_score_65_and_burst_boundary(case):
    bars=copy.deepcopy(case['bars'])
    bars[-1].update(close='10.20',high='10.20')
    result=evaluate(bars,['2000000.00001']*5,case['now'])
    assert result['score']==65
    assert result['priority']=='MEDIUM'
    result=evaluate(bars,['2000000']*5,case['now'])
    assert result['priority']=='HIGH'
    bars[-1].update(close='10.08',high='10.08')
    result=evaluate(bars,['1333333']*5,case['now'])
    assert result['score']==65 and result['priority']=='HIGH'


def test_sort_order_independent_of_scan(store):
    rt=Runtime(store)
    candidates=[{'symbol':symbol,'priority':priority,'score':score,'trigger_bar_start_at':'2026-10-09T10:00:00+08:00','feed_health':'HEALTHY'} for symbol,priority,score in [('SZ.000001','HIGH',65),('SH.600000','HIGH',65),('SZ.300308','MEDIUM',90),('SH.688001','HIGH',75)]]
    rt.feed=lambda at=None:{'monitored_count':4,'available_count':4}
    for permutation in itertools.permutations(candidates):
        rt.cards=lambda at=None:list(permutation)
        assert [c['symbol'] for c in rt.radar()['top_cards']]==['SH.688001','SH.600000','SZ.000001']
