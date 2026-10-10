import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reference.rule_oracle import evaluate, make_episode_id, next_episode_state

FIXTURE = json.loads((ROOT / 'fixtures' / 'rule_scenarios.json').read_text(encoding='utf-8'))

class TestRuleOracle(unittest.TestCase):
    def test_cases(self):
        for case in FIXTURE['cases']:
            with self.subTest(case=case['id']):
                actual=evaluate(case['bars'],case['prior_same_slot_amounts'],case['now'])
                for key, value in case['expected'].items():
                    self.assertEqual(actual[key], value, (case['id'],key,actual))

    def test_episode_id_is_deterministic(self):
        args=('SH.600000','2026-10-09','2026-10-09T09:59:00+08:00','spike_rules_v1.0.0')
        self.assertEqual(make_episode_id(*args), make_episode_id(*args))
        self.assertNotEqual(make_episode_id(*args), make_episode_id('SZ.000001',*args[1:]))
        self.assertEqual(len(make_episode_id(*args)),24)

    def test_episode_same_card_expires_after_three_weak(self):
        now=evaluate(FIXTURE['cases'][0]['bars'],['1000000']*5,'2026-10-09T10:00:10+08:00')
        state=next_episode_state(None,now,'10.12')
        self.assertEqual(state['state'],'NEW')
        missed={'triggered':False,'score':0}
        for expected in ('WEAKENING','WEAKENING','EXPIRED'):
            state=next_episode_state(state,missed,'10.04',consecutive_weak=state['weak'],nontrigger_minutes=state['nontrigger'])
            self.assertEqual(state['state'],expected)

    def test_replayed_terminal_does_not_reopen(self):
        prev={'state':'EXPIRED','weak':3,'nontrigger':3,'score':0,'trigger_close':'10.12'}
        self.assertEqual(next_episode_state(prev, {'triggered':True,'score':90}, '10.30'), prev)

    def test_rule_version_score_is_not_probability(self):
        got=evaluate(FIXTURE['cases'][0]['bars'], ['1000000']*5,'2026-10-09T10:00:10+08:00')
        self.assertNotIn('buy',str(got).lower())
        self.assertNotIn('probability',str(got).lower())

if __name__=='__main__':
    unittest.main()
