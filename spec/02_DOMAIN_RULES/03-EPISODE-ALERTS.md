# 03 — Episode Lifecycle, Alerts & Idempotency

## E01｜事件定义

一轮上涨异动称 `SpikeEpisode`。稳定 ID 使用 `SHA256(symbol|session_date|first_trigger_bar_start|rule_version)` 的前 24 位十六进制（生产可用全长，必须稳定）；同一轮每分钟更新同一条记录，前端 key 固定 episode_id。

不可变记录 `episode_events`: event_id、episode_id、symbol、bar_start/end、event_type、previous_state、next_state、score、priority、rule_version、source、source_received_at、audit_sequence。每条分钟决策只插入一次；唯一键 `(symbol,bar_start_at,rule_version,decision_kind)`。

## E02｜状态机

```text
ABSENT -- valid Spike trigger --> NEW
NEW --> ACTIVE / STRENGTHENING / WEAKENING
ACTIVE <--> STRENGTHENING <--> WEAKENING
any active --> EXPIRED [连续3根 weakening 或连续8个交易分钟未再触发]
any active --> INVALIDATED [触发 bar 被证实无效/修订失去触发资格]
EXPIRED / INVALIDATED 为终态，不能重新打开
```

`score - prior_score >=10 && close>=trigger_close` → STRENGTHENING；否则 `score <= prior_score-15` 或 `close<=trigger_close*0.994` → WEAKENING；其它 → ACTIVE。优先级只按当前 bar 实际可计算结果更新，非 Spike bar 的得分也可作为延续性评价，但不能把它视作新 Trigger；如无新触发且持续增强不成立，状态按 ACTIVE→WEAKENING 退化。连续三根弱化或 8 根无新触发终止，两个计数都是**交易分钟**，停牌/午休不算时间进度。

额外：`NEW` 最多保持首根 bar；恢复/重启后基于持久化事件恢复，不得造成 NEW 重发。

## E03｜再触发策略

同一股票仅允许一个 ACTIVE episode。终止后须至少 15 个有效交易分钟冷却，且至少最近 10 个有效交易分钟无有效 Spike Trigger，才允许新建另一 episode。交易日切换时终止未结束 episode，第二天独立计数。数据断档时无法证明 quiet window，禁止直接重建高优先级 episode。

## E04｜通知矩阵

| 条件 | 页面内 | 系统通知 | 唯一 dedup 键 |
|---|---|---|---|
| HIGH + NEW | 是 | 权限允许时是 | `episode_id:HIGH_NEW` |
| MEDIUM + NEW | 是 | 默认否 | `episode_id:MEDIUM_NEW` |
| MEDIUM→HIGH 首次升级 | 是 | 可发一次 | `episode_id:HIGH_UPGRADE` |
| ACTIVE/STRENGTHENING 常规更新 | 卡片更新 | 否 | 不适用 |
| WEAKENING/EXPIRED | 卡片/活动记录 | 否 | 不适用 |
| STALE/UNAVAILABLE | 顶部危险横幅 | 停止异动通知 | 不适用 |

系统通知由浏览器触发：仅在页面/ServiceWorker 有实际有效配置时可达；V1 没有后端 Web Push、手机 App 或后台系统托管能力。`notification_permission=denied` 时不要自动重复请求授权。

## E05｜断线与重放

SSE: 每条具有单调递增整数 `id`、`event`、`data`；客户端用 `Last-Event-ID`/cursor 补最近事件（默认 24h）；服务端校验回放期间的权限和数据可用性。过去的事件回放只恢复 UI，不触发系统桌面通知。特别是重启后不能把同一 HIGH_NEW 推送第二遍。SSE 不存在时前端采用 15 秒轮询降级，并明确标注“降级连接”。

## E06｜指标

日累计唯一 Episode 数、HIGH 数、被抑制重复数、数据新鲜度分布、Provider 成功率、有效股票分钟覆盖率、告警送达/点击率（本机可用时）；不收集用户隐私遥测。任何时候 `gain_probability` 字段都不存在于 V1 主契约。
