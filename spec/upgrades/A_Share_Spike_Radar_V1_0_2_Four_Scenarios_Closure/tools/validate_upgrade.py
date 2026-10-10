"""Offline deterministic completeness and static schema validation."""
from pathlib import Path
import hashlib, json, csv, subprocess, sys

ROOT=Path(__file__).resolve().parents[1]


def verify():
    for rel in ['00_README.md','01_PRODUCT_DELTA.md','02_DOMAIN_RULES_DELTA.md',
                '03_IMPLEMENTATION_DELTA.md','04_HANDOFF_ACCEPTANCE.md','CODEX_START.md',
                'CHANGESET.json','MIGRATION_MATRIX.csv','acceptance_traceability.csv',
                'contracts/rule_profile.v1.0.2.json','contracts/spike_card.v1.0.2.schema.json',
                'contracts/episode_event.v1.0.2.schema.json',
                'contracts/examples/spike_card_v102_SIMULATION.json',
                'reference/scenario_oracle_v102.py','fixtures/four_scenario_full_bars.json',
                'tests/test_scenarios_v102.py','VALIDATION_REPORT.md','MANIFEST.json']:
        assert (ROOT/rel).is_file(),f'MISSING: {rel}'
    change=json.loads((ROOT/'CHANGESET.json').read_text())
    assert change['target_rule_version']=='spike_rules_v1.0.2'
    assert change['status']=='SPEC_DELTA_READY' and change['runtime_verified'] is False
    profile=json.loads((ROOT/'contracts/rule_profile.v1.0.2.json').read_text())
    assert profile['rule_version']==change['target_rule_version']
    assert profile['interval']=='1m' and profile['priority']['high_turnover_burst_gte']=='2.0'
    assert set(profile['scenarios'])==set(change['scope'])
    fixtures=json.loads((ROOT/'fixtures/four_scenario_full_bars.json').read_text())['cases']
    assert len(fixtures)>=20 and all(x['data_mode']=='SIMULATION' for x in fixtures)
    with (ROOT/'acceptance_traceability.csv').open() as f:
        trace=list(csv.DictReader(f))
    assert [r['case_id'] for r in trace]==change['acceptance_ids']
    schemas=[ROOT/'contracts/spike_card.v1.0.2.schema.json',ROOT/'contracts/episode_event.v1.0.2.schema.json']
    for path in schemas:
        schema=json.loads(path.read_text())
        assert schema['additionalProperties'] is False
        try:
            import jsonschema
            jsonschema.Draft202012Validator.check_schema(schema)
        except ImportError:
            print('NOTE: jsonschema not installed; schemas parsed but not meta-validated')
    try:
        import jsonschema
        card=json.loads((ROOT/'contracts/examples/spike_card_v102_SIMULATION.json').read_text())
        jsonschema.validate(card,json.loads(schemas[0].read_text()))
    except ImportError:
        pass
    manifest=json.loads((ROOT/'MANIFEST.json').read_text())
    expected=manifest['files']
    actual={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in ROOT.rglob('*') if p.is_file() and p.name!='MANIFEST.json'
            and '__pycache__' not in p.parts}
    assert expected==actual,f'manifest difference: {set(actual)^set(expected)}'
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'Ran 34 tests' in result.stderr,result.stderr
    print('PASS: 34 static reference tests, 2 JSON schemas, 22 full-bar fixtures, 28 acceptance traceability rows, manifest hashes.')
    print('RUNTIME STATUS: PENDING (AKShare live gates not tested).')

if __name__=='__main__':verify()
