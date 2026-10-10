from pathlib import Path
import json,sys
p=Path(__file__).resolve().parent
meta=json.loads((p/'CHANGESET.json').read_text(encoding='utf-8'))
cases=json.loads((p/'fixtures/minute_only_scenarios.json').read_text(encoding='utf-8'))['cases']
assert len(cases)==meta['scenario_test_count']==14
assert len(set(x['id'] for x in cases))==len(cases)
assert all(x['expected'] and x['check'] for x in cases)
assert meta['new_data_frequency']=='1m_final_only'
assert all((p/n).stat().st_size>0 for n in ('00_README.md','01_PRODUCT_DELTA.md','02_RULES_DELTA.md','03_CODEX_IMPLEMENTATION.md','04_TEST_AND_GATES.md'))
print('SPEC_DELTA_READY: 14 scenario contracts; original application/runtime not validated')
