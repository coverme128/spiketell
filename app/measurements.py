"""Symbol-minute coverage and receipt latency; missing observations stay missing."""
import json
import math
from bisect import bisect_left,bisect_right
from datetime import datetime, time, timedelta

from app.domain.market import TZ, timestamp, metadata_reason
from app.repo.store import dump


def minutes(day):
    for start,end in ((time(9,30),time(11,30)),(time(13),time(14,57))):
        cursor = datetime.combine(day,start,TZ)
        stop = datetime.combine(day,end,TZ)
        while cursor<stop:
            yield cursor+timedelta(minutes=1)
            cursor += timedelta(minutes=1)


def record_expected(store, at, calendar):
    date = at.date().isoformat()
    if date not in (calendar or {}).get('trading_dates',[]):
        return
    rows = store.rows('SELECT w.*,i.payload FROM watchlist w LEFT JOIN instruments i USING(symbol) WHERE w.enabled=1')
    with store.transaction() as db:
        for row in rows:
            meta = json.loads(row['payload']) if row['payload'] else {}
            # Unknown metadata is not an excuse to shrink the denominator.
            # Only a dated, explicit suspension record permits exclusion.
            excluded = meta.get('suspended') is True and meta.get('checked_at','')[:10]==date and meta.get('suspension_evidence')
            for end in minutes(at.date()):
                if end>at or end<=timestamp(row['added_at']):
                    continue
                db.execute('INSERT OR IGNORE INTO minute_coverage VALUES (?,?,?,NULL,?,?)',
                           (row['symbol'],end.isoformat(),'EXCLUDED_SUSPENSION' if excluded else 'EXPECTED',
                            'SUSPENDED' if excluded else 'NO_VALID_FINAL_BAR',dump(meta)))
        old = db.execute('SELECT * FROM session_observations WHERE session_date=?',(date,)).fetchone()
        in_session = time(9,30)<=at.time().replace(tzinfo=None)<=time(11,31) or time(13)<=at.time().replace(tzinfo=None)<=time(14,58)
        if in_session:
            if old:
                previous = timestamp(old['last_seen_at'])
                same_half = (previous.hour<12)==(at.hour<12)
                gap = (at-previous).total_seconds() if same_half else max(0,(datetime.combine(at.date(),time(11,30),TZ)-previous).total_seconds())+max(0,(at-datetime.combine(at.date(),time(13),TZ)).total_seconds())
                db.execute('UPDATE session_observations SET last_seen_at=?,max_gap_seconds=MAX(max_gap_seconds,?) WHERE session_date=?',(at.isoformat(),gap,date))
            else:
                db.execute('INSERT INTO session_observations(session_date,started_at,last_seen_at) VALUES (?,?,?)',(date,at.isoformat(),at.isoformat()))


def record_valid(store, bars, errors, instruments, at):
    with store.transaction() as db:
        for bar in bars:
            if bar['symbol'] in errors or metadata_reason(instruments.get(bar['symbol']),at):
                continue
            lag = (timestamp(bar['received_at'])-timestamp(bar['bar_end_at'])).total_seconds()
            if not 0<=lag<=90:
                continue
            db.execute("UPDATE minute_coverage SET valid_received_at=COALESCE(valid_received_at,?),reason=NULL WHERE symbol=? AND bar_end_at=? AND eligibility='EXPECTED'",
                       (bar['received_at'],bar['symbol'],bar['bar_end_at']))


def percentile(values, ratio):
    return sorted(values)[max(0,math.ceil(len(values)*ratio)-1)] if values else None


def report(store, date=None, detailed=True):
    where = " WHERE eligibility='EXPECTED'"+(' AND substr(bar_end_at,1,10)=?' if date else '')
    args=(date,) if date else ()
    totals=store.rows('SELECT COUNT(*) AS expected,COUNT(valid_received_at) AS valid FROM minute_coverage'+where,args)[0]
    expected_count,valid_count=totals['expected'],totals['valid']
    missing = {}
    if detailed:
        for row in store.rows('SELECT symbol,bar_end_at FROM minute_coverage'+where+' AND valid_received_at IS NULL',args):
            missing.setdefault(row['symbol'],[]).append(row['bar_end_at'])
    per_day={}
    for row in store.rows('SELECT bar_end_at,COUNT(*) AS n FROM minute_coverage'+where+' GROUP BY bar_end_at',args):
        per_day.setdefault(row['bar_end_at'][:10],[]).append(row['n'])
    receipts = store.rows("SELECT r.*,e.payload FROM notification_receipts r JOIN episode_events e USING(event_id) WHERE r.kind='PAGE_VISIBLE'")
    lags = [float(r['lag_seconds']) for r in receipts if not date or json.loads(r['payload'])['bar_end_at'][:10]==date]
    receipt_ids = {r['event_id'] for r in receipts}
    presence = store.rows('SELECT * FROM browser_presence ORDER BY observed_at')
    presence_times=[timestamp(p['observed_at']) for p in presence]
    expected_visible = []
    for row in store.rows('SELECT event_id,payload FROM episode_events'):
        event=json.loads(row['payload'])
        if event['delivery_mode']!='LIVE' or not event.get('alert_kind') or (date and event['bar_end_at'][:10]!=date):
            continue
        event_at=timestamp(event['recorded_at'])
        latest={}
        start=bisect_left(presence_times,event_at-timedelta(seconds=40));end=bisect_right(presence_times,event_at)
        for state in presence[start:end]:
            latest[state['client_id']]=state['visible']
        if any(latest.values()):
            expected_visible.append(row['event_id'])
    missing_receipts=[event_id for event_id in expected_visible if event_id not in receipt_ids]
    sessions = []
    for row in store.rows('SELECT * FROM session_observations ORDER BY session_date'):
        if date and row['session_date']!=date:
            continue
        counts=per_day.get(row['session_date'],[])
        full_pool = len(counts)==237 and min(counts,default=0)>=50
        complete = (timestamp(row['started_at']).time().replace(tzinfo=None)<=time(9,31)
                    and timestamp(row['last_seen_at']).time().replace(tzinfo=None)>=time(14,57)
                    and row['max_gap_seconds']<=90 and full_pool)
        sessions.append({**dict(row),'complete_50_stock_session':complete})
    complete = sum(s['complete_50_stock_session'] for s in sessions)
    coverage = valid_count/expected_count if expected_count else None
    return {'status':'MEASURED' if complete>=2 and lags else 'INSUFFICIENT_EVIDENCE',
            'complete_sessions':complete,'sessions':sessions,'expected_eligible_symbol_minutes':expected_count,
            'valid_final_symbol_minutes':valid_count,'coverage_ratio':coverage,'missing_symbol_minutes':missing,
            'visible_alert_samples':len(lags),'visible_alert_p50_seconds':percentile(lags,.50),
            'visible_alert_p95_seconds':percentile(lags,.95),
            'expected_visible_alerts':len(expected_visible),'missing_visible_receipts':missing_receipts,
            'meets_numeric_targets':bool(complete>=2 and coverage is not None and coverage>=.95 and lags and expected_visible and not missing_receipts and percentile(lags,.95)<=45),
            'note':'无提醒样本时延迟保持空值；本报告不代替源权限、语义、通知与其他发布门禁。'}
