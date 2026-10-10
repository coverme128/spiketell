# A-Share Multi-Stock Spike Radar V1.0.1 — Minute-Only Closure

**交付类型：** V1.0.0 1+4 规范的最小叠加修正包；不是新 App，也不是替代原 1+4 主包。
**依赖主包：** `A_Share_Multi_Stock_Spike_Radar_V1_1plus4_Bundle.zip`
**主包 SHA256：** `08a3dcf41b4090b4e2aaa05f824d9737b01c5b01db4b80f8380176761b4c4a5b`
**规则版本：** 从 `spike_rules_v1.0.0` 升到 `spike_rules_v1.0.1`；旧历史事件保持原版本。
**状态：** `SPEC_DELTA_READY`；未进行真实行情或运行时验收。

## 一句话结论
仅用 AKShare + **已收盘的 1 分钟 K 线**实现；**不新增 10–15 秒轮询、Level-2、AI、自动交易或次日卖出**。补齐分钟级快速拉升、冲高回落、二次拉升的场景解释和可运行验收要求；明确历史成交额基准的冷启动与主动提醒可达性。

## 使用顺序
1. Codex 先解压并阅读原 1+4 的 `00_MASTER.md`、规则、适配器、测试及 release gates。
2. 将本包 `01_PRODUCT_DELTA.md`、`02_RULES_DELTA.md`、`03_CODEX_IMPLEMENTATION.md`、`04_TEST_AND_GATES.md` 作为增量约束；冲突时仅在列明变更处以本包为准。
3. 本包只描述必须落地的差异，非列出的原 1+4 范围、数据安全和上线门禁全部继承。
4. 同步修改原 Rulebook、`rule_profile.v1.json`、`rule_oracle.py`、fixtures/tests、Episode Alert 矩阵及 Manifest，保证源码、规则、测试、演示文案一致。
5. `python verify_addendum.py` 仅验证本补丁完整性；不等于算法已实现或真实数据源已通过。

## 不变的核心目标
自选多股 → 1m 确认 Spike → Top 1–3 重点卡 → 浏览器通知 → 同一 Episode 更新。卡片属于**异动提示**，绝非已验证的上涨概率或买入指令。
