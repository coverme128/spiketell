# A-Share Multi-Stock Spike Radar — v1.0.2 Four-Scenario Closure

**交付形态：单一增量升级包**，叠加 `V1.0.0 1+4 主包` + `V1.0.1 Minute-Only Closure`，不是新 App，不替换整个 1+4。

- **状态**：`SPEC_DELTA_READY`；不是 Codex 已实现、不是交易时段验收完成。
- **行情**：仅 AKShare 候选提供者的**已确认、完整的 1 分钟 OHLCV**；不新建 10/15 秒通道，不用 Level-2。
- **产品输出**：多股票异常监控、Top 1–3、主动提醒、一个 Episode 持续更新；仅提示“值得立即查看”，不提供买卖指令或上涨概率。
- **四场景**：`RAPID_RISE` 快速拉升；`MOMENTUM_ACCELERATION` 多分钟真实加速；`VOLUME_BREAKOUT` 横盘放量突破；`SPIKE_REVERSAL` 冲高回落风险。
- **规则版本**：`spike_rules_v1.0.2`。只影响新事件，不回写旧事件。

## 基线与应用顺序

1. `A_Share_Multi_Stock_Spike_Radar_V1_1plus4_Bundle.zip`（SHA-256 以 `CHANGESET.json` 为准）
2. `A_Share_Spike_Radar_V1_0_1_Minute_Only_Closure.zip`（SHA-256 以 `CHANGESET.json` 为准）
3. **本** `V1.0.2 Four-Scenario Closure`。

只在本包明确说明的部分覆盖旧版文案/规则；原来的行情单位与时间戳校准、市场日历、数据新鲜度、流动性、Episode 冷却、数据安全、T001–T040 和 G01–G14 **全部继承**。

## 文件导航

| 文件 | 给谁 | 内容 |
|---|---|---|
| `01_PRODUCT_DELTA.md` | 产品/前端 | 标签、卡片、排序、提醒体验 |
| `02_DOMAIN_RULES_DELTA.md` | 策略/QA | 4 场景的精确定义、互斥/共存、门槛和否决 |
| `03_IMPLEMENTATION_DELTA.md` | Codex | 代码切入点、兼容 API、DB、版本迁移 |
| `04_HANDOFF_ACCEPTANCE.md` | QA/运营 | P0 场景矩阵、运行验收门禁和证据 |
| `CODEX_START.md` | Codex | 单次实施指令、交付格式 |
| `contracts/*` | 工程 | 可机读完整 v1.0.2 规则配置、可选字段 schema 与示例 |
| `reference/*` | 工程/QA | 纯函数参考逻辑；**验收 oracle 而非行情服务** |
| `fixtures/*`, `tests/*` | QA | 真实结构的合成分钟 K 线场景与可执行测试 |
| `CHANGESET.json`, `MIGRATION_MATRIX.csv` | 交付经理 | 基线指纹、版本差异与变更影响 |

## 运行静态校验

解压后在本包目录执行：

```bash
python -m unittest discover -s tests -v
python tools/validate_upgrade.py
```

通过只证明本增量包的规则与机器测试自洽；不证明 AKShare 的 50 只吞吐、分钟数据连续性、真实告警送达或策略有效性。
