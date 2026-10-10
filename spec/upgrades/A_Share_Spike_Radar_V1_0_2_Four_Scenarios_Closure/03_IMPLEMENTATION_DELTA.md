# 03 Implementation Delta — Codex 落地范围

## 范围与接入点

保持原架构：**AKShare 1m final → Python/FastAPI Domain Engine → SQLite Event/Alert Outbox → SSE → React/TS Radar**。不新增进程/队列/AI/秒级行情。

| 当前模块（原包） | v1.0.2 变更 | 保持不变 |
|---|---|---|
| Market Data Adapter | 确保 current 前 20 根连续、同会话 valid bar 获取与历史同槽基准；分钟 OHLC 不用于复现秒级事件 | provider 健康、时钟、价格/成交单位、交易日历 |
| Trigger Engine | `trigger_kinds` 增加 `BREAKOUT`；保留 V1 `PRICE_1M/PRICE_3M`；对无连续前 20 根不误触发 | V1 价格触发、成交额闸门 |
| Scenario Classifier | 四标签、加速度分量、20m 平台宽度、分钟峰值回落识别 | 原 score 指标的定义和点数 |
| Priority Engine | Rapid MEDIUM 例外保留；Reversal veto 为最末、最高优先级；诊断不入 Top | HIGH 成交额基准要求、基础 score 数学 |
| Episode Engine | 已有 Episode 更新 `matched_scenarios`；REVERSAL_OBSERVED → WEAKENING；同 bar 多标签单 decision | ID 算法、cooldown、quiet window、事件审计 |
| Alert Engine | `ACCEL_NEW`、`BREAKOUT_NEW` 可选；唯一 first-attention 键确保不刷屏，HIGH_UPGRADE 限一次 | HIGH_NEW / RAPID_NEW 行为（被统一的首次提醒互斥约束覆盖） |
| Radar UI | 显示 primary + scenario badges、依据；风险诊断退出 Top；分钟结束时间/数据延迟必显 | 原三页、无买入建议、不展示未经验证概率 |
| QA | 新合成 K 线与端到端场景，重跑原 T001–T040 和 M101–M114 | 原 G01–G14 不降低 |

## 算法实施顺序（显式）

```text
final valid bar & eligible symbol/session/freshness
  -> contiguous window discovery (2,4,21 bars)
  -> metrics (ret1, ret3, slot-burst, range, wick, pullback)
  -> old PRICE_1M/PRICE_3M, new BREAKOUT
  -> if no trigger & peak reversal: diagnostic-only
  -> score (unchanged v1.0.0)
  -> priority original -> rapid v1.0.1 MEDIUM override
  -> risk veto final (LOW / IGNORE / not attention)
  -> deterministic matched_scenarios / primary_scenario
  -> upsert decision, update single Episode, append event, dedup alert outbox (transaction)
  -> SSE/UI snapshot and allowed fresh OS alert
```

## 契约兼容

原 `spike_card.schema.json` 有 `additionalProperties:false`；**不能直接在 API 中塞入新字段而不更新 schema**。

将本包 `contracts/spike_card.v1.0.2.schema.json` 的**三个可选字段**并入旧 v1 卡片 JSON Schema：

- `primary_scenario`: string | null；
- `matched_scenarios`: string[]；
- `is_attention_eligible`: boolean。

添加诊断单独 `event_type=REVERSAL_OBSERVED|BREAKOUT_UNVERIFIED` 到事件详情时同步更新事件 schema / OpenAPI 枚举（若 `event_type` 为自由字符串，则仅更新描述）。用于内部的 `trigger_kinds`、`raw_score` 优先放进 `bar_decisions.details_json`，不要破坏现有前端。

**建议 DB 最小迁移**：不必加新表。在 `bar_decisions` 的 `details_json` / 按现有表缺失时新增 JSON 列，持久化 `trigger_kinds,matched_scenarios,primary_scenario,raw_score,attention_eligible`；Episode 累积 matched scenarios 及当前风险标识由 events/latest decision 派生。已有 `episode_events` append-only 不删除。更新 `alert_outbox` 约束以支持首次提醒互斥，可在 SQLite 事务中对 `(episode_id, 'FIRST_ATTENTION')` 做**唯一占位**，单次通知类型记录在 details；已有 v1.0.1 事件按统一逻辑迁移去重，不允许重发。

## 双重版本维护

- `spike_rules_v1.0.2` 为**行为版本**，新决策用新版本，已存旧事件/通知/score 不重算覆盖；如迁移时需要 replay，只标 `SIMULATION` / `BACKFILL`，不通知。
- `rule_profile.v1.0.2.json` 是**完整合并的最终参数文件**：包含 V1 原值、V1.0.1 Rapid 和反转诊断，以及 V1.0.2 四场景参数。Codex 禁止只把补丁当旁路代码使用。
- 服务首次启动须检查数据库升级的可逆性与备份，建议 migration 顺序：snapshot → schema compatibility → new rule version → tests → live enable。

## 注意的数据质量边界

- AKShare 近期分钟数据只有有限历史窗口，`VOLUME_BREAKOUT` 需要 >=5 个**以前的、有效、同分钟时段**的历史基准。凑不齐就不能真正判断“放量”。
- 20m 高低区间与分钟 OHLC 是价格形态描述，**不是预测概率**。
- 每个阈值用 Decimal/string；切勿把 `0.10%` 理解成小数 `0.1` 倍。
- 触发后如果行情变为 STALE、PARTIAL、UNKNOWN_LABEL 不发布 LIVE 通知；补录只写审计。
- 工作中的 Provider 限流必须可观测，50 只性能达不到 G04/G05 时缩小监控规模并显式降级，而不是跳过分钟。

## 接口约束与交付

Codex 必须回传：修改文件/commit、全量规则文件、对应 API schema diff、完整测试日志、`issue-matrix.csv`（F201–F228）、50 只/两完整交易时段 Feed Gate 证据或 `PENDING_RUNTIME`、风险/异常清单。若 V1.0.1 尚未落地，需要先合并其全部约束再实施本包。
