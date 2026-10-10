"""Pure, deterministic V1 reference oracle for Codex acceptance; NOT a live-market service.

Inputs are canonical finalized bars + prior same-slot amount history + evaluation clock.
No trades, predictions, network, exchange holidays or provider inference here.
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any
import hashlib

D = lambda x: Decimal(str(x))


def _dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 8 * 3600:
        raise ValueError("timestamps must contain Asia/Shanghai +08:00 offset")
    return dt


def _session(dt: datetime) -> str | None:
    t = dt.timetz().replace(tzinfo=None)
    if time(9, 30) <= t < time(11, 30):
        return "AM"
    if time(13, 0) <= t < time(14, 57):
        return "PM"
    return None


def _consecutive(a: dict, b: dict) -> bool:
    aa, bb = _dt(a["bar_start_at"]), _dt(b["bar_start_at"])
    return bool(aa.date() == bb.date() and
                _session(aa) == _session(bb) and _session(aa) is not None and
                (bb - aa).total_seconds() == 60)


def _valid_bar(bar: dict) -> bool:
    try:
        o, h, l, c = (D(bar[k]) for k in ("open", "high", "low", "close"))
        a = D(bar["amount_cny"])
        vol = int(bar["volume_shares"])
        start, end = _dt(bar["bar_start_at"]), _dt(bar["bar_end_at"])
        if bar.get("is_final") is not True or bar.get("quality") != "VALID":
            return False
        if _session(start) is None or start.date() != end.date() or (end - start).total_seconds() != 60:
            return False
        if o <= 0 or c <= 0 or l <= 0 or not (l <= min(o, c) <= max(o, c) <= h):
            return False
        if a < 0 or vol < 0:
            return False
        if not str(bar.get("symbol", "")).startswith(("SH.", "SZ.")):
            return False
        return True
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return False


def _points(value: Decimal | None, steps: list[tuple[str, int]]) -> int:
    if value is None:
        return 0
    for threshold, pts in steps:
        if value >= D(threshold):
            return pts
    return 0


def evaluate(bars: list[dict[str, Any]], prior_same_slot_amounts: list[str], now: str) -> dict:
    """Evaluates only the newest bar; bar order MUST be ascending.

    prior_same_slot_amounts is historically earlier sessions, not same-day future bars.
    Returned score zero for non-triggering bars; after-trigger lifecycle is elsewhere.
    """
    no = {"triggered": False, "score": 0, "priority": "LOW", "action": "IGNORE",
          "ret1_pct": None, "ret3_pct": None, "turnover_burst": None,
          "breakout20": False, "persistence3": False, "reasons": [], "risks": [], "error": None}
    if not bars:
        return dict(no, error="NO_BAR")
    bars = sorted(bars, key=lambda b: b["bar_start_at"])
    current = bars[-1]
    if not _valid_bar(current):
        return dict(no, error="INVALID_BAR")
    try:
        observation_time, end = _dt(now), _dt(current["bar_end_at"])
        if (observation_time - end).total_seconds() < 0:
            return dict(no, error="FUTURE_BAR")
        if (observation_time - end).total_seconds() > 90:
            return dict(no, error="STALE_BAR")
        if D(current["amount_cny"]) < D("1000000"):
            return dict(no, error="LOW_TURNOVER")
        if len(bars) < 2 or not _valid_bar(bars[-2]) or not _consecutive(bars[-2], current):
            return dict(no, error="INSUFFICIENT_CONTIGUOUS_BARS")
        ret1 = (D(current["close"]) / D(bars[-2]["close"]) - 1) * 100
        c4 = bars[-4:]
        has3 = (len(c4) == 4 and all(_valid_bar(b) for b in c4)
                and all(_consecutive(c4[i], c4[i+1]) for i in range(3)))
        ret3 = (D(current["close"]) / D(c4[0]["close"]) - 1) * 100 if has3 else None
        triggered = ret1 >= D("0.8") or (ret3 is not None and ret3 >= D("1.8") and ret1 >= D("0.3"))
        if not triggered:
            return dict(no, error="NO_TRIGGER", ret1_pct=str(ret1), ret3_pct=str(ret3) if ret3 is not None else None)
        vals = [D(v) for v in prior_same_slot_amounts]
        vals = [v for v in vals if v > 0]
        burst = D(current["amount_cny"]) / D(median(vals)) if len(vals) >= 5 else None
        has20 = (len(bars) >= 21 and all(_valid_bar(b) for b in bars[-21:]) and
                 all(_consecutive(bars[-21+i], bars[-20+i]) for i in range(20)))
        breakout = bool(has20 and D(current["close"]) > max(D(b["high"]) for b in bars[-21:-1]) * D("1.001"))
        persistence = bool(has3 and sum(D(c4[i+1]["close"]) > D(c4[i]["close"]) for i in range(3)) >= 2)
        range_ = D(current["high"]) - D(current["low"])
        wick_ratio = (D(current["high"]) - max(D(current["open"]), D(current["close"]))) / range_ if range_ > 0 else D(0)
        same_day = [b for b in bars if _dt(b["bar_start_at"]).date() == end.date() and _valid_bar(b)]
        peak = max(D(b["high"]) for b in same_day)
        pullback = (peak - D(current["close"])) / peak * 100
        score = _points(ret1, [("1.8",30),("1.2",20),("0.8",10)])
        score += _points(burst, [("5",25),("3",20),("2",10)])
        score += 20 if breakout else 0
        score += 15 if persistence else 0
        score -= 15 if wick_ratio >= D("0.5") else 0
        score -= 15 if pullback >= D("0.8") else 0
        score = max(0, min(90, score))
        priority = ("HIGH" if score >= 65 and burst is not None and burst >= D("2")
                    else "MEDIUM" if score >= 40 else "LOW")
        reasons = ["价格快速上行"]
        if burst is not None and burst >= D("2"):
            reasons.append("成交额显著高于历史同分钟")
        if breakout:
            reasons.append("突破20分钟区间高位")
        if persistence:
            reasons.append("最近多分钟上涨延续")
        risks = []
        if wick_ratio >= D("0.5"):
            risks.append("上影线明显")
        if pullback >= D("0.8"):
            risks.append("冲高回落")
        if burst is None:
            risks.append("成交历史不足")
        return {
            "triggered": True, "score": score, "priority": priority,
            "action": "VIEW_NOW" if priority == "HIGH" else "MONITOR" if priority == "MEDIUM" else "IGNORE",
            "ret1_pct": str(ret1), "ret3_pct": str(ret3) if ret3 is not None else None,
            "turnover_burst": str(burst) if burst is not None else None,
            "breakout20": breakout, "persistence3": persistence,
            "reasons": reasons[:3], "risks": risks, "error": None
        }
    except (KeyError, InvalidOperation, ValueError, ZeroDivisionError, TypeError):
        return dict(no, error="INVALID_WINDOW")


def make_episode_id(symbol: str, session_date: str, first_bar_start_at: str, rule_version: str) -> str:
    key = f"{symbol}|{session_date}|{first_bar_start_at}|{rule_version}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def next_episode_state(previous: dict | None, signal: dict, close: str,
                       *, consecutive_weak: int = 0, nontrigger_minutes: int = 0) -> dict:
    """Event-sourcing helper. Only call once per validated new contiguous final bar.

    Persist counters and timestamps in the real implementation; this pure function
    locks the NEW / strengthening / weakening / expiry transition semantics.
    """
    if previous is None:
        if not signal["triggered"]:
            return {"state": "ABSENT", "weak": 0, "nontrigger": 0}
        return {"state": "NEW", "weak": 0, "nontrigger": 0, "score":signal["score"], "trigger_close": close}
    if previous["state"] in ("EXPIRED", "INVALIDATED"):
        return previous
    score = signal["score"] if signal["triggered"] else 0
    last = int(previous.get("score",0))
    weak_condition = (score <= last - 15 or D(close) <= D(previous["trigger_close"]) * D("0.994")
                      or not signal["triggered"])
    weak = consecutive_weak + 1 if weak_condition else 0
    no_trigger = nontrigger_minutes + (0 if signal["triggered"] else 1) if not signal["triggered"] else 0
    if weak >= 3 or no_trigger >= 8:
        state = "EXPIRED"
    elif weak_condition:
        state = "WEAKENING"
    elif score >= last + 10 and D(close) >= D(previous["trigger_close"]):
        state = "STRENGTHENING"
    else:
        state = "ACTIVE"
    return {"state":state,"weak":weak,"nontrigger":no_trigger,"score":score,"trigger_close":previous["trigger_close"]}
