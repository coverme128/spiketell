"""Build evidence indexes from actual test results; live gates stay pending."""
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]


def read_tests(path):
    if not path.exists():return {}
    return {c.attrib.get('name',''): 'FAIL' if c.find('failure') is not None or c.find('error') is not None else 'SKIP' if c.find('skipped') is not None else 'PASS' for c in ET.parse(path).iter('testcase')}


def main():
    backend=read_tests(ROOT/'evidence/backend-tests.xml');browser=read_tests(ROOT/'evidence/browser-tests.xml')
    mapping={
    1:['test_atomic_creation_and_restart_dedup'],2:['test_frozen_fixtures[S02_NO_TRIGGER]'],3:['test_frozen_fixtures[S03_LOW_TURNOVER]'],4:['test_frozen_fixtures[S04_MISSING_BASELINE]'],
    5:['test_atomic_creation_and_restart_dedup'],6:['test_future_bar_rejected','test_frozen_fixtures[S07_NON_FINAL]'],7:['test_market_sessions[09:29-CLOSED]','test_market_sessions[11:45-MIDDAY_BREAK]','test_market_sessions[14:59-CLOSE_AUCTION]'],8:['test_no_cross_lunch_returns'],
    9:['test_partial_health_counts_only_fresh_symbols'],10:['test_delayed_recovery_never_notifies'],11:['test_medium_to_high_one_upgrade'],12:['test_medium_to_high_one_upgrade'],13:['test_expiry_and_immutable_history'],14:['test_cooldown_and_quiet_window'],15:['test_cooldown_and_quiet_window'],16:['test_calendar_fail_closed_and_holiday'],
    17:['test_metadata_restrictions[ST]','test_metadata_restrictions[NEW]','test_metadata_restrictions[DELISTED]','test_metadata_restrictions[UNKNOWN]'],18:['test_adapter_units_and_time'],19:['test_clock_and_timestamp_qualification'],20:['test_partial_health_counts_only_fresh_symbols','test_calendar_fail_closed_and_holiday'],
    21:['notification denied and quiet mode persist'],22:['notification denied and quiet mode persist'],23:['test_sse_replay_delivery_mode','SSE reconnect fallback and missing detail'],24:['test_atomic_creation_and_restart_dedup','test_backup_restore'],26:['responsive 390','responsive 430'],27:['test_batch_import_partial_and_duplicate'],28:['test_revision_is_append_only_and_invalidates'],29:['test_exact_threshold_without_rounding'],
    31:['SSE reconnect fallback and missing detail'],32:['notification denied and quiet mode persist'],33:['test_partial_health_counts_only_fresh_symbols'],34:['test_partial_health_counts_only_fresh_symbols'],35:['test_single_instance_lock'],36:['test_symbol_conversions[600000-SH.600000]'],37:['test_simulation_database_cannot_be_opened_live','test_simulated_events_never_live'],38:['test_simulated_events_never_live'],39:['test_diagnostics_exposes_blockers'],40:['test_disabled_watch_has_no_signal']}
    mapping[29]=['test_score_65_and_burst_boundary','test_exact_threshold_without_rounding']
    mapping[30]=['test_sort_order_independent_of_scan']
    mapping[41]=['test_ignore_and_full_csv_keep_episode_audit','activity exports full server history with exact version fields']
    tests={**backend,**browser}
    partial={9:'Injected stale projection; actual 120s network outage pending',17:'Synthetic metadata gate only; authoritative instrument service pending',20:'Injected clock jump; external NTP reachability pending',21:'Browser permission branch; OS notification behavior pending',22:'UI coverage statement tested; browser-closed OS observation pending',23:'Replay envelope and browser fallback tested; full reconnect stress pending',25:'Two complete 50-stock live sessions required',29:'Exact Decimal trigger tested; score65/burst2 boundary pending',30:'Deterministic ranking needs dedicated scan-order test',31:'Missing episode UI verified; actual OS notification click pending',33:'Health projection tested; live in-flight stale alert scenario pending',38:'Copy inspected; full notification branch coverage pending',39:'Blocked-source diagnostics tested; real subscribed-account denial pending'}
    partial.pop(29,None);partial.pop(30,None)
    partial.update({
        1:'Engine creation/outbox verified; actual visible notification pending',
        7:'Session classification tested; per-session end-to-end alert suppression pending',
        12:'Upgrade scenario tested; dedicated five-minute sustained scenario pending',
        18:'Synthetic unit conversion tested; intraday quote comparison pending',
        20:'Injected clock checks and real SNTP probe available; loss/recovery integration pending',
        24:'Store reopen and backup tested; abrupt process termination/recovery pending',
        32:'Quiet setting persists; real OS suppression with live Radar updates pending',
        35:'Lock contention tested; two launched scheduler processes and crash recovery pending',
        36:'Canonical conversions tested; actual cross-exchange feed alignment pending',
        17:'Automatic real metadata preparation implemented; intraday suspension/status refresh qualification pending',
    })
    entries=[]
    for n in range(1,43):
        names=mapping.get(n,[]);passed=bool(names) and all(tests.get(name)=='PASS' for name in names)
        entries.append({'case_id':f'T{n:03}','status':'PASS_AUTOMATED' if passed and n not in partial else 'PARTIAL' if passed else 'PENDING','tests':names,'evidence':['evidence/backend-tests.xml','evidence/browser-tests.xml'],'remaining':partial.get(n,'' if passed else 'No complete execution evidence')})
    commit=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip() or None
    metadata={'generated_at':datetime.now(timezone.utc).isoformat(),'base_commit':commit,'working_tree_changes':True,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('app','web/src','tests','scripts') for p in sorted((ROOT/folder).rglob('*')) if p.is_file() and '__pycache__' not in str(p)}}
    gates=[]
    fixtures_path=ROOT/'spec/fixtures/rule_scenarios.json'
    fixture_names=[f"test_frozen_fixtures[{case['id']}]" for case in json.loads(fixtures_path.read_text())['cases']] if fixtures_path.exists() else []
    deterministic_names=fixture_names+mapping[1]+mapping[29]+mapping[30]
    descriptions={1:'Scope and three-page screenshots',2:'Personal-use source rights',3:'Two verified timestamp samples',4:'10/30/50 valid symbol-minute coverage',5:'Two complete sessions, visible alert p95',6:'Freshness/calendar/clock guards',7:'Frozen deterministic rule fixtures',8:'Dedup and restart persistence',9:'Responsive UI and trustworthy status',10:'Failure and recovery qualification',11:'WAL migration and backup/restore',12:'Actual OS notification reachability',13:'Localhost host/origin restrictions',14:'Complete release evidence and implementation commit'}
    for n in range(1,15):
        status='PENDING'
        # Passing component tests is not proof of the entire release gate.
        if n == 7 and fixture_names and all(backend.get(name)=='PASS' for name in deterministic_names):status='PASS_AUTOMATED'
        if n in (6,8,10,11,13) and backend and all(s=='PASS' for s in backend.values()):status='PARTIAL'
        if n in (1,9,12) and browser and all(s=='PASS' for s in browser.values()):status='PARTIAL'
        gates.append({'gate':f'G{n:02}','status':status,'requirement':descriptions[n]})
    for name,value in [('test-matrix',{'metadata':metadata,'cases':entries}),('release-gates',{'metadata':metadata,'release_status':'DATA_PROVIDER_BLOCKED','gates':gates,'backend_tests':len(backend),'browser_tests':len(browser)})]:
        (ROOT/'evidence'/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    # Indexing tests must never erase independently collected live measurements.
    live_path=ROOT/'evidence/live-session-measurement.json'
    if not live_path.exists():
        live_path.write_text(json.dumps({'status':'INSUFFICIENT_EVIDENCE','complete_sessions':0,'expected_eligible_symbol_minutes':None,'valid_final_symbol_minutes':None,'coverage_ratio':None,'visible_alert_p50_seconds':None,'visible_alert_p95_seconds':None,'explanation':'Placeholder only; no live-session aggregation implemented.'},indent=2)+'\n')
    print(f'Evidence indexed: {len(backend)} backend, {len(browser)} browser tests. DATA_PROVIDER_BLOCKED.')


if __name__=='__main__':main()
