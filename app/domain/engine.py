"""Atomic bar decisions, immutable evidence and restart-safe episode projection."""
import hashlib
import json
from datetime import timedelta

from app.config import PROFILE
from app.domain.market import adjacent, timestamp, validate_bar
from app.domain.rules import evaluate, make_episode_id, next_episode_state, first_attention_alert
from app.repo.store import dump

VERSION = PROFILE["rule_version"]
TERMINAL = ("EXPIRED", "INVALIDATED")


class Engine:
    def __init__(self, store, mode="LIVE"):
        self.store = store
        self.mode = mode

    def _save_episode(self, db, ep):
        db.execute("INSERT INTO episodes VALUES (?,?,?,?,?) ON CONFLICT(episode_id) DO UPDATE SET state=excluded.state,payload=excluded.payload",
                   (ep["episode_id"], ep["symbol"], ep["session_date"], ep["state"], dump(ep)))

    def _event(self, db, ep, bar, kind, prior, at, delivery="REPLAY", alert=None):
        card = self.card(ep)
        data = {"event_id": hashlib.sha256(f'{ep["episode_id"]}|{kind}|{bar["bar_start_at"]}'.encode()).hexdigest()[:24],
                "episode_id": ep["episode_id"], "symbol": ep["symbol"], "event_type": kind,
                "previous_state": prior, "next_state": ep["state"], "score": ep["score"], "priority": ep["priority"],
                "bar_start_at": bar["bar_start_at"], "bar_end_at": bar["bar_end_at"], "rule_version": ep.get("rule_version", "spike_rules_v1.0.0"),
                "source": bar["source"], "source_received_at": bar["received_at"], "delivery_mode": delivery,
                "recorded_at": at.isoformat(), "card": card, "alert_kind": alert,
                "fingerprint": hashlib.sha256(dump(bar).encode()).hexdigest()}
        db.execute("INSERT OR IGNORE INTO episode_events(event_id,episode_id,event_type,bar_start_at,recorded_at,payload) VALUES (?,?,?,?,?,?)",
                   (data["event_id"], ep["episode_id"], kind, bar["bar_start_at"], at.isoformat(), dump(data)))

    def close_old_sessions(self, at):
        with self.store.transaction() as db:
            rows = db.execute("SELECT payload FROM episodes WHERE session_date < ? AND state NOT IN ('EXPIRED','INVALIDATED')", (at.date().isoformat(),)).fetchall()
            for row in rows:
                ep = json.loads(row[0]); prior = ep["state"]
                ep.update(state="EXPIRED", updated_at=at.isoformat())
                self._save_episode(db, ep)
                self._event(db, ep, ep["bar"], "SESSION_CLOSED", prior, at)

    def ingest(self, bar, at, *, allow_signals=False, notify=False, baseline=None):
        validate_bar(bar)
        if timestamp(bar["bar_end_at"]) > at or timestamp(bar["received_at"]) > at:
            raise ValueError("FUTURE_BAR")
        symbol, start = bar["symbol"], bar["bar_start_at"]
        fingerprint = hashlib.sha256(dump({k: v for k, v in bar.items() if k not in ("source", "received_at")}).encode()).hexdigest()
        with self.store.transaction() as db:
            old = db.execute("SELECT * FROM minute_bars WHERE symbol=? AND bar_start_at=? ORDER BY revision DESC LIMIT 1", (symbol, start)).fetchone()
            if old and old["fingerprint"] == fingerprint:
                self.store.counter("duplicate_bars")
                return "DUPLICATE"
            revision = old["revision"] + 1 if old else 1
            db.execute("INSERT INTO minute_bars VALUES (?,?,?,?,?)", (symbol, start, revision, fingerprint, dump(bar)))
            if old:
                # A revision of any evidence in an episode's causal window invalidates it.
                # Never rewrite the original decision; conservative invalidation is auditable.
                for row in db.execute("SELECT payload FROM episodes WHERE symbol=? AND session_date=?", (symbol, start[:10])).fetchall():
                    ep = json.loads(row[0])
                    if start <= ep["bar"]["bar_start_at"]:
                        prior = ep["state"]
                        ep.update(state="INVALIDATED", updated_at=at.isoformat())
                        self._save_episode(db, ep)
                        self._event(db, ep, bar, f"CORRECTION_R{revision}", prior, at)
                progress_row = db.execute("SELECT payload FROM symbol_progress WHERE symbol=?", (symbol,)).fetchone()
                if progress_row:
                    progress = json.loads(progress_row[0]); progress.update(quiet=0, cooldown=0)
                    db.execute("UPDATE symbol_progress SET payload=? WHERE symbol=?", (dump(progress), symbol))
                self.store.counter("revised_bars")
                return "CORRECTION"
            if not allow_signals or (at - timestamp(bar["bar_end_at"])).total_seconds() > PROFILE["max_bar_age_seconds"]:
                self.store.counter("suppressed_stale_or_blocked")
                return "EVIDENCE_ONLY"
            watch = db.execute("SELECT enabled FROM watchlist WHERE symbol=?", (symbol,)).fetchone()
            if not watch or not watch[0]:
                return "DISABLED"
            progress_row = db.execute("SELECT payload FROM symbol_progress WHERE symbol=?", (symbol,)).fetchone()
            progress = json.loads(progress_row[0]) if progress_row else {}
            if progress.get("date") != start[:10]:
                progress = {"date": start[:10], "quiet": 0, "cooldown": 0}
            if progress.get("last") and start <= progress["last"]:
                return "OUT_OF_ORDER"
            gap = bool(progress.get("last") and not adjacent(progress["last"], start))
            if gap:
                progress.update(quiet=0, cooldown=0)
            rows = db.execute("SELECT payload FROM minute_bars b WHERE symbol=? AND bar_start_at<=? AND (bar_start_at>=? OR substr(bar_start_at,12,5)=?) AND revision=(SELECT MAX(revision) FROM minute_bars WHERE symbol=b.symbol AND bar_start_at=b.bar_start_at) ORDER BY bar_start_at", (symbol, start, start[:10], start[11:16])).fetchall()
            all_bars = [json.loads(row[0]) for row in rows]
            current_day = [b for b in all_bars if b["bar_start_at"][:10] == start[:10]]
            if baseline is None:
                # Distinct prior dates, same slot; never today/future observations.
                amounts = {b['bar_start_at'][:10]:b['amount_cny'] for b in all_bars if b['bar_start_at'][:10]<start[:10] and b['bar_start_at'][11:16]==start[11:16]}
                for row in db.execute("SELECT session_date,amount_cny FROM baseline_amounts WHERE symbol=? AND session_date<? AND slot=? AND semantics IN ('start','end') ORDER BY session_date DESC",(symbol,start[:10],start[11:16])):
                    amounts.setdefault(row['session_date'],row['amount_cny'])
                meta_row = db.execute('SELECT payload FROM instruments WHERE symbol=?',(symbol,)).fetchone()
                changed_regime = meta_row and json.loads(meta_row[0]).get('baseline_warning')=='PRICE_REGIME_CHANGED'
                baseline = [] if changed_regime else [amounts[date] for date in sorted(amounts,reverse=True)]
            signal = evaluate(current_day, baseline, at.isoformat())
            db.execute("INSERT OR IGNORE INTO bar_decisions VALUES (?,?,?,?)", (symbol, start, VERSION, dump(signal)))
            active = db.execute("SELECT payload FROM episodes WHERE symbol=? AND state NOT IN ('EXPIRED','INVALIDATED')", (symbol,)).fetchone()
            ep = json.loads(active[0]) if active else None
            if ep and ep.get("rule_version", "spike_rules_v1.0.0") != VERSION:
                # End the old projection with its original score/version. No historical
                # recomputation or immediate re-alert when the behavior version changes.
                prior = ep["state"]
                ep.update(state="EXPIRED", updated_at=at.isoformat())
                self._save_episode(db, ep)
                self._event(db, ep, ep["bar"], "RULE_VERSION_CLOSED", prior, at)
                progress.update(quiet=0, cooldown=0)
                ep = None
            if ep and gap:
                prior = ep["state"]; ep.update(state="INVALIDATED", updated_at=at.isoformat())
                self._save_episode(db, ep); self._event(db, ep, bar, "DATA_GAP", prior, at)
                ep = None
            previous_quiet = progress.get("quiet", 0)
            progress["quiet"] = 0 if signal["triggered"] else previous_quiet + 1
            progress["cooldown"] = progress.get("cooldown", 0) + 1
            progress["last"] = start
            prior_state, prior_priority = (ep["state"], ep["priority"]) if ep else (None, None)
            if ep is None and signal["triggered"] and signal["is_attention_eligible"] and not gap:
                prior_episode = db.execute("SELECT 1 FROM episodes WHERE symbol=? AND session_date=? LIMIT 1", (symbol, start[:10])).fetchone()
                can_open = not prior_episode or (progress["cooldown"] >= PROFILE["episode"]["cooldown_minutes_after_expiry"] and previous_quiet >= PROFILE["episode"]["quiet_minutes_for_new_episode"])
                if can_open:
                    ep = {"episode_id": make_episode_id(symbol, start[:10], start, VERSION), "symbol": symbol,
                          "session_date": start[:10], "rule_version": VERSION, "trigger_bar_start_at": start, "trigger_close": bar["close"],
                          "state": "NEW", "score": signal["score"], "weak": 0, "nontrigger": 0,
                          "started_at": at.isoformat()}
                    self.store.counter("episode_created_count")
            elif ep:
                ep.update(next_episode_state(ep, signal, bar["close"], consecutive_weak=ep["weak"], nontrigger_minutes=ep["nontrigger"]))
            if ep:
                previous_scenarios = ep.get("signal", {}).get("matched_scenarios", [])
                ep["matched_scenarios"] = list(dict.fromkeys(ep.get("matched_scenarios", []) + signal["matched_scenarios"]))
                ep.update(priority=signal["priority"], score=signal["score"], signal=signal, bar=bar, updated_at=at.isoformat(), data_mode=self.mode)
                self._save_episode(db, ep)
                if ep["state"] in TERMINAL:
                    progress["cooldown"] = 0
                alert = None
                if ep["state"] == "NEW":
                    alert = first_attention_alert(signal)
                elif prior_priority in ("LOW", "MEDIUM") and ep["priority"] == "HIGH" and signal["is_attention_eligible"] and ep["state"] not in TERMINAL:
                    alert = "HIGH_UPGRADE"
                if alert:
                    cursor = db.execute("INSERT OR IGNORE INTO alert_outbox VALUES (?,?,?,?)", (f'{ep["episode_id"]}:{alert}:{VERSION}', ep["episode_id"], alert, at.isoformat()))
                    if not cursor.rowcount:
                        alert = None; self.store.counter("alert_dedup_count")
                delivery = "SIMULATION" if self.mode == "SIMULATION" else "LIVE" if notify else "REPLAY"
                kind = ("REVERSAL_OBSERVED" if signal["force_weakening"] else
                        "CREATED" if prior_state is None else
                        "SCENARIOS_CHANGED" if previous_scenarios != signal["matched_scenarios"] else "UPDATED")
                self._event(db, ep, bar, kind, prior_state, at, delivery, alert)
            db.execute("INSERT INTO symbol_progress VALUES (?,?) ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload", (symbol, dump(progress)))
            return signal

    def card(self, ep):
        b, s = ep["bar"], ep["signal"]
        meta = self.store.rows("SELECT payload FROM instruments WHERE symbol=?", (ep["symbol"],))
        name = json.loads(meta[0][0]).get("name", ep["symbol"]) if meta else ep["symbol"]
        return {"episode_id": ep["episode_id"], "symbol": ep["symbol"], "name": name, "rule_version": ep.get("rule_version", "spike_rules_v1.0.0"),
                "trigger_bar_start_at": ep["trigger_bar_start_at"], "last_bar_end_at": b["bar_end_at"],
                "received_at": b["received_at"], "reference_close_cny": b["close"], "ret1_pct": s["ret1_pct"] or "0",
                "ret3_pct": s["ret3_pct"], "turnover_burst": s["turnover_burst"], "score": ep["score"],
                "priority": ep["priority"], "episode_state": ep["state"], "action": s["action"], "reasons": s["reasons"],
                "risks": s["risks"], "feed_health": "STOPPED", "data_mode": ep["data_mode"], "updated_at": ep["updated_at"],
                "as_of_label": "最后已完成分钟 K 线收盘价",
                **({"primary_scenario": s.get("primary_scenario"),
                    "matched_scenarios": s.get("matched_scenarios", []),
                    "is_attention_eligible": s.get("is_attention_eligible", False)}
                   if ep.get("rule_version") == VERSION else {})}
