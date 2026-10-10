# MASTER — Product, Contract & Delivery Freeze

## M0｜核心定位（冻结）

名称：**A-Share Multi-Stock Spike Radar V1**。

一句话：**个人用户配置多只 A 股，系统在交易时段自动检测分钟级上涨异动，筛选重要事件、实时提醒，并在同一张卡上持续更新状态。**

核心输出是 `Top Spike Cards + Real-time Alerts + Episode Tracking`。用户打开首页的第一个问题是：“现在有没有需要立即查看的股票？”允许答案是“没有”。V1 从来不承诺精选股票会涨或提供投资收益。

## M1｜产品边界与商业成熟标准

**P0 必做**：自选股 CRUD / 批量导入；交易日历与持续采集；1m 收盘 K 线校验；规则化 Spike Trigger；重要性分级；Top 1–3（可看全部）；浏览器桌面/页面内提示；Episode 去重与状态变更；数据延迟熔断；断线重连；历史事件日志；本机单用户安全部署与可观测性。

**P0 不做**：BUY SETUP/买入区间/止损价/上涨概率；5–15m 预测；T+1 卖出与持仓；股票池智能推荐；AI 自动解释；全市场行情采集；自动下单；L2；跨券商资产；多租户、支付、移动原生 App。可保留代码扩展点，不得把未实现能力做成假按钮或 Demo 数据。

**非 Demo 标准**：异常不可静默；所有信号可追溯到来源分钟 K 线与规则版本；状态一致；重复推送可抑制；浏览器关闭时不谎称仍能主动推送；文档/真实实现/截图/测试一一对应。

## M2｜核心用户故事

- 我添加 30 个股票代码，系统在下一个有效交易时段监测它们。
- 不论我是否盯盘，页面打开并已授权通知时，有新高优先级 Spike 即提醒。
- 一个 Spike 只占一条 Episode；后续增强、减弱、失效直接更新，不被重复卡片淹没。
- 我可以查看原因：1m 变化、成交额异常、近期突破和持续情况；并能明确数据对应分钟。
- 没有数据源/停盘/时钟异常时，不显示看似正常的新机会。

## M3｜冻结的数据与状态合同

- 股票统一 ID：`SH.600000` / `SZ.000001` / `SZ.300308` / `SH.688001`；展示可为六位代码；适配器负责 provider 转换。
- 标准 K 线：`symbol, bar_start_at, bar_end_at, open, high, low, close, volume_shares, amount_cny, source, received_at, is_final, quality`。所有时间 ISO-8601 +08:00；交易会话时区 `Asia/Shanghai`。
- **只用 final + 连续竞价时间内的数据生成正式告警**；所有价格展示为“最后已完成分钟 K 线收盘价”，不写“实时成交价”。
- 卡片状态拆分为 `priority(HIGH/MEDIUM/LOW)` + `episode_state(NEW/ACTIVE/STRENGTHENING/WEAKENING/EXPIRED/INVALIDATED)`；用户动作 `VIEW_NOW/MONITOR/IGNORE`。
- 事件不可变审计记录，卡片是最新状态投影。规则版本 `spike_rules_v1.0.0` 写入每条事件。

## M4｜推荐架构

```text
AKShare adapter [可切换 Tushare/QMT]
   ↓ normalized 1m final bars, market session guard, data quality
Local Python FastAPI (single instance)
   ├─ Polling & Feed Health
   ├─ Deterministic Spike Rule Engine
   ├─ Episode State + Alert Dedup
   ├─ SQLite WAL Repository
   └─ REST + SSE
          ↓
React + TypeScript + Vite: Radar / Watchlist / Activity + Notification Permission
```

默认本机运行；前端浏览器通过 SSE 收到更新。生产进程必须是**单实例调度**，不得让多 worker 各自启动相同轮询任务。QMT 可作为未来 Windows sidecar 适配器，不在本包中假定跨平台可用。

## M5｜建议默认值（不是盈利模型）

- 默认监控规模 30 只，目标验证 50，只在压测过关后提高到 100。
- 每分钟收盘后轮询；并发上限、节流、请求预算由 Provider 探测配置。
- 异动触发：单分钟涨幅 >=0.8%；或最近 3 个**连续交易分钟**累计涨幅 >=1.8% 且最后一分钟涨幅 >=0.3%；单分钟成交额 >=100 万元。阈值是工程起点，不代表胜率。
- 排序：价格冲击/成交异常/突破/延续、冲高回落惩罚；默认 HIGH >=65，MEDIUM >=40，详见 Rulebook。所有分数仅代表**告警重要性**。
- 最多展示 Top 3，HIGH 新触发与 MEDIUM→HIGH 升级才触发显著系统通知；用户可配置安静模式。

## M6｜开发顺序与交付责任

Codex：按规格实施代码、环境配置、真实 Provider 集成、测试与部署；产品负责人确认数据源权限、允许通知、股票池与上线验收。交付包只提供合同和参考规则，不冒充运行完成。

顺序：市场数据可用性 Spike → 数据合同 → 纯规则测试 → Episode/存储 → API/SSE → 3 页前端 → 断线/异常/监控 → 真实交易时段验证。

## M7｜发布状态

`SPEC_READY` 只看静态包核对；`DATA_PROVIDER_BLOCKED` 不能宣告有效监控；`PAPER_RUNTIME_PENDING` 是代码已联调但缺少交易时段证据；`PERSONAL_RUNTIME_READY` 必须通过 04 的所有 P0 门禁。未来商业对外服务另须行情数据再分发权与相关金融合规复核。
