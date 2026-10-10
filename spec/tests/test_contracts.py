import importlib.util
import json
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HAS_SCHEMA=importlib.util.find_spec('jsonschema') is not None
HAS_YAML=importlib.util.find_spec('yaml') is not None

class TestContracts(unittest.TestCase):
    @unittest.skipUnless(HAS_SCHEMA, 'optional jsonschema not installed')
    def test_json_examples_against_schemas(self):
        import jsonschema
        for name in ('minute_bar','spike_card','episode_event'):
            with self.subTest(name=name):
                schema=json.loads((ROOT/'contracts'/f'{name}.schema.json').read_text())
                example=json.loads((ROOT/'contracts/examples'/f'{name}.json').read_text())
                jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker()).validate(example)

    @unittest.skipUnless(HAS_YAML, 'optional PyYAML not installed')
    def test_openapi_yaml_parses(self):
        import yaml
        data=yaml.safe_load((ROOT/'contracts/openapi.yaml').read_text())
        self.assertEqual(data['openapi'],'3.0.3')
        self.assertIn('/radar',data['paths'])

    def test_live_examples_are_explicitly_simulated(self):
        for name in ('spike_card','episode_event','radar_response'):
            item=json.loads((ROOT/'contracts/examples'/f'{name}.json').read_text())
            if name=='spike_card':
                self.assertEqual(item['data_mode'],'SIMULATION')
            elif name=='episode_event':
                self.assertEqual(item['delivery_mode'],'SIMULATION')
            else:
                self.assertEqual(item['top_cards'][0]['data_mode'],'SIMULATION')

if __name__=='__main__':
    unittest.main()
