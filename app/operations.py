"""Automatic local preparation, calendar/clock refresh and daily maintenance."""
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

from app.domain.market import now, timestamp
from app.timecheck import measure_clock


class Operations:
    def __init__(self, runtime):
        self.runtime = runtime

    async def bootstrap(self):
        rt = self.runtime;at = now();ev = rt.evidence()
        calendar = ev.get('calendar',{})
        due = not calendar or calendar.get('valid_to','')<at.date().isoformat()
        if calendar.get('checked_at'):
            due = due or (at-timestamp(calendar['checked_at'])).total_seconds()>86400
        if due:
            process = await asyncio.create_subprocess_exec(sys.executable,'-m','app.providers.calendar_worker',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            try:
                raw,_ = await asyncio.wait_for(process.communicate(),30)
                if process.returncode or len(raw)>500_000:
                    raise ValueError('CALENDAR_UNAVAILABLE')
                dates = json.loads(raw)
                if not dates or not min(dates)<=at.date().isoformat()<=max(dates):
                    raise ValueError('CALENDAR_RANGE_INCOMPLETE')
                start = f'{at.year-1}-01-01'
                calendar = {'source':'akshare/tool_trade_date_hist_sina','checked_at':now().isoformat(),
                            'valid_from':max(start,min(dates)),'valid_to':max(dates),'trading_dates':[d for d in dates if d>=start]}
                rt.store.save_evidence('calendar',calendar)
            finally:
                if process.returncode is None:
                    process.kill();await process.wait()
        clock = ev.get('clock',{})
        if not clock.get('checked_at') or (at-timestamp(clock['checked_at'])).total_seconds()>900:
            witness = await asyncio.to_thread(measure_clock,clock.get('host','time.cloudflare.com'))
            rt.clock_witness = witness
            rt.store.save_evidence('clock',witness)

    def maintenance(self):
        rt = self.runtime;at = now()
        if rt.store.evidence('maintenance',{}).get('date')==at.date().isoformat():
            return
        directory = Path(rt.store.path).parent/'backups'
        directory.mkdir(exist_ok=True)
        target = directory/(Path(rt.store.path).stem+'-'+at.date().isoformat()+'.sqlite3')
        if not target.exists():
            rt.store.backup(target)
        retention = rt.store.settings().get('retention_days',90)
        cutoff = (at-timedelta(days=retention)).date().isoformat()
        with rt.store.transaction() as db:
            ids = [r[0] for r in db.execute("SELECT episode_id FROM episodes WHERE session_date<? AND state IN ('EXPIRED','INVALIDATED')",(cutoff,))]
            for episode_id in ids:
                db.execute('DELETE FROM notification_receipts WHERE event_id IN (SELECT event_id FROM episode_events WHERE episode_id=?)',(episode_id,))
                for table in ('ignored_episodes','alert_outbox','episode_events','episodes'):
                    db.execute(f'DELETE FROM {table} WHERE episode_id=?',(episode_id,))
            for table,column in (('minute_bars','bar_start_at'),('bar_decisions','bar_start_at'),('baseline_amounts','session_date'),('poll_samples','recorded_at'),('minute_coverage','bar_end_at'),('session_observations','session_date'),('browser_presence','observed_at')):
                db.execute(f'DELETE FROM {table} WHERE {column}<?',(cutoff,))
        # Keep the latest seven backups belonging to this database only.
        for old in sorted(directory.glob(Path(rt.store.path).stem+'-*.sqlite3'))[:-7]:
            old.unlink()
        rt.store.save_evidence('maintenance',{'date':at.date().isoformat(),'backup':str(target),'retention_days':retention,'database_check':rt.store.rows('PRAGMA quick_check')[0][0]})

    async def run(self):
        while True:
            failures = {}
            for name,operation in (('bootstrap',self.bootstrap),('preparation',self.runtime.preparation.refresh_due)):
                try:
                    await operation()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failures[name] = type(error).__name__
            try:
                maintenance_task=asyncio.create_task(asyncio.to_thread(self.maintenance))
                try:
                    await asyncio.shield(maintenance_task)
                except asyncio.CancelledError:
                    await maintenance_task
                    raise
            except Exception as error:
                failures['maintenance'] = type(error).__name__
            self.runtime.store.save_evidence('operations',{'state':'RETRYING' if failures else 'RUNNING','errors':failures,'checked_at':now().isoformat()})
            await asyncio.sleep(15)
