import asyncio
import json
import logging
import os
import random
import time

from app.config import evidence, qualification_reasons
from app.domain.engine import Engine, TERMINAL
from app.domain.market import metadata_reason, now, session, timestamp
from app.providers.akshare import AKShareProvider
from app.repo.store import dump
from app.preparation import Preparation
from app.providers.live import LiveProvider
from app.measurements import record_expected, record_valid

log = logging.getLogger("radar")


class Runtime:
    def __init__(self, store, mode="LIVE"):
        if mode not in ("LIVE", "SIMULATION"):
            raise ValueError("INVALID_RADAR_MODE")
        self.store, self.mode = store, mode
        self.engine = Engine(store, mode)
        self.started = now()
        self.start_mono = time.monotonic()
        self.last_poll = None
        self.last_error = None
        self.recovered = False
        self.failures = 0
        self.requests = []
        self.clock_witness = None
        self.preparation = Preparation(store,self.evidence)
        self.live_provider = None
        self.capacity_successes = 0

    def evidence(self):
        value = evidence()
        for key in ('provider','calendar','clock'):
            saved = self.store.evidence(key)
            if saved:
                value[key] = {**value.get(key,{}),**saved}
        if self.clock_witness:
            value["clock"] = self.clock_witness
        return value

    def watchlist(self, at=None):
        at = at or now()
        records = []
        for r in self.store.rows("SELECT w.*,i.payload AS metadata,h.payload AS health FROM watchlist w LEFT JOIN instruments i USING(symbol) LEFT JOIN provider_health h USING(symbol) ORDER BY w.added_at,w.symbol"):
            meta = json.loads(r["metadata"]) if r["metadata"] else None
            health = json.loads(r["health"]) if r["health"] else {}
            reason = metadata_reason(meta, at)
            if not reason:
                reason = health.get("error") or ("STALE" if not health.get("bar_end_at") or (at - timestamp(health["bar_end_at"])).total_seconds() > 90 else None)
            records.append({"symbol": r["symbol"], "name": (meta or {}).get("name", "待验证名称"),
                            "enabled": bool(r["enabled"]), "source_state": reason or "VALID", "metadata": meta,
                            "excluded_rows":health.get("excluded_rows", {}),
                            "preparation":self.preparation.status(r['symbol']),
                            "baseline":self.preparation.baseline_status(r['symbol'],at),
                            "last_bar_end_at": health.get("bar_end_at"), "lag_seconds": (at - timestamp(health["bar_end_at"])).total_seconds() if health.get("bar_end_at") else None})
        return records

    def feed(self, at=None):
        at = at or now()
        ev = self.evidence()
        market = session(at, ev.get("calendar"))
        reasons = qualification_reasons(ev, at)
        if market == "UNKNOWN":
            reasons.append("CALENDAR_UNKNOWN")
        elif market != "CONTINUOUS":
            reasons.append("NO_SESSION")
        drift = abs((at - self.started).total_seconds() - (time.monotonic() - self.start_mono))
        if drift > 2:
            reasons.append("CLOCK_JUMP")
        items = [w for w in self.watchlist(at) if w["enabled"]]
        available = sum(w["source_state"] == "VALID" for w in items)
        if not items:
            reasons.append("WATCHLIST_EMPTY")
        elif available < len(items):
            reasons.append("PARTIAL_COVERAGE" if available else "FEED_UNAVAILABLE")
        if any(w["source_state"] == "VALID" and w["lag_seconds"] > 45 for w in items):
            reasons.append("LATENCY_ELEVATED")
        if self.last_error:
            reasons.append(self.last_error)
        if self.mode == "SIMULATION":
            reasons.append("SIMULATION_ONLY")
        qualified_capacity = ev.get('provider',{}).get('qualified_pool_size')
        if qualified_capacity is not None and len(items)>qualified_capacity:
            reasons.append('CAPACITY_UNVERIFIED')
        blocking = [r for r in reasons if r not in ("PARTIAL_COVERAGE", "LATENCY_ELEVATED")]
        status = "STOPPED" if blocking else "DEGRADED" if reasons else "HEALTHY"
        ends = [w["last_bar_end_at"] for w in items if w["last_bar_end_at"]]
        return {"status": status, "session": market, "updated_at": at.isoformat(), "available_count": available,
                "monitored_count": len(items), "last_bar_end_at": max(ends, default=None), "reasons": reasons,
                "data_mode": self.mode, "release_status": "DATA_PROVIDER_BLOCKED" if qualification_reasons(ev, at) else "IMPLEMENTED_PENDING_RUNTIME"}

    def cards(self, at=None):
        at = at or now()
        feed = self.feed(at)
        valid = {w["symbol"] for w in self.watchlist(at) if w["enabled"] and w["source_state"] == "VALID"}
        cards = []
        for row in self.store.rows("SELECT payload FROM episodes ORDER BY rowid DESC"):
            ep = json.loads(row[0]); card = self.engine.card(ep)
            current = (feed["status"] != "STOPPED" and ep["symbol"] in valid and ep["state"] not in TERMINAL
                       and 0 <= (at - timestamp(card["last_bar_end_at"])).total_seconds() <= 90)
            card["feed_health"] = feed["status"] if current else "STOPPED"
            cards.append(card)
        return cards

    def radar(self):
        at = now(); feed = self.feed(at); cards = self.cards(at)
        active = [c for c in cards if c["feed_health"] != "STOPPED" and c["priority"] != "LOW" and c.get("is_attention_eligible", True)]
        ignored = {r[0] for r in self.store.rows('SELECT episode_id FROM ignored_episodes')}
        active = [c for c in active if c.get('episode_id') not in ignored]
        # Stable tie breaks: priority, score, first trigger descending, symbol ascending.
        active.sort(key=lambda c: c["symbol"])
        active.sort(key=lambda c: c["trigger_bar_start_at"], reverse=True)
        active.sort(key=lambda c: ({"HIGH": 0, "MEDIUM": 1}[c["priority"]], -c["score"]))
        return {"feed": feed, "monitored_count": feed["monitored_count"], "available_count": feed["available_count"],
                "today_episode_count": sum(c["trigger_bar_start_at"][:10] == at.date().isoformat() for c in cards),
                "high_count": sum(c["priority"] == "HIGH" for c in active), "top_cards": active[:3], "all_cards": active,
                "risk_cards": [c for c in cards if c["feed_health"] != "STOPPED" and c.get("primary_scenario") == "SPIKE_REVERSAL" and c["episode_id"] not in ignored],
                "historical_cards": [c for c in cards if c['feed_health']=='STOPPED'][:3], "cursor": self.store.sequence()}

    def scenario_diagnostics(self, date=None):
        date = date or now().date().isoformat()
        rows = self.store.rows("""SELECT d.symbol,d.bar_start_at,d.rule_version,d.payload,b.payload AS bar
            FROM bar_decisions d JOIN minute_bars b ON b.symbol=d.symbol AND b.bar_start_at=d.bar_start_at AND b.revision=1
            WHERE d.bar_start_at>=? AND d.bar_start_at<? AND json_array_length(d.payload,'$.diagnostics')>0
            ORDER BY d.bar_start_at DESC,d.symbol LIMIT 30""", (date,date+'Z'))
        return [{"symbol":r['symbol'],"bar_start_at":r['bar_start_at'],"rule_version":r['rule_version'],
                 "bar_end_at":json.loads(r['bar'])['bar_end_at'],"received_at":json.loads(r['bar'])['received_at'],
                 "source":json.loads(r['bar'])['source'],"data_mode":self.mode,
                 "event_types":["REVERSAL_OBSERVED" if x=='INTRAMINUTE_PEAK_REVERSAL' else x for x in json.loads(r['payload'])['diagnostics']],
                 "decision":json.loads(r['payload'])} for r in rows]

    def card_evidence(self, ids):
        facts = {}
        for episode_id in ids:
            rows = self.store.rows("SELECT payload FROM episodes WHERE episode_id=?", (episode_id,))
            if rows:
                bar = json.loads(rows[0][0])["bar"]
                facts[episode_id] = {"amount_cny":bar["amount_cny"],"source":bar["source"]}
        return facts

    async def poll(self):
        at = now(); ev = self.evidence()
        clock_host = ev.get("clock", {}).get("host")
        if clock_host:
            from app.timecheck import measure_clock
            clock = ev.get("clock", {})
            try:
                due = not clock.get("checked_at") or (at-timestamp(clock["checked_at"])).total_seconds() >= 900
                if due:
                    self.clock_witness = await asyncio.to_thread(measure_clock, clock_host)
                    ev["clock"] = self.clock_witness
            except (OSError, ValueError):
                self.clock_witness = {"source": "NTP_FAILED", "host": clock_host}
                ev["clock"] = self.clock_witness
        at = now()  # NTP checked_at must not be compared to the earlier poll clock.
        record_expected(self.store,at,ev.get('calendar'))
        self.engine.close_old_sessions(at)
        # Refresh operator-qualified instrument metadata before making decisions.
        with self.store.transaction() as db:
            for symbol, meta in ev.get("instruments", {}).items():
                db.execute("INSERT INTO instruments VALUES (?,?) ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload", (symbol, dump(meta)))
        if self.mode != "LIVE" or session(at, ev.get("calendar")) != "CONTINUOUS" or [r for r in qualification_reasons(ev, at) if r!='CAPACITY_UNVERIFIED']:
            return
        if abs((at - self.started).total_seconds() - (time.monotonic() - self.start_mono)) > 2:
            self.last_error = "CLOCK_JUMP"; return
        watched = [w for w in self.watchlist(at) if w["enabled"] and not metadata_reason(w["metadata"], at)]
        symbols = [w["symbol"] for w in watched]
        budget = min(300, int(os.getenv("RADAR_MAX_CALLS_PER_MINUTE", "120")))
        calls = len(symbols)*2
        if calls > budget:
            self.last_error = "REQUEST_BUDGET_EXCEEDED"; return
        self.requests = [t for t in self.requests if (at - t).total_seconds() < 60]
        if len(self.requests) + calls > budget:
            wait = max(0.05,60-(at-min(self.requests)).total_seconds()+.05)
            if wait>5:
                return
            await asyncio.sleep(wait)
            at = now()
            self.requests = [t for t in self.requests if (at-t).total_seconds()<60]
            if len(self.requests)+calls>budget:
                return
        cursors = {r["symbol"]: r["start"] for r in self.store.rows("SELECT symbol,MAX(bar_start_at) AS start FROM minute_bars GROUP BY symbol")}
        self.requests.extend([at] * calls)
        if self.live_provider is None or self.live_provider.semantics!=ev['provider']['timestamp_semantics']:
            self.live_provider = LiveProvider(ev['provider']['timestamp_semantics'],transport=self.preparation.transport)
        result = await self.live_provider.fetch_final_bars(symbols,cursors)
        current = now()
        record_expected(self.store,current,ev.get('calendar'))
        record_valid(self.store,result.bars,result.errors,{w['symbol']:w['metadata'] for w in watched},current)
        # Prove the actual enabled pool before allowing its signals. The
        # separate 50-stock / two-day release gate is still measured separately.
        timely = sum(s not in result.errors and 0<=result.lag.get(s,999)<=45 for s in symbols)
        self.capacity_successes = self.capacity_successes+1 if symbols and timely/len(symbols)>=.95 and (current-at).total_seconds()<=35 else 0
        if self.capacity_successes>=3 and len(symbols)>ev['provider'].get('qualified_pool_size',0):
            provider = {**ev['provider'],'capacity_verified':True,'qualified_pool_size':len(symbols),
                        'capacity_observed_at':current.isoformat(),'capacity_successful_rounds':self.capacity_successes}
            self.store.save_evidence('provider',provider)
            ev['provider'] = provider
        gates_ok = (session(current, ev.get("calendar")) == "CONTINUOUS" and not qualification_reasons(ev, current)
                    and len(symbols)<=ev['provider'].get('qualified_pool_size',50)
                    and abs((current-self.started).total_seconds()-(time.monotonic()-self.start_mono)) <= 2)
        safe_notify = self.last_poll is not None and self.last_error is None
        for symbol in symbols:
            bars = sorted((b for b in result.bars if b["symbol"] == symbol), key=lambda b: b["bar_start_at"])
            latest = bars[-1]["bar_end_at"] if bars else None
            previous_health = self.store.rows("SELECT payload FROM provider_health WHERE symbol=?", (symbol,))
            old_health = json.loads(previous_health[0][0]) if previous_health else {}
            recovered_symbol = not old_health or old_health.get("error") or not old_health.get("bar_end_at") or (at - timestamp(old_health["bar_end_at"])).total_seconds() > 90
            for bar in bars:
                if bar["bar_start_at"][:10] not in ev["calendar"]["trading_dates"]:
                    continue
                fresh = 0 <= (current - timestamp(bar["bar_end_at"])).total_seconds() <= 90
                # Cold start / recovery bars supply evidence only. Next new bar is eligible.
                self.engine.ingest(bar, current, allow_signals=gates_ok and fresh and not recovered_symbol and symbol not in result.errors,
                                   notify=safe_notify and not recovered_symbol and bar is bars[-1])
            with self.store.transaction() as db:
                db.execute("INSERT INTO provider_health VALUES (?,?) ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload",
                           (symbol, dump({"bar_end_at": latest, "error": result.errors.get(symbol), "excluded_rows":result.excluded_rows.get(symbol, {}), "checked_at": current.isoformat()})))
        self.last_error = "PROVIDER_UNAVAILABLE" if symbols and len(result.errors) == len(symbols) else None
        self.failures = self.failures + 1 if self.last_error else 0
        self.last_poll = current
        with self.store.transaction() as db:
            db.execute("INSERT INTO poll_samples(recorded_at,payload) VALUES (?,?)", (current.isoformat(), dump({"requested_count":len(symbols),"error_count":len(result.errors),"valid_symbols":sum(0 <= lag <= 90 and symbol not in result.errors for symbol,lag in result.lag.items()),"lag_seconds":result.lag,"errors":result.errors})))
        log.info(dump({"event": "poll", "at": current.isoformat(), "requested": len(symbols), "errors": result.errors, "lag": result.lag}))

    async def run(self):
        while True:
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = "SCHEDULER_ERROR"
                self.failures += 1
                log.error(dump({"event": "poll_failed", "type": type(exc).__name__}))
            delay = max(1, 70 - now().second-now().microsecond/1_000_000) if not self.failures else min(300, 15 * 2 ** min(self.failures, 4)) + random.random()
            await asyncio.sleep(delay)
