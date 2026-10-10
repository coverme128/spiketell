# 04 — Paste-to-Codex Execution Brief

## 给 Codex 的完整执行提示词

你是此项目的负责人兼工程实施代理。以本 ZIP 的 `00_MASTER.md` 为最高规格入口，依次阅读 `01_PRODUCT/`、`02_DOMAIN_RULES/`、`03_IMPLEMENTATION/`、`04_PRODUCTION_HANDOFF/`；机读契约在 `contracts/`，合成 Fixture 与 oracle 在 `fixtures/`、`reference/`、`tests/`。

### 任务

实现一个**本机可长期使用、非演示版** `A-Share Multi-Stock Spike Radar V1`。只实现股票自选池分钟异动雷达：20–50 股票（可评估 100）、1m final bar 规则、Top1–3 异动卡、SSE/浏览器通知、Episode 持续状态、历史活动日志、运营诊断；不实现买卖预测、推荐介入价、AI/新闻、自动交易或多租户。

### 技术要求

优先 Python FastAPI + React TypeScript + SQLite WAL；优先 AKShare provider 做真实性能力验证，但如无法满足则必须输出 DATA_PROVIDER_BLOCKED 及 Tushare/QMT adapter 替换方案，不能掩盖。不要为了不用钱违背许可条款。单实例调度、时区 Asia/Shanghai、交易日历、数据最终化、迟到与陈旧闸门、事件/通知幂等是 P0。

### 实施要求

1. 先运行本包校验脚本与纯规则 oracle tests，确认使用的是完整包。
2. 按 `03-CODEX-PLAN` 完成 B01–B04；必须写实际工程代码，而不是输出另一个规划包。
3. 保持 `rule_profile.v1.json` 与领域文档版本一致，任何调整以变更记录显式说明。
4. 数据源能力门禁先验：先实测 10→30→50 只采集，并提供 bar_time/ingest_time 时延。未通过时不得将 Live UI 判定为 Healthy。
5. V1 UI 只三页 Radar / Watchlist / Activity；Simulation 只能用于测试，页面有不可隐藏的模拟标签。
6. 严格执行 `02-TEST-MATRIX` 所有 P0，并补充机器自动测试。凡真实交易时段数据尚未到手，相关门禁必须写 `PENDING`，不可写 PASS。

### 输出要求

- 真实代码提交（附 commit hash）、README、依赖锁、`.env.example`、数据库 migration、种子合成数据与 mock 配置、Provider 运行环境。
- 单命令启动、单命令测试、故障自恢复说明、桌面与窄屏真实截图。
- `Test Evidence Matrix`：T001–T040 对应证据路径；`Data Provider Qualification Report`；`Live Session Measurement`（覆盖率与时延 p50/p95、真实时段）；`Release Gate Report`。
- 明确 `SPEC_READY / IMPLEMENTED_PENDING_RUNTIME / DATA_PROVIDER_BLOCKED / PERSONAL_RUNTIME_READY` 中的真实状态。未通过时要给出明确缺陷，不得回避。

### 不许做

不得新增投资推荐、买入价格、预测胜率、AI 主力资金判断、主动下单；不得在无权限源上承诺商业数据稳定性；不得用未来 bar 计算过去 score；不得用模拟数据冒充市场行情；不得把多分钟同一异动拆成多张卡。

你可以在既定产品边界内自主完成实现，不需要就非关键样式反复征求确认；任何规则口径或数据源能力重大改变必须记录并标记 Gate 待审。
