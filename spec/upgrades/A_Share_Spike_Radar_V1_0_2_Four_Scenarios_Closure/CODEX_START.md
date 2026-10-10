# Codex — 单次实施指令

请在现有 A-Share Multi-Stock Spike Radar V1 项目中实施 **v1.0.2 Four-Scenario Closure**，不要新建应用/重构技术栈。请先核实仓库已实施的真实版本：若 V1.0.1 尚未实施，应先完整合并其规则和测试，再实施本包；不得声称本包文档等于代码已运行。

读取顺序：原 1+4 `00_MASTER.md` → v1.0.1 `00_README.md`/`02_RULES_DELTA.md` → 本包 `00_README.md`、`01_PRODUCT_DELTA.md`、`02_DOMAIN_RULES_DELTA.md`、`03_IMPLEMENTATION_DELTA.md`、`04_HANDOFF_ACCEPTANCE.md` → `contracts` → `reference`/`fixtures`/`tests`。

**实施核心**：

1. 在一个确定性的 Domain Engine 中正确识别 `RAPID_RISE`、`MOMENTUM_ACCELERATION`、`VOLUME_BREAKOUT`、`SPIKE_REVERSAL`。横盘放量突破是独立触发；区分“连续上涨”和“加速”；明确反转否决。
2. 按 `rule_profile.v1.0.2.json` 实施；不可绕过 final 1m / 数据新鲜度 / 交易日历 / 流动性及高优先级成交历史闸门。
3. 同一分钟多场景合并成**一个决策**，同一轮行情只更新一个 Episode；首次系统提醒互斥，HIGH_UPGRADE 最多一次，重启不重复。
4. 更新 Schema、OpenAPI 示例、UI 文案、持久化审计/版本、规则测试和迁移；保留全部旧历史的旧规则版本。
5. 运行所有旧 `T001–T040`、`M101–M114` 及新增 `F201–F228`，不修改旧用例期望来偷过门禁；确有定义冲突须在 Issue Matrix 附说明、迁移证据。
6. 没有真实行情证据时必须报告未通过的 Runtime Gate；模拟 Fixture 截图与静态 PASS 不能替代真实运行。

**不得实现**：10/15 秒快照、Level-2、AI 上涨概率、荐股买卖结论、自动下单、次日卖出、全市场扫描、Redis/BullMQ 新增组件。

**回传**：`implementation-report.md`、`issue-matrix.csv`、`changed-files.md`、`validation-logs/`、对应 UI 截图、`runtime-gates.md`（如未跑写 PENDING）和最终 readiness 状态。无证据不可宣称 PASS。
