# 03 — Codex Implementation Plan / Definition of Done

## 交付方式

采用四个逐步可测的 Batch，每个 Batch 必须有真实代码、测试报告和截图/日志证据。可以由 Codex 在一个连续任务中完成，但不得跳过 P0 门禁或拿模拟 UI 当 Live。

### B01 — Data Contract & Provider Spike

- 建立 Python + TypeScript monorepo；环境配置、dev/build/test 脚本、数据库迁移。
- 完成 canonical stock ID、trade calendar/continuous auction guard、MinuteBar validator、AKShare Adapter & stub provider interface；真实接口时间标签/手转股/金额单位现场核验。
- 实现可见的 `HEALTHY/DEGRADED/STOPPED`、错误日志与独立不带市场行情的 Fixture 回放入口。
- 以目标股票池测 10、30、50 股票轮询吞吐。记录实测报告；失败则明确 `DATA_PROVIDER_BLOCKED`，不能继续假装“监控中”。

**验收**：无数据伪装 final；交易日/午休/停牌/行情迟到 gating；接口断开后无新 Spike；账面源权限确认。

### B02 — Deterministic Engine + Episode

- 严格实现 Rulebook 的 ret1/ret3/median baseline/breakout/persistence/upper wick/pullback/score/rank；不使用 LLM。
- SQLite migrations、唯一约束、事务事件日志、重复处理幂等、重启恢复、Episode 冷却。
- 执行 `tests/` 提供的 oracle tests，并补充真实 adapter 示例；回放数据至少 30 组 P0 边界用例（本包 Matrix 作为最小集合）。

**验收**：同一 Fixture 重放输出逐字段一致；重复轮询不生成第二张卡；任何 stale 数据不出新信号。

### B03 — User-Facing Product

- 实现 Radar、Watchlist、Activity 三页；动态 Live/Degraded/Stopped；Top1-3；活动详情、稳定 key、滚动与状态。
- REST + SSE + Last-Event-ID，浏览器权限 UI、通知文案、前台 Toast、权限拒绝降级；窄屏 390/430 无溢出。
- 页面无假数据；Simulation 运行必须明确可视水印 `SIMULATION / 非实盘`。

**验收**：30 只列表可增删/导入/持久化；收到 Episode 新建/更新/结束；重复通知抑制与浏览器通知拒绝场景通过。

### B04 — Hardening & Production Handoff

- 连接波动/限流/网络超时/交易休市/午休/开盘/收盘/数据校正场景。
- 健康、操作日志、故障诊断、备份恢复、NTP 漂移、进程单实例锁和本机开机服务。
- 真实交易日验证 2 个完整交易时段，记录覆盖率与时延分布；性能不足则宣布数据源 Gate 不通过（可切换 Provider 再验）。
- 输出 Release Evidence ZIP：测试报告、数据源评估、实际部署说明、UI 截图、已知限制、规则版本与 git commit。

**验收**：04 Release Gates 所有 P0 = PASS，不允许将缺少真实交易时段证据标为上线。

## 交付物总表

`src + lockfiles + .env.example + migrations + tests + openapi + README + screenshots + replay & live metrics + deployment/runbook + release-gate report`。

任何“图已经做完”但 Data Gate 未通过的状态必须归类为 `UI_READY_DATA_BLOCKED`。个人版无登录时只允许 localhost；如果改为网络可访问，先补身份认证/HTTPS/CSRF 等控制。UI 实现不得新增投资建议功能。
