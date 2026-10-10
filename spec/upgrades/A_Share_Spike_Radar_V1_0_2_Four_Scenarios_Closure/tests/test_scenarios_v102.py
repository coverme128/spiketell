"""Synthetic, deterministic F201–F228 + compatibility acceptance tests.

These do not inspect a real trading platform and cannot certify AKShare latency.
"""
import unittest, json, pathlib, sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reference'))
from scenario_oracle_v102 import evaluate, next_alert, first_attention_alert, episode_update_hint, RULE_VERSION

fixtures=json.loads((ROOT/'fixtures/four_scenario_full_bars.json').read_text())['cases']


class V102Fixtures(unittest.TestCase):
    pass


def make_case(case):
    def tester(self):
        actual=evaluate(case['bars'],case['prior_same_slot_amounts'],case['now'])
        for k,v in case['expect'].items():
            if k=='scenario_contains':
                self.assertTrue(set(v).issubset(set(actual['matched_scenarios'])))
            elif k=='raw_score_min':
                self.assertGreaterEqual(actual['raw_score'],v)
            else:
                self.assertEqual(actual.get(k),v,f"{case['id']}:{k} — {actual}")
        self.assertEqual(actual['rule_version'],RULE_VERSION)
        if actual['primary_scenario']=='SPIKE_REVERSAL':
            self.assertFalse(actual['is_attention_eligible'])
            self.assertIsNone(first_attention_alert(actual,episode_is_new=True,already_first_attention=False))
    return tester


for _case in fixtures:
    setattr(V102Fixtures,'test_'+_case['id'],make_case(_case))


class V102Policy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results={x['id']:evaluate(x['bars'],x['prior_same_slot_amounts'],x['now']) for x in fixtures}

    def test_F218_existing_reversal_weakens_same_episode(self):
        r=self.results['F216_reversal_triggered']
        upd=episode_update_hint('episode_existing_abcdef012345',r)
        self.assertEqual(upd['episode_id'],'episode_existing_abcdef012345')
        self.assertEqual(upd['force_state'],'WEAKENING')
        self.assertFalse(upd['new_episode'])

    def test_F218_diagnostic_reversal_also_weakens_existing_episode(self):
        r=self.results['F215_reversal_only']
        self.assertFalse(r['triggered'])
        self.assertTrue(r['force_weakening'])
        update=episode_update_hint('episode_existing_abcdef012345',r)
        self.assertEqual(update['force_state'],'WEAKENING')
        self.assertFalse(update['new_episode'])

    def test_F220_existing_episode_scenario_change_no_first_alert(self):
        r=self.results['F208_breakout']
        self.assertIsNone(next_alert(r,episode_is_new=False,already_first_attention=True,
                                     prior_priority='MEDIUM',already_high_upgrade=False))

    def test_F221_breakout_first_notification_exact_once(self):
        r=self.results['F208_breakout']
        self.assertEqual(first_attention_alert(r,episode_is_new=True,already_first_attention=False),'BREAKOUT_NEW')
        self.assertIsNone(first_attention_alert(r,episode_is_new=True,already_first_attention=True))

    def test_F221_rapid_cold_first_notification_exact_once(self):
        r=self.results['F202_rapid_cold']
        self.assertEqual(first_attention_alert(r,episode_is_new=True,already_first_attention=False),'RAPID_NEW')
        self.assertIsNone(first_attention_alert(r,episode_is_new=True,already_first_attention=True))

    def test_F221_high_priority_over_scenarios(self):
        r=self.results['F219_both']
        self.assertEqual(r['priority'],'HIGH')
        self.assertEqual(first_attention_alert(r,episode_is_new=True,already_first_attention=False),'HIGH_NEW')

    def test_F221_high_upgrade_once(self):
        r=self.results['F219_both']
        self.assertEqual(next_alert(r,episode_is_new=False,already_first_attention=True,
                                    prior_priority='MEDIUM',already_high_upgrade=False),'HIGH_UPGRADE')
        self.assertIsNone(next_alert(r,episode_is_new=False,already_first_attention=True,
                                     prior_priority='MEDIUM',already_high_upgrade=True))

    def test_F221_accel_medium_notification(self):
        r=self.results['F204_accel']
        self.assertEqual(r['priority'],'MEDIUM')
        self.assertEqual(first_attention_alert(r,episode_is_new=True,already_first_attention=False),'ACCEL_NEW')

    def test_F227_deterministic_replay(self):
        for x in fixtures:
            r1=evaluate(x['bars'],x['prior_same_slot_amounts'],x['now'])
            r2=evaluate(x['bars'],x['prior_same_slot_amounts'],x['now'])
            self.assertEqual(r1,r2)

    def test_F228_old_rule_versions_listed(self):
        profile=json.loads((ROOT/'contracts/rule_profile.v1.0.2.json').read_text())
        self.assertEqual(profile['rule_version'],'spike_rules_v1.0.2')
        self.assertEqual(profile['prior_rule_versions'],['spike_rules_v1.0.0','spike_rules_v1.0.1'])
        self.assertEqual(profile['score']['ret1_steps'][0],{'gte':'1.8','points':30})
        self.assertEqual(profile['trigger']['ret1_pct_gte'],'0.8')

    def test_schema_has_scenario_fields(self):
        schema=json.loads((ROOT/'contracts/spike_card.v1.0.2.schema.json').read_text())
        self.assertFalse(schema['additionalProperties'])
        self.assertIn('primary_scenario',schema['properties'])
        self.assertIn('matched_scenarios',schema['properties'])
        self.assertNotIn('matched_scenarios',schema['required'])

    def test_no_second_level_or_buy_probability(self):
        profile=json.loads((ROOT/'contracts/rule_profile.v1.0.2.json').read_text())
        self.assertEqual(profile['interval'],'1m')
        self.assertIn('buy_recommendation',profile['non_goals'])
        self.assertIn('upside_probability',profile['non_goals'])
        self.assertTrue(profile['scenarios']['VOLUME_BREAKOUT']['independent_trigger'])


if __name__ == '__main__':
    unittest.main()
