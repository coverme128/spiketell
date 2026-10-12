# 检测到提醒的追踪

生产 evaluate → 原始 bar_decisions → 候选投影 / 场景匹配 / 评级 → 原有 Engine Episode → alert_outbox / episode_events → SSE → 浏览器条件与去重 → OS_ATTEMPTED → OS_SHOWN 或 OS_FAILED。

候选门槛是生产规则 triggered=true、force_weakening=true 或非空 diagnostics。不新增价格规则。Qualified 场景命中可以是 LOW；MEDIUM/HIGH 关注资格独立；HIGH 提醒计数只计 HIGH_NEW/HIGH_UPGRADE。候选/场景统计单位是“股票分钟”，Episode 是轮次，通知决策/回执是事件，不混用。

- BEFORE_MONITOR_START：早于该股票当天首个正式判断分钟。
- DATA_MISSING：所需分钟不存在。
- DATA_STALE：没有原始判断且原始接收已过期；独立 stale 字段保留启动前回补的延迟。
- TRIGGER_NOT_MET：生产规则没有候选命中。
- CANDIDATE_FILTERED：价格/形态已命中，未达到关注等级。
- EPISODE_SUPPRESSED：关注资格满足但没有 Episode 事件，详情看 gap/cooldown。
- ALERT_SUPPRESSED：已有 Episode 合并无新提醒，或浏览器抑制回执。
- ALERT_DELIVERY_FAILED：有 OS_FAILED，无确认展示。
- ALERT_SENT：有 OS_SHOWN（浏览器 onshow，不代表用户已读）。
- DELIVERY_UNCONFIRMED：存在提醒决策但没有发送/送达的可靠回执，不推断成功或失败。
- NO_RECORDED_DECISION：分钟存在但没有原始判断，保留未知，不解释为无异动。

新增 processing_trace 在同一事务写入原始决策，包含处理时间、数据间断、Episode id/状态、提醒类型、合并/冷却原因。旧记录只关联现存事件和回执，标明推断来源；没有重算并篡改旧决策。

浏览器关闭时不会收到系统推送。OS_SUPPRESSED 表示可见性/授权/设置未满足；不伪称发生过发送。缺少回执也可能是浏览器离线或回执网络失败，保持未确认。localStorage 与 Web Locks 原有去重不变。

内部接口：GET /api/v1/movement-diagnostics?symbol=300124&date=2026-10-12&start=09:30&end=11:03。
命令：.venv/bin/python scripts/replay_movement.py --symbol 300124 --date 2026-10-12 --output /tmp/300124.json。
CLI 以 SQLite mode=ro 打开；接口只查询。两者直接调用生产 evaluate，不创建 Episode、outbox、回执。5m 仅计算诊断。已有记录可跨刷新查看；今日其他异动不混入独立 Episode 历史，历史候选可按日期经诊断接口查看，遵循原始数据保留期。
