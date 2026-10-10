"""Deterministic, dependency-free v1.0.2 scenario acceptance reference.

This is NOT a production market data client, trading signal, or predictor.
It expects already-normalized FINAL 1m bars and previously recorded same-slot
amount values from five distinct prior sessions (validated by integration).
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

RULE_VERSION = "spike_rules_v1.0.2"
D = lambda v: Decimal(str(v))


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 28800:
        raise ValueError("Asia/Shanghai offset required")
    return dt


def session(dt: datetime) -> str | None:
    t = dt.timetz().replace(tzinfo=None)
    if time(9, 30) <= t < time(11, 30):
        return "AM"
    if time(13, 0) <= t < time(14, 57):
        return "PM"
    return None


def eligible_bar(bar: dict) -> bool:
    try:
        st, en = parse_dt(bar["bar_start_at"]), parse_dt(bar["bar_end_at"])
        o, h, l, c = (D(bar[k]) for k in ["open", "high", "low", "close"])
        amt, vol = D(bar["amount_cny"]), int(bar["volume_shares"])
        sym = str(bar.get("symbol", ""))
        return (bar.get("is_final") is True and bar.get("quality") == "VALID"
                and st.date() == en.date() and session(st) is not None
                and (en-st).total_seconds() == 60 and st.second == 0
                and (sym.startswith("SZ.") or sym.startswith("SH.")) and len(sym) == 9
                and sym[3:].isdigit() and 0 < l <= min(o,c) <= max(o,c) <= h
                and amt >= 0 and vol >= 0)
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
        return False


def contiguous(a: dict, b: dict) -> bool:
    a0, b0 = parse_dt(a["bar_start_at"]), parse_dt(b["bar_start_at"])
    return (a0.date() == b0.date() and session(a0) is not None
            and session(a0) == session(b0) and (b0-a0).total_seconds() == 60
            and a["symbol"] == b["symbol"])


def has_contiguous_tail(bars: list[dict], length: int) -> bool:
    tail = bars[-length:]
    return (len(tail) == length and all(eligible_bar(b) for b in tail)
            and all(contiguous(tail[i], tail[i+1]) for i in range(len(tail)-1)))


def step_points(value: Decimal | None, steps: list[tuple[str,int]]) -> int:
    return next((points for threshold, points in steps if value is not None and value >= D(threshold)), 0)


def empty(error: str | None = None) -> dict[str, Any]:
    return {
        "rule_version": RULE_VERSION, "triggered": False, "trigger_kinds": [],
        "score": 0, "raw_score": 0, "priority": "LOW", "action":"IGNORE",
        "ret1_pct": None, "ret3_pct": None, "turnover_burst": None,
        "breakout20": False, "platform_width_pct": None,
        "momentum_acceleration": False, "matched_scenarios": [],
        "primary_scenario": None, "diagnostics": [], "risks": [],
        "is_attention_eligible": False, "rapid_attention": False,
        "force_weakening": False, "error": error
    }


def evaluate(bars: list[dict], prior_same_slot_amounts: list[str], now: str) -> dict:
    """Evaluate newest bar; input history must be finalized and chronological.

    Prior amount values must originate from distinct previous *dates* in the
    integration; this pure oracle validates numeric availability only.
    """
    if not bars:
        return empty("NO_BAR")
    # Do not sort automatically: a malformed input stream is a feed error.
    if any(bars[i]["bar_start_at"] >= bars[i+1]["bar_start_at"] for i in range(len(bars)-1)):
        return empty("OUT_OF_ORDER")
    bar = bars[-1]
    if not eligible_bar(bar):
        return empty("INVALID_BAR")
    try:
        now_dt, bar_end = parse_dt(now), parse_dt(bar["bar_end_at"])
        delay = (now_dt-bar_end).total_seconds()
        if delay < 0:
            return empty("FUTURE_BAR")
        if delay > 90:
            return empty("STALE_BAR")
        if D(bar["amount_cny"]) < D("1000000"):
            return empty("LOW_TURNOVER")
        if not has_contiguous_tail(bars, 2):
            return empty("INSUFFICIENT_CONTIGUOUS_BARS")
        prev = bars[-2]
        close, prev_close = D(bar["close"]), D(prev["close"])
        ret1 = (close/prev_close-1)*100
        has4 = has_contiguous_tail(bars, 4)
        ret3 = (close/D(bars[-4]["close"])-1)*100 if has4 else None
        old1 = ret1 >= D("0.8")
        old3 = ret3 is not None and ret3 >= D("1.8") and ret1 >= D("0.3")

        values = [D(a) for a in prior_same_slot_amounts]
        # Values containing <=0 are invalid history days and do not count.
        good_values = [v for v in values if v > 0 and v.is_finite()]
        burst = D(bar["amount_cny"])/D(median(good_values)) if len(good_values) >= 5 else None
        has21 = has_contiguous_tail(bars, 21)
        breakout20 = False
        width = None
        broad_breakout = False
        if has21:
            prior = bars[-21:-1]
            high20 = max(D(b["high"]) for b in prior)
            low20 = min(D(b["low"]) for b in prior)
            width = (high20-low20)/low20*100
            breakout20 = close > high20 * D("1.001")
            broad_breakout = (width <= D("1.50") and breakout20 and ret1 >= D("0.25"))
        new_breakout = broad_breakout and burst is not None and burst >= D("2")

        accel = False
        if has4 and ret3 is not None and ret3 >= D("1.8"):
            c0,c1,c2,c3 = (D(b["close"]) for b in bars[-4:])
            r0,r1,r2 = ((c1/c0-1)*100, (c2/c1-1)*100, (c3/c2-1)*100)
            accel = (r0 >= D("0.20") and r1 > 0 and r2 >= D("0.30")
                     and r1-r0 >= D("0.10") and r2-r1 >= D("0.10"))

        # Reversal is evaluated even if the closing price fails the old trigger.
        peak_from_prev = (D(bar["high"])/prev_close-1)*100
        peak_to_close = (D(bar["high"])-close)/D(bar["high"])*100
        reversal = (peak_from_prev >= D("1.8") and peak_to_close >= D("0.8"))
        triggered = old1 or old3 or new_breakout

        diagnostics = []
        if broad_breakout and not new_breakout and burst is None:
            diagnostics.append("BREAKOUT_UNVERIFIED")
        if reversal:
            diagnostics.append("INTRAMINUTE_PEAK_REVERSAL")

        result = empty()
        result.update(ret1_pct=str(ret1), ret3_pct=str(ret3) if ret3 is not None else None,
                      turnover_burst=str(burst) if burst is not None else None,
                      breakout20=breakout20, platform_width_pct=str(width) if width is not None else None,
                      momentum_acceleration=accel, diagnostics=diagnostics)
        if not triggered and not reversal:
            return dict(result, error="NO_TRIGGER")
        if not triggered:
            return dict(result, matched_scenarios=["SPIKE_REVERSAL"],
                        primary_scenario="SPIKE_REVERSAL", force_weakening=True, error="DIAGNOSTIC_ONLY")

        kinds = []
        if old1: kinds.append("PRICE_1M")
        if old3: kinds.append("PRICE_3M")
        if new_breakout: kinds.append("BREAKOUT")
        matches = []
        if old1: matches.append("RAPID_RISE")
        if accel: matches.append("MOMENTUM_ACCELERATION")
        if new_breakout: matches.append("VOLUME_BREAKOUT")
        if reversal: matches.append("SPIKE_REVERSAL")
        same_day_bars = [b for b in bars if eligible_bar(b) and parse_dt(b["bar_start_at"]).date()==bar_end.date()]
        peak_so_far = max(D(b["high"]) for b in same_day_bars)
        pullback = (peak_so_far-close)/peak_so_far*100
        bar_range = D(bar["high"])-D(bar["low"])
        wick = (D(bar["high"])-max(D(bar["open"]),close))/bar_range if bar_range>0 else D(0)
        persistence = bool(has4 and sum(D(bars[i+1]["close"])>D(bars[i]["close"]) for i in range(len(bars)-4,len(bars)-1)) >=2)
        score = step_points(ret1, [("1.8",30),("1.2",20),("0.8",10)])
        score += step_points(burst,[("5",25),("3",20),("2",10)])
        score += 20 if breakout20 else 0
        score += 15 if persistence else 0
        score -= 15 if wick >= D("0.5") else 0
        score -= 15 if pullback >= D("0.8") else 0
        score = max(0,min(90,score))
        priority = ("HIGH" if score >=65 and burst is not None and burst>=D("2")
                    else "MEDIUM" if score >= 40 else "LOW")
        rapid_attention = bool(old1 and ret1>=D("1.8") and wick<D("0.35")
                               and pullback<D("0.80"))
        if rapid_attention and priority=="LOW":
            priority="MEDIUM"
        risks=[]
        if wick >= D("0.5"): risks.append("上影线明显")
        if pullback >= D("0.8"): risks.append("冲高回落")
        if burst is None: risks.append("成交历史不足")
        if reversal:
            priority="LOW"
            risks.append("分钟内冲高回落风险否决")
        order=["SPIKE_REVERSAL","VOLUME_BREAKOUT","MOMENTUM_ACCELERATION","RAPID_RISE"]
        primary = next((k for k in order if k in matches),None)
        attention=priority in ("HIGH","MEDIUM") and not reversal
        return dict(result, triggered=True, trigger_kinds=kinds, score=score, raw_score=score,
                    priority=priority,
                    action=("VIEW_NOW" if priority=="HIGH" else "MONITOR" if attention else "IGNORE"),
                    matched_scenarios=matches, primary_scenario=primary,
                    rapid_attention=rapid_attention and not reversal,
                    is_attention_eligible=attention, force_weakening=reversal,
                    risks=risks, error=None)
    except (KeyError, ValueError, TypeError, InvalidOperation, ArithmeticError, IndexError):
        return empty("INVALID_WINDOW")


def first_attention_alert(result: dict, *, episode_is_new: bool, already_first_attention: bool) -> str | None:
    """An *advisory* pure selection function; persistence remains DB responsibility."""
    if (not episode_is_new or already_first_attention or not result["is_attention_eligible"]):
        return None
    if result["priority"] == "HIGH":
        return "HIGH_NEW"
    matched=set(result["matched_scenarios"])
    if "VOLUME_BREAKOUT" in matched and result["turnover_burst"] is not None and D(result["turnover_burst"])>=2:
        return "BREAKOUT_NEW"
    if "MOMENTUM_ACCELERATION" in matched and result["turnover_burst"] is not None and D(result["turnover_burst"])>=2:
        return "ACCEL_NEW"
    if result["rapid_attention"]:
        return "RAPID_NEW"
    return None


def episode_update_hint(previous_episode_id: str | None, signal: dict) -> dict:
    """Scenario-only guidance; production Episode machine still owns timestamps/counters."""
    if previous_episode_id:
        return {"episode_id": previous_episode_id, "new_episode": False,
                "force_state": "WEAKENING" if signal["force_weakening"] else None}
    return {"episode_id": None, "new_episode": bool(signal["triggered"] and signal["is_attention_eligible"]),
            "force_state": None}


def next_alert(result: dict, *, episode_is_new: bool, already_first_attention: bool,
               prior_priority: str | None, already_high_upgrade: bool) -> str | None:
    """UI notification eligibility only; durable outbox & SQL uniqueness are mandatory."""
    first = first_attention_alert(result, episode_is_new=episode_is_new,
                                  already_first_attention=already_first_attention)
    if first:
        return first
    if (not episode_is_new and result["is_attention_eligible"]
            and prior_priority in ("LOW", "MEDIUM") and result["priority"] == "HIGH"
            and not already_high_upgrade):
        return "HIGH_UPGRADE"
    return None
