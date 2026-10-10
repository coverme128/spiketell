# 03 Implementation Delta — Codex Task

## 最小改动清单
1. 完整沿用原 1+4 的 Python + FastAPI + React/TS + SQLite + SSE；不新增数据源或服务。
2. 在 `reference/rule_oracle.py` / 真实 Domain Engine 中实现 R09（price rapid attention override）与 R10（风险诊断），确保回放确定、版本隔离；在 `rule_profile.v1.json` 添加阈值配置：`rapid_attention.ret1_pct_gte=1.8`, `upper_wick_ratio_lt=0.35`, `pullback_from_day_high_pct_lt=0.80`, `min_amount_cny=1000000`。
3. 规范 HIGH 原规则不可改变；R09 只是 MEDIUM 展示/通知例外：即便 `score<40` 也可能有 `priority=MEDIUM`，必须显示 `RAPID_PRICE_ATTENTION` 理由。更新原 Rulebook 和文案，避免「分数达40才能 MEDIUM」的旧描述失真。
4. Alert Engine 新增 `RAPID_NEW`（只针对 R09、且未就同一新事件发过 HIGH_NEW）；新增持久化去重，不重复推送。原 `MEDIUM_NEW` 仍然默认无系统通知。
5. Radar Card 不强制新增破坏性 schema 字段；优先使用已有 `reasons/risks/as_of_label` 来解释特殊关注与冷启动。Provider 状态页补充 baseline 状态与冷启动范围统计，可通过新增兼容字段或独立状态 API 提供。
6. 开盘、午休、尾盘、快拉又回落、二次拉升、同卡幂等、行情补录迟到，新增 P0 fixture 与测试，参考 `fixtures/minute_only_scenarios.json`。
7. 跑原始完整验收，加测新增用例；更新 Profile、Golden Fixture、测试期望、API 示例、Manifest SHA256 与版本说明。任何旧用例受 R09 影响必须明确解释，不得单方面删除来获得 PASS。

## 实际行情闸门（不可跳过）
- AKShare 10→30→50 只自选股真实交易时段连续运行实测。
- 按原主包 G04/G05：50 只目标覆盖率 >=95%；可见提醒 p95 从完整分钟终点算 <=45s（均为项目目标，未经实测）。未达到则 `DATA_PROVIDER_BLOCKED`，可缩小可用监控规模并如实显示，但不得宣称 50 只生产通过。
- 近 5 日历史窗口与 5 个以前交易日需求不应混淆：展示实际历史样本数并证明冷启动 R09 可达；不能用随机数填充成交异常倍数。
- 时间戳语义未知、旧行情、partial、补录回放、午夜、午休、集合竞价都绝不能触发新的 LIVE 通知。

## 完成标准
代码、迁移、测试、可用页面、日志、真实交易时段覆盖和延迟证据。模拟测试 PASS 仅说明规则闭环，不等于已可以长期监控。
