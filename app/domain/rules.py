"""Versioned, Decimal-only production rules using the complete merged profile.

The supplied oracle is kept independently under spec/upgrades for comparison.
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

from app.config import PROFILE as P
from app.domain.rules_v100 import _valid_bar, make_episode_id

RULE_VERSION = P["rule_version"]
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
        return _valid_bar(bar) and parse_dt(bar["bar_start_at"]).second == 0
    except (KeyError, ValueError, TypeError):
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
        "force_weakening": False, "persistence3": False, "reasons": [], "error": error
    }


def evaluate(bars: list[dict], prior_same_slot_amounts: list[str], now: str) -> dict:
    """Evaluate newest bar; input history must be finalized and chronological.

    Prior amount values must originate from distinct previous *dates* in the
    integration; the deterministic evaluator validates numeric availability only.
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
        if delay > P["max_bar_age_seconds"]:
            return empty("STALE_BAR")
        if D(bar["amount_cny"]) < D(P["min_turnover_cny"]):
            return empty("LOW_TURNOVER")
        if not has_contiguous_tail(bars, 2):
            return empty("INSUFFICIENT_CONTIGUOUS_BARS")
        prev = bars[-2]
        close, prev_close = D(bar["close"]), D(prev["close"])
        ret1 = (close/prev_close-1)*100
        has4 = has_contiguous_tail(bars, 4)
        ret3 = (close/D(bars[-4]["close"])-1)*100 if has4 else None
        old1 = ret1 >= D(P["trigger"]["ret1_pct_gte"])
        old3 = ret3 is not None and ret3 >= D(P["trigger"]["ret3_pct_gte"]) and ret1 >= D(P["trigger"]["ret3_and_ret1_pct_gte"])

        values = [D(a) for a in prior_same_slot_amounts]
        # Values containing <=0 are invalid history days and do not count.
        good_values = [v for v in values if v.is_finite() and v > 0]
        burst = D(bar["amount_cny"])/D(median(good_values)) if len(good_values) >= P["volume_baseline"]["min_previous_sessions"] else None
        breakout_p = P["scenarios"]["VOLUME_BREAKOUT"]
        count = breakout_p["prior_contiguous_bars"]
        has21 = has_contiguous_tail(bars, count + 1)
        breakout20 = False
        width = None
        broad_breakout = False
        if has21:
            prior = bars[-count-1:-1]
            high20 = max(D(b["high"]) for b in prior)
            low20 = min(D(b["low"]) for b in prior)
            width = (high20-low20)/low20*100
            breakout20 = close > high20 * D(breakout_p["close_above_prior_high_ratio_gt"])
            broad_breakout = (width <= D(breakout_p["prior_range_width_pct_lte"]) and breakout20 and ret1 >= D(breakout_p["ret1_pct_gte"]))
        new_breakout = broad_breakout and len(good_values) >= breakout_p["requires_baseline_sessions"] and burst is not None and burst >= D(breakout_p["turnover_burst_gte"])

        accel = False
        accel_p = P["scenarios"]["MOMENTUM_ACCELERATION"]
        if has4 and ret3 is not None and ret3 >= D(accel_p["ret3_pct_gte"]):
            c0,c1,c2,c3 = (D(b["close"]) for b in bars[-4:])
            r0,r1,r2 = ((c1/c0-1)*100, (c2/c1-1)*100, (c3/c2-1)*100)
            accel = (r0 >= D(accel_p["oldest_return_pct_gte"]) and r1 > 0 and r2 >= D(accel_p["last_return_pct_gte"])
                     and r1-r0 >= D(accel_p["min_increment_percentage_points"]) and r2-r1 >= D(accel_p["min_increment_percentage_points"]))

        # Reversal is evaluated even if the closing price fails the old trigger.
        peak_from_prev = (D(bar["high"])/prev_close-1)*100
        peak_to_close = (D(bar["high"])-close)/D(bar["high"])*100
        reversal = (peak_from_prev >= D(P["peak_reversal"]["peak_from_previous_close_pct_gte"]) and peak_to_close >= D(P["peak_reversal"]["peak_to_close_pct_gte"]))
        triggered = old1 or old3 or new_breakout

        diagnostics = []
        if broad_breakout and not new_breakout and burst is None:
            diagnostics.append("BREAKOUT_UNVERIFIED")
        if reversal:
            diagnostics.append("INTRAMINUTE_PEAK_REVERSAL")

        result = empty()
        result['condition_checks'] = {
            'PRICE_1M': {'met':old1,'ret1_pct':str(ret1),'required_gte':P['trigger']['ret1_pct_gte']},
            'PRICE_3M': {'met':old3,'ret3_pct':str(ret3) if ret3 is not None else None,
                         'required_gte':P['trigger']['ret3_pct_gte'],'last_return_required_gte':P['trigger']['ret3_and_ret1_pct_gte']},
            'MOMENTUM_ACCELERATION': {'met':accel,'contiguous_four_bars':has4,'returns_pct': [str((D(bars[i+1]['close'])/D(bars[i]['close'])-1)*100) for i in range(len(bars)-4,len(bars)-1)] if has4 else None,'requirements':accel_p},
            'VOLUME_BREAKOUT': {'met':new_breakout,'contiguous_21_bars':has21,'price_shape_met':broad_breakout,
                                'width_pct':str(width) if width is not None else None,'above_prior_high':breakout20,
                                'baseline_sessions':len(good_values),'burst':str(burst) if burst is not None else None,'requirements':breakout_p},
            'SPIKE_REVERSAL': {'met':reversal,'peak_from_previous_close_pct':str(peak_from_prev),
                               'peak_to_close_pct':str(peak_to_close),'requirements':P['peak_reversal']}}
        result.update(ret1_pct=str(ret1), ret3_pct=str(ret3) if ret3 is not None else None,
                      turnover_burst=str(burst) if burst is not None else None,
                      breakout20=breakout20, platform_width_pct=str(width) if width is not None else None,
                      momentum_acceleration=accel, diagnostics=diagnostics)
        if not triggered and not reversal:
            return dict(result, error="NO_TRIGGER")
        if not triggered:
            return dict(result, matched_scenarios=["SPIKE_REVERSAL"],
                        primary_scenario="SPIKE_REVERSAL", force_weakening=True, risks=["分钟内曾冲高且收盘回落，谨慎查看"], error="DIAGNOSTIC_ONLY")

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
        persistence = bool(has4 and sum(D(bars[i+1]["close"])>D(bars[i]["close"]) for i in range(len(bars)-4,len(bars)-1)) >=P["persistence"]["up_closes_at_least"])
        score = step_points(ret1, [(v["gte"], v["points"]) for v in P["score"]["ret1_steps"]])
        score += step_points(burst,[(v["gte"], v["points"]) for v in P["score"]["turnover_burst_steps"]])
        score += P["score"]["breakout_points"] if breakout20 else 0
        score += P["score"]["persistence_points"] if persistence else 0
        score -= P["score"]["upper_wick_penalty"] if wick >= D(P["score"]["upper_wick_ratio_gte"]) else 0
        score -= P["score"]["pullback_penalty"] if pullback >= D(P["score"]["pullback_from_intraday_high_pct_gte"]) else 0
        score = max(P["score"]["min"],min(P["score"]["max"],score))
        priority = ("HIGH" if score >=P["priority"]["high_score_gte"] and burst is not None and burst>=D(P["priority"]["high_turnover_burst_gte"])
                    else "MEDIUM" if score >= P["priority"]["medium_score_gte"] else "LOW")
        rapid_attention = bool(old1 and ret1>=D(P["rapid_attention"]["min_ret1_pct"]) and wick<D(P["rapid_attention"]["upper_wick_ratio_lt"])
                               and pullback<D(P["rapid_attention"]["pullback_from_day_high_pct_lt"]))
        if rapid_attention and priority=="LOW":
            priority="MEDIUM"
        result['rating_checks']={'upper_wick_ratio':str(wick),'pullback_from_day_high_pct':str(pullback),'persistence':persistence,'score_profile':P['score'],'priority_requirements':P['priority'],'rapid_attention_met':rapid_attention}
        risks=[]
        if wick >= D("0.5"): risks.append("上影线明显")
        if pullback >= D("0.8"): risks.append("冲高回落")
        if burst is None: risks.append("成交基准积累中")
        if reversal:
            priority="LOW"
            risks.append("分钟内冲高回落风险否决")
        order=P["scenario_primary_order"]
        primary = next((k for k in order if k in matches),None)
        attention=priority in ("HIGH","MEDIUM") and not reversal
        return dict(result, triggered=True, trigger_kinds=kinds, score=score, raw_score=score,
                    priority=priority,
                    action=("VIEW_NOW" if priority=="HIGH" else "MONITOR" if attention else "IGNORE"),
                    matched_scenarios=matches, primary_scenario=primary,
                    rapid_attention=rapid_attention and not reversal,
                    is_attention_eligible=attention, force_weakening=reversal,
                    risks=risks, persistence3=persistence, reasons=signal_reasons(kinds, accel, burst, rapid_attention and not reversal), error=None)
    except (KeyError, ValueError, TypeError, InvalidOperation, ArithmeticError, IndexError):
        return empty("INVALID_WINDOW")



def signal_reasons(kinds, accel, burst, rapid_attention=False):
    reasons = ["RAPID_PRICE_ATTENTION：快速价格关注"] if rapid_attention else []
    if "BREAKOUT" in kinds:
        reasons.append("此前20根窄幅横盘后放量突破")
    if accel:
        reasons.append("连续三分钟涨幅逐分钟加速")
    if "PRICE_1M" in kinds:
        reasons.append("1分钟价格快速上行")
    elif "PRICE_3M" in kinds and not accel:
        reasons.append("3分钟累计上涨")
    if burst is not None and burst >= D(P["priority"]["high_turnover_burst_gte"]):
        reasons.append("成交额显著高于历史同分钟")
    return reasons[:3]


def first_attention_alert(signal):
    if not signal["is_attention_eligible"]:
        return None
    choices = {
        "HIGH_NEW": signal["priority"] == "HIGH",
        "BREAKOUT_NEW": "VOLUME_BREAKOUT" in signal["matched_scenarios"],
        "ACCEL_NEW": "MOMENTUM_ACCELERATION" in signal["matched_scenarios"],
        "RAPID_NEW": signal["rapid_attention"],
    }
    for kind in P["alert_dedup"]["first_attention_selection_order"]:
        if not choices[kind]:
            continue
        if kind in ("BREAKOUT_NEW", "ACCEL_NEW") and (signal["turnover_burst"] is None or D(signal["turnover_burst"]) < D(P["priority"]["high_turnover_burst_gte"])):
            continue
        return kind
    return None


def next_episode_state(previous, signal, close, **counters):
    result = base_episode_state(previous, signal, close, **counters)
    if previous and previous["state"] not in ("EXPIRED", "INVALIDATED") and signal.get("force_weakening"):
        result["state"] = "WEAKENING"
    return result


def base_episode_state(previous: dict | None, signal: dict, close: str,
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
    weak_condition = (score <= last + P["episode"]["weakening_delta_lte"] or D(close) <= D(previous["trigger_close"]) * D(P["episode"]["weakening_below_trigger_close_ratio"])
                      or not signal["triggered"])
    weak = consecutive_weak + 1 if weak_condition else 0
    no_trigger = nontrigger_minutes + (0 if signal["triggered"] else 1) if not signal["triggered"] else 0
    if weak >= P["episode"]["expire_after_weak_consecutive"] or no_trigger >= P["episode"]["expire_after_nontrigger_minutes"]:
        state = "EXPIRED"
    elif weak_condition:
        state = "WEAKENING"
    elif score >= last + P["episode"]["strengthening_delta_gte"] and D(close) >= D(previous["trigger_close"]):
        state = "STRENGTHENING"
    else:
        state = "ACTIVE"
    return {"state":state,"weak":weak,"nontrigger":no_trigger,"score":score,"trigger_close":previous["trigger_close"]}
