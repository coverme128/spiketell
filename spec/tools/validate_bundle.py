"""No third-party dependencies. Validates delivery integrity and rule oracle fixtures."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from reference.rule_oracle import evaluate

REQUIRED=[
  'README.md','00_MASTER.md',
  '01_PRODUCT/01-PRD.md','01_PRODUCT/02-UX-COPY.md',
  '02_DOMAIN_RULES/01-SPIKE-RULEBOOK.md','02_DOMAIN_RULES/02-MARKET-DATA.md','02_DOMAIN_RULES/03-EPISODE-ALERTS.md',
  '03_IMPLEMENTATION/01-ARCHITECTURE.md','03_IMPLEMENTATION/02-API-DATA-CONTRACT.md','03_IMPLEMENTATION/03-CODEX-PLAN.md',
  '04_PRODUCTION_HANDOFF/01-RELEASE-GATES.md','04_PRODUCTION_HANDOFF/02-TEST-MATRIX.md','04_PRODUCTION_HANDOFF/03-CODEX-START.md','04_PRODUCTION_HANDOFF/04-OPERATIONS.md',
  'contracts/openapi.yaml','contracts/rule_profile.v1.json','contracts/minute_bar.schema.json','contracts/spike_card.schema.json','contracts/episode_event.schema.json',
  'fixtures/rule_scenarios.json','reference/rule_oracle.py','tests/test_oracle.py','tests/test_contracts.py','contracts/examples/README.md','contracts/examples/minute_bar.json','contracts/examples/spike_card.json','contracts/examples/episode_event.json','contracts/examples/radar_response.json','SOURCES.md','DELIVERY_REPORT.md','MANIFEST.json'
]

def main():
    failures=[]
    for r in REQUIRED:
        path=ROOT/r
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f'missing or empty {r}')
    if failures:
        raise SystemExit('FAIL\n'+'\n'.join(failures))
    manifest=json.loads((ROOT/'MANIFEST.json').read_text(encoding='utf-8'))
    for r in REQUIRED:
        if r=='MANIFEST.json':
            continue
        digest=hashlib.sha256((ROOT/r).read_bytes()).hexdigest()
        if manifest['sha256'].get(r)!=digest:
            failures.append(f'hash mismatch {r}')
    for r in ('contracts/rule_profile.v1.json','contracts/minute_bar.schema.json','contracts/spike_card.schema.json','contracts/episode_event.schema.json','fixtures/rule_scenarios.json'):
        json.loads((ROOT/r).read_text(encoding='utf-8'))
    profile=json.loads((ROOT/'contracts/rule_profile.v1.json').read_text(encoding='utf-8'))
    assert profile['rule_version']=='spike_rules_v1.0.0'
    fixture=json.loads((ROOT/'fixtures/rule_scenarios.json').read_text(encoding='utf-8'))
    assert fixture['data_mode']=='SIMULATION'
    for case in fixture['cases']:
        actual=evaluate(case['bars'],case['prior_same_slot_amounts'],case['now'])
        for key,expected in case['expected'].items():
            if actual.get(key)!=expected:
                failures.append(f'Fixture mismatch {case["id"]}.{key}: got {actual.get(key)}, expected {expected}')
    if failures:
        raise SystemExit('FAIL\n'+'\n'.join(failures))
    print(f'PASS package files: {len(REQUIRED)}')
    print(f'PASS declared SHA256: {len(manifest["sha256"])}')
    print(f'PASS synthetic fixture cases: {len(fixture["cases"])}')
    print('STATUS: SPEC_READY (not runtime verified)')

if __name__=='__main__':
    main()
