"""Read-only, real-data verification for a user's actual watchlist."""
import json
from app.config import PROFILE, qualification_reasons
from app.domain.market import now, session, timestamp, metadata_reason


def baseline_summary(runtime, at=None):
    at = at or now()
    items = runtime.watchlist(at)
    eligible = [w for w in items if w['enabled'] and not metadata_reason(w['metadata'], at)]
    ready = sum(w['baseline']['slots_with_five_days'] == w['baseline']['total_continuous_slots'] for w in eligible)
    available = any(w['baseline']['historical_days'] for w in eligible)
    return {'baseline_ready_count':ready,'eligible_watch_count':len(eligible),
            'enabled_watch_count':sum(w['enabled'] for w in items),
            'baseline_status':'READY' if eligible and ready==len(eligible) else 'WARMING' if available else 'UNAVAILABLE',
            'readiness_scope':'all_237_continuous_slots_have_five_prior_sessions',
            'price_attention_requires_baseline':False}


def stock_verification(runtime, symbol):
    at = now()
    item = next((w for w in runtime.watchlist(at) if w['symbol']==symbol),None)
    if item is None:
        return None
    ev = runtime.evidence();feed = runtime.feed(at)
    bars = runtime.store.rows('SELECT payload FROM minute_bars WHERE symbol=? ORDER BY bar_start_at DESC,revision DESC LIMIT 1',(symbol,))
    bar = json.loads(bars[0][0]) if bars else None
    decisions = runtime.store.rows('SELECT bar_start_at,rule_version,payload FROM bar_decisions WHERE symbol=? ORDER BY bar_start_at DESC,rowid DESC LIMIT 1',(symbol,))
    decision = dict(decisions[0]) if decisions else None
    if decision:
        decision['details'] = json.loads(decision.pop('payload'))
    count = runtime.store.rows("SELECT COUNT(*) FROM minute_bars WHERE symbol=? AND bar_start_at>=? AND revision=1",(symbol,at.date().isoformat()))[0][0]
    issues = list(feed['reasons'])
    if not item['enabled']:issues.append('MONITOR_DISABLED')
    if item['source_state']!='VALID':issues.append(item['source_state'])
    if not item['enabled']:
        state,message='DISABLED','已停用监控，启用后才会检测新分钟。'
    elif session(at,ev.get('calendar'))!='CONTINUOUS':
        state,message='WAITING_SESSION','当前非连续竞价时段；已保存自选，开盘后自动准备并检测。'
    elif qualification_reasons(ev,at) or feed['status']=='STOPPED':
        state,message='WAITING_FEED','行情检查尚未通过，暂不发布实盘异动。查看下方暂停原因。'
    elif item['source_state']!='VALID':
        state,message='WAITING_STOCK','该股票尚无符合要求的完整分钟，其他合格股票可以继续监控。'
    elif not bar or not decision or decision['bar_start_at']!=bar['bar_start_at'] or decision['bar_start_at'][:10]!=at.date().isoformat():
        state,message='WARMING','真实完整分钟已接收；冷启动或恢复期间先补齐数据，等待下一根新分钟检测。'
    else:
        state='DETECTING'
        details=decision['details']
        message=('正在检测：最新分钟满足异动条件。' if details['triggered'] and details.get('is_attention_eligible') else
                 '正在检测：最新分钟仅记风险诊断，不发送上涨提醒。' if details.get('force_weakening') else
                 '正在检测：最新分钟未达到提醒条件，这不代表采集停止。')
        if details.get('error')=='INSUFFICIENT_CONTIGUOUS_BARS':
            message='已检测最新分钟，等待至少两根同一竞价时段的连续完整分钟，不使用昨收补齐。'
    return {'symbol':symbol,'name':item['name'],'checked_at':at.isoformat(),'data_mode':runtime.mode,
            'rule_version':PROFILE['rule_version'],'state':state,'message':message,'session':feed['session'],
            'feed_health':feed['status'],'blockers':list(dict.fromkeys(issues)),
            'preparation':item['preparation'],'baseline':item['baseline'],
            'latest_final_bar':bar,'latest_decision':decision,'today_received_minutes':count,
            'latest_bar_age_seconds':(at-timestamp(bar['bar_end_at'])).total_seconds() if bar else None,
            'source_receive_delay_seconds':(timestamp(bar['received_at'])-timestamp(bar['bar_end_at'])).total_seconds() if bar else None,
            'calibration':runtime.store.evidence('calibration_status',{}),
            'release_status':feed['release_status']}
