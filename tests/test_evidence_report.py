import json

from scripts import report


def test_indexing_preserves_live_measurements_and_does_not_pass_whole_gates(tmp_path, monkeypatch):
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    (evidence / 'backend-tests.xml').write_text('<testsuite><testcase name="component"/></testsuite>')
    (evidence / 'browser-tests.xml').write_text('<testsuite><testcase name="browser"/></testsuite>')
    measured = '{"status":"INSUFFICIENT_EVIDENCE","complete_sessions":1}\n'
    (evidence / 'live-session-measurement.json').write_text(measured)
    monkeypatch.setattr(report, 'ROOT', tmp_path)
    report.main()
    assert (evidence / 'live-session-measurement.json').read_text() == measured
    gates = {g['gate']:g['status'] for g in json.loads((evidence / 'release-gates.json').read_text())['gates']}
    assert gates['G05'] == 'PENDING'
    assert all(gates[g] == 'PARTIAL' for g in ('G08', 'G09', 'G10', 'G11', 'G12', 'G13'))
    assert json.loads((evidence / 'release-gates.json').read_text())['release_status'] == 'DATA_PROVIDER_BLOCKED'
