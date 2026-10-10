import asyncio
import contextlib
import json
import os
import logging
import csv
import io
from logging.handlers import TimedRotatingFileHandler
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, qualification_reasons
from app.domain.market import now, symbol_id, timestamp, session
from app.lock import InstanceLock
from app.repo.store import Store, dump
from app.runtime import Runtime
from app.operations import Operations
from app.calibration import Calibration
from app.providers.public import quote, instrument, search, SourceError
from app.measurements import report as measurement_report
from app.verification import baseline_summary, stock_verification


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(min_length=1, max_length=100)


class EnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quiet_mode: StrictBool | None = None
    notification_enabled: StrictBool | None = None
    max_watchlist: int | None = Field(default=None, ge=1, le=50, strict=True)
    retention_days: int | None = Field(default=None,ge=7,le=365,strict=True)


class SourceConsent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    personal_use_confirmed: StrictBool


class BrowserPresence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_id: str=Field(min_length=8,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
    visible: StrictBool
    browser_at: datetime


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=16, max_length=64)
    kind: Literal["PAGE_VISIBLE", "OS_SHOWN", "CLICKED"]
    browser_at: datetime


def stream_payload(row, replay, runtime):
    data = json.loads(row["payload"])
    data["audit_sequence"] = row["sequence"]
    card = next((c for c in runtime.cards() if c["episode_id"] == data["episode_id"]), data["card"])
    data['card'] = card
    if runtime.store.rows('SELECT 1 FROM ignored_episodes WHERE episode_id=?',(data['episode_id'],)):
        replay = True
    if replay or runtime.feed()["status"] == "STOPPED" or card["feed_health"] == "STOPPED" or card.get("is_attention_eligible") is False or (now() - timestamp(data["recorded_at"])).total_seconds() > 90:
        data["delivery_mode"] = "REPLAY"
    return f'id: {row["sequence"]}\nevent: episode\ndata: {dump(data)}\n\n'


def create_app(db_path=None, scheduler=True):
    path = db_path or os.getenv("RADAR_DB", "data/radar.sqlite3")

    @asynccontextmanager
    async def lifespan(api):
        lock = InstanceLock(str(path) + ".lock")
        lock.acquire()
        store = Store(path)
        mode = os.getenv("RADAR_MODE", "LIVE")
        with store.transaction() as db:
            row = db.execute("SELECT value FROM settings WHERE key='data_mode'").fetchone()
            mismatch = bool(row and json.loads(row[0]) != mode)
            if not mismatch:
                db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('data_mode',?)", (dump(mode),))
        if mismatch:
            store.close(); lock.release()
            raise RuntimeError("LIVE_AND_SIMULATION_REQUIRE_SEPARATE_DATABASES")
        api.state.runtime = Runtime(store, mode)
        logger = logging.getLogger("radar")
        logger.setLevel(logging.INFO)
        handler = TimedRotatingFileHandler(Path(path).parent / "radar.log", when="midnight", backupCount=14, encoding="utf-8")
        logger.addHandler(handler)
        tasks = [asyncio.create_task(api.state.runtime.run()),asyncio.create_task(Operations(api.state.runtime).run()),
                 asyncio.create_task(Calibration(store,api.state.runtime.evidence,api.state.runtime.preparation.transport).run())] if scheduler and mode=='LIVE' else []
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            logger.removeHandler(handler); handler.close()
            store.close(); lock.release()

    api = FastAPI(title="SpikeTell · A 股异动雷达", version="1.0.2", lifespan=lifespan)
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @api.middleware("http")
    async def local_security(request, call_next):
        origin = request.headers.get("origin")
        port = int(os.getenv('RADAR_PORT','8765'))
        allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", "http://127.0.0.1:5173", "http://localhost:5173"}
        if origin and origin not in allowed:
            return JSONResponse({"code": "ORIGIN_REJECTED", "message": "仅允许本机页面访问"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"code": "ORIGIN_REJECTED", "message": "禁止跨站请求"}, status_code=403)
        if int(request.headers.get("content-length", "0")) > 65536:
            return JSONResponse({"code": "PAYLOAD_TOO_LARGE", "message": "请求过大"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @api.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"code": "INVALID_SETTINGS" if request.url.path.endswith("settings") else "INVALID_REQUEST", "message": "参数格式不合法"}, status_code=400)

    @api.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"code": str(exc.detail), "message": str(exc.detail)}, status_code=exc.status_code)

    def rt():
        return api.state.runtime

    @api.get("/api/v1/health/live")
    def live():
        return {"up": True}

    @api.get("/api/v1/health/ready")
    def ready():
        feed = rt().feed()
        return JSONResponse(feed, status_code=503 if feed["status"] == "STOPPED" else 200)

    @api.get("/api/v1/radar")
    def radar():
        data = rt().radar()
        data["card_evidence"] = rt().card_evidence({c["episode_id"] for c in data["all_cards"] + data["historical_cards"] + data["risk_cards"]})
        data["scenario_diagnostics"] = rt().scenario_diagnostics()
        return data

    @api.get("/api/v1/scenario-diagnostics")
    def scenario_diagnostics(date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        """Audit-only reversal / unverified breakout decisions; never an alert stream."""
        return {"items": rt().scenario_diagnostics(date)}

    @api.get("/api/v1/watchlist")
    def watchlist():
        return rt().watchlist()

    @api.post("/api/v1/watchlist")
    async def add_watchlist(body: ImportRequest):
        items = []; store = rt().store; at = now().isoformat()
        verified,failed = {},{}
        if scheduler:
            existing = {r[0] for r in store.rows('SELECT symbol FROM watchlist')}
            async def verify(value):
                try:
                    symbol = symbol_id(value)
                    if symbol in existing or symbol in verified:
                        return
                    raw = await rt().preparation.transport.call('metadata:'+symbol,quote,symbol)
                    verified[symbol] = instrument(symbol,raw,now(),rt().evidence().get('calendar'))
                except (SourceError,ValueError,KeyError,TypeError) as error:
                    failed[value] = error.code if isinstance(error,SourceError) else 'METADATA_INVALID'
            await asyncio.gather(*(verify(value) for value in dict.fromkeys(body.symbols)))
        with store.transaction() as db:
            for value in body.symbols:
                try:
                    symbol = symbol_id(value)
                except ValueError as error:
                    items.append({"symbol": value, "status": "REJECTED", "reason": str(error)}); continue
                if db.execute("SELECT 1 FROM watchlist WHERE symbol=?", (symbol,)).fetchone():
                    items.append({"symbol": symbol, "status": "ALREADY_EXISTS"}); continue
                if value in failed:
                    items.append({'symbol':symbol,'status':'REJECTED','reason':failed[value]});continue
                if db.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] >= store.settings()["max_watchlist"]:
                    items.append({"symbol": symbol, "status": "REJECTED", "reason": "WATCHLIST_LIMIT"}); continue
                db.execute("INSERT INTO watchlist VALUES (?,1,?,?)", (symbol, at, at))
                if symbol in verified:
                    db.execute('INSERT INTO instruments VALUES (?,?) ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload',(symbol,dump(verified[symbol])))
                items.append({"symbol": symbol, "status": "ADDED", "reason": "元数据验证前暂停信号"})
        return {"items": items}

    @api.get('/api/v1/instruments/search')
    async def search_instruments(q: str=Query(min_length=1,max_length=30)):
        try:
            return {'items':await rt().preparation.transport.call('search',search,q)}
        except SourceError as error:
            raise HTTPException(503,error.code)

    @api.get('/api/v1/watchlist/{symbol}/verification')
    def verify_watch_stock(symbol: str):
        result = stock_verification(rt(), symbol)
        if result is None:
            raise HTTPException(404, 'NOT_FOUND')
        return result

    @api.post('/api/v1/watchlist/{symbol}/prepare')
    async def prepare_stock(symbol: str):
        if not rt().store.rows('SELECT 1 FROM watchlist WHERE symbol=?',(symbol,)):
            raise HTTPException(404,'NOT_FOUND')
        await rt().preparation.prepare(symbol,force=True)
        return rt().preparation.status(symbol)

    @api.get('/api/v1/setup')
    def setup_status():
        ev = rt().evidence()
        provider_status={k:v for k,v in ev.get('provider',{}).items() if k in ('personal_use_confirmed','timestamp_semantics','history_timestamp_semantics','finalization_verified','capacity_verified','qualified_pool_size')}
        pool_size=rt().store.rows('SELECT COUNT(*) FROM watchlist WHERE enabled=1')[0][0]
        if pool_size>provider_status.get('qualified_pool_size',50):
            provider_status['capacity_verified']=False
        return {'provider':provider_status,**baseline_summary(rt()),
                'calibration':rt().store.evidence('calibration_status',{'state':'WAITING_CONSENT','message':'请先确认数据使用范围'}),
                'operations':rt().store.evidence('operations',{}),'calendar_ready':session(now(),ev.get('calendar'))!='UNKNOWN',
                'clock_ready':'CLOCK_UNVERIFIED' not in qualification_reasons(ev,now()),
                'measurements':measurement_report(rt().store,detailed=False),'source_documentation':'https://github.com/akfamily/akshare',
                'maintenance':rt().store.evidence('maintenance',{})}

    @api.post('/api/v1/setup/source')
    def source_consent(body: SourceConsent):
        provider = rt().evidence().get('provider',{})
        provider.update(name='akshare',personal_use_confirmed=body.personal_use_confirmed,
                        rights_evidence='local-user-declaration:'+now().isoformat() if body.personal_use_confirmed else '',
                        rights_scope='个人本机使用，用户确认具备所选数据源使用权限')
        rt().store.save_evidence('provider',provider)
        if not body.personal_use_confirmed:
            rt().store.save_evidence('calibration_status',{'state':'WAITING_CONSENT','message':'请先确认数据使用范围'})
        elif not provider.get('finalization_verified'):
            rt().store.save_evidence('calibration_status',{'state':'PREPARING','message':'使用范围已保存，系统正在准备盘中采样条件'})
        return setup_status()

    @api.get('/api/v1/measurements')
    def measurements(date: str | None=None):
        return measurement_report(rt().store,date)

    @api.post('/api/v1/browser/presence',status_code=204)
    def browser_presence(body: BrowserPresence):
        at=now()
        if body.browser_at.tzinfo is None or abs((at-body.browser_at).total_seconds())>5:
            raise HTTPException(400,'BROWSER_CLOCK_UNVERIFIED')
        with rt().store.transaction() as db:
            db.execute('INSERT OR IGNORE INTO browser_presence VALUES (?,?,?)',(body.client_id,at.isoformat(),int(body.visible)))
        return Response(status_code=204)

    @api.patch("/api/v1/watchlist/{symbol}")
    def enable(symbol: str, body: EnabledRequest):
        with rt().store.transaction() as db:
            if not db.execute("UPDATE watchlist SET enabled=?,updated_at=? WHERE symbol=?", (body.enabled, now().isoformat(), symbol)).rowcount:
                raise HTTPException(404, "NOT_FOUND")
        return {"symbol": symbol, "enabled": body.enabled}

    @api.delete("/api/v1/watchlist/{symbol}", status_code=204)
    def remove(symbol: str):
        with rt().store.transaction() as db:
            db.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
        return Response(status_code=204)

    def filtered_cards(state=None,date=None,sort='time'):
        cards = rt().cards()
        if state:
            cards = [c for c in cards if c["episode_state"] == state]
        if date:
            cards = [c for c in cards if c["trigger_bar_start_at"].startswith(date)]
        cards.sort(key=lambda c:(c['score'] if sort=='score' else c['trigger_bar_start_at'],c['episode_id']),reverse=True)
        return cards

    @api.get('/api/v1/episodes/export')
    def export_episodes(format: Literal['json','csv']='json',date: str | None=None,state: str | None=None):
        cards = filtered_cards(state,date)
        if format=='json':
            return Response(dump(cards),media_type='application/json',headers={'Content-Disposition':'attachment; filename="episodes.json"'})
        fields = ['episode_id','symbol','name','rule_version','trigger_bar_start_at','last_bar_end_at','received_at','updated_at','reference_close_cny','ret1_pct','ret3_pct','turnover_burst','score','priority','episode_state','primary_scenario','matched_scenarios','is_attention_eligible']
        output = io.StringIO();writer=csv.DictWriter(output,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for card in cards:
            safe = {k:('\''+v if isinstance(v,str) and v.startswith(('=','+','-','@')) and k in ('name','symbol','episode_id') else v) for k,v in card.items()}
            writer.writerow(safe)
        return Response('\ufeff'+output.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="episodes.csv"'})

    @api.delete('/api/v1/history')
    def clear_past_history(confirm: Literal['CLEAR_PAST_HISTORY']):
        cutoff=now().date().isoformat()
        directory=Path(rt().store.path).parent/'backups'
        directory.mkdir(exist_ok=True)
        backup=directory/('before-history-clear-'+now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
        rt().store.backup(backup)
        with rt().store.transaction() as db:
            ids=[r[0] for r in db.execute('SELECT episode_id FROM episodes WHERE session_date<?',(cutoff,))]
            for episode_id in ids:
                db.execute('DELETE FROM notification_receipts WHERE event_id IN (SELECT event_id FROM episode_events WHERE episode_id=?)',(episode_id,))
                for table in ('ignored_episodes','alert_outbox','episode_events','episodes'):
                    db.execute(f'DELETE FROM {table} WHERE episode_id=?',(episode_id,))
        return {'deleted_episodes':len(ids),'preserved':'今日事件、去重状态、历史成交基准','backup':str(backup)}

    @api.get("/api/v1/episodes")
    def episodes(limit: int = Query(30, ge=1, le=100), cursor: int = Query(0, ge=0), state: str | None = None, date: str | None = None, sort: Literal['time','score']='time'):
        cards = filtered_cards(state,date,sort)
        selected = cards[cursor:cursor+limit]
        return {"items": selected, "card_evidence":rt().card_evidence(c["episode_id"] for c in selected), "next_cursor": str(cursor+limit) if len(cards) > cursor+limit else None}

    @api.post('/api/v1/episodes/{episode_id}/ignore',status_code=204)
    def ignore_episode(episode_id: str):
        if not rt().store.rows('SELECT 1 FROM episodes WHERE episode_id=?',(episode_id,)):
            raise HTTPException(404,'NOT_FOUND')
        with rt().store.transaction() as db:
            db.execute('INSERT OR IGNORE INTO ignored_episodes VALUES (?,?)',(episode_id,now().isoformat()))
        return Response(status_code=204)

    @api.get("/api/v1/episodes/{episode_id}")
    def episode(episode_id: str):
        cards = [c for c in rt().cards() if c["episode_id"] == episode_id]
        if not cards:
            raise HTTPException(404, "EPISODE_NOT_FOUND")
        history = [{**json.loads(r["payload"]), "audit_sequence": r["sequence"]} for r in rt().store.rows("SELECT * FROM episode_events WHERE episode_id=? ORDER BY sequence", (episode_id,))]
        ep = json.loads(rt().store.rows("SELECT payload FROM episodes WHERE episode_id=?", (episode_id,))[0][0])
        bars = [json.loads(r[0]) for r in rt().store.rows("SELECT payload FROM minute_bars WHERE symbol=? AND bar_start_at BETWEEN ? AND ? ORDER BY bar_start_at,revision", (ep["symbol"], ep["session_date"], ep["bar"]["bar_start_at"]))]
        from decimal import Decimal
        latest = list({b['bar_start_at']:b for b in bars}.values())
        peak = max((Decimal(b['high']) for b in latest),default=Decimal(0))
        close = Decimal(ep['bar']['close'])
        prior = latest[-21:-1]
        window = latest[-21:]
        contiguous = len(window)==21 and all(timestamp(right['bar_start_at'])-timestamp(left['bar_start_at'])==timedelta(minutes=1) for left,right in zip(window,window[1:]))
        metrics = {'prior20_high_cny':str(max(Decimal(b['high']) for b in prior)) if contiguous else None,
                   'pullback_pct':str((peak-close)/peak*100) if peak else None,
                   'baseline':rt().preparation.baseline_status(ep['symbol']),
                   'ignored':bool(rt().store.rows('SELECT 1 FROM ignored_episodes WHERE episode_id=?',(episode_id,)))}
        return {"card": cards[0], "history": history, "bars": bars,'metrics':metrics,
                "decisions":[{"bar_start_at":r['bar_start_at'],"rule_version":r['rule_version'],"details":json.loads(r['payload'])}
                             for r in rt().store.rows("SELECT * FROM bar_decisions WHERE symbol=? AND bar_start_at BETWEEN ? AND ? ORDER BY bar_start_at,rule_version",(ep['symbol'],ep['trigger_bar_start_at'],ep['bar']['bar_start_at']))]}

    @api.get("/api/v1/settings")
    def settings():
        return rt().store.settings()

    @api.patch("/api/v1/settings")
    def change_settings(body: SettingsRequest):
        changes = body.model_dump(exclude_unset=True)
        if any(v is None for v in changes.values()):
            raise HTTPException(400, "INVALID_SETTINGS")
        with rt().store.transaction() as db:
            if changes.get("max_watchlist", 50) < db.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]:
                raise HTTPException(400, "WATCHLIST_EXCEEDS_NEW_LIMIT")
            for key, value in changes.items():
                db.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,revision=revision+1", (key, dump(value)))
            db.execute("INSERT INTO settings_audit(recorded_at,payload) VALUES (?,?)", (now().isoformat(), dump(changes)))
        return rt().store.settings()

    @api.get("/api/v1/diagnostics")
    def diagnostics():
        samples = [{"recorded_at":r["recorded_at"], **json.loads(r["payload"])} for r in rt().store.rows("SELECT * FROM poll_samples ORDER BY sequence DESC LIMIT 60")]
        return {"feed": rt().feed(), "symbols": rt().watchlist(), "counters": {r[0]: r[1] for r in rt().store.rows("SELECT * FROM counters")},
                "uptime_seconds": (now()-rt().started).total_seconds(), "window_start": rt().started.isoformat(),
                "poll_requests_last_60s": sum((now()-t).total_seconds()<60 for t in rt().requests),
                "last_poll_at": rt().last_poll.isoformat() if rt().last_poll else None, "database_check": rt().store.rows("PRAGMA quick_check")[0][0],
                "poll_sample_count":len(samples), "recent_polls":samples,
                "notification_receipts": [dict(r) for r in rt().store.rows("SELECT kind,COUNT(*) AS samples FROM notification_receipts GROUP BY kind")]}

    @api.post("/api/v1/notifications/receipt", status_code=204)
    def notification_receipt(body: ReceiptRequest):
        at = now()
        if body.browser_at.tzinfo is None or abs((at-body.browser_at).total_seconds()) > 5:
            raise HTTPException(400, "BROWSER_CLOCK_UNVERIFIED")
        rows = rt().store.rows("SELECT payload FROM episode_events WHERE event_id=?", (body.event_id,))
        if not rows:
            raise HTTPException(404, "EVENT_NOT_FOUND")
        event = json.loads(rows[0][0])
        if event["delivery_mode"] != "LIVE":
            raise HTTPException(400, "NOT_A_LIVE_EVENT")
        lag = (body.browser_at-timestamp(event["bar_end_at"])).total_seconds()
        if lag < 0:
            raise HTTPException(400, "BROWSER_CLOCK_UNVERIFIED")
        with rt().store.transaction() as db:
            db.execute("INSERT OR IGNORE INTO notification_receipts VALUES (?,?,?,?,?)", (body.event_id,body.kind,body.browser_at.isoformat(),at.isoformat(),str(lag)))
        return Response(status_code=204)

    @api.get("/api/v1/events/stream")
    async def events(request: Request, cursor: int | None = Query(None, ge=0)):
        header = request.headers.get("last-event-id")
        try:
            since = int(header) if header is not None else cursor
            if since is not None and since < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, "INVALID_CURSOR")
        boundary = rt().store.sequence()
        since = boundary if since is None else since
        cutoff = (now()-timedelta(hours=24)).isoformat()
        first = rt().store.rows("SELECT MIN(sequence) FROM episode_events WHERE recorded_at>=?", (cutoff,))[0][0]
        resync = since > boundary or (since < boundary and (first is None or since < first-1))

        async def generate():
            last = since
            if resync:
                yield f'event: resync_required\ndata: {{"cursor":{boundary}}}\n\n'
                last = boundary
            idle = 0
            while not await request.is_disconnected():
                rows = rt().store.rows("SELECT * FROM episode_events WHERE sequence>? ORDER BY sequence LIMIT 100", (last,))
                for row in rows:
                    yield stream_payload(row, row["sequence"] <= boundary, rt())
                    last = row["sequence"]
                if not rows:
                    idle += 1
                    if idle % 15 == 1:
                        yield f'event: feed\ndata: {dump(rt().feed())}\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    dist = ROOT / "web/dist"
    if (dist / "assets").is_dir():
        api.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @api.get("/", include_in_schema=False)
    def index():
        if not (dist / "index.html").exists():
            return JSONResponse({"message": "先运行 npm --prefix web run build"}, status_code=503)
        return FileResponse(dist / "index.html")

    from app.contracts.openapi import install_contracts
    install_contracts(api)
    return api


app = create_app()
