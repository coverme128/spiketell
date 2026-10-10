# 02 Domain Rules Delta — Four-Scenario Coverage v1.0.2

本规则**叠加** v1.0.1 的基础价格触发、`RAPID_PRICE_ATTENTION` 冷启动 MEDIUM 例外、分钟内峰值回落诊断与 V1 的分数。所有数值是**工程初始阈值**，不是模型概率或实测最优参数。生产实现以 `contracts/rule_profile.v1.0.2.json` 为最终机器配置。

## 全局有效性前置门槛（未变化）

- 普通沪深 A 股、已知风险状态/交易日历、连续竞价、FINAL/VALID 1m OHLCV、明确经实测校准的分钟区间 `[start,end)`、单分钟成交额至少 `1,000,000` 元、有效最新分钟延迟 <= 90 秒、时钟偏差 <=2 秒。未知则 fail closed。
- 所有滚动窗口必须为**同一连续竞价分段内的连续 1 分钟 bar**；09:30 开盘、13:00 午后不借用昨收/午前来补缺。
- `ret1` 需要 2 根，`ret3` 需要 4 根，横盘突破需要当前 bar 之前 20 根连续有效 bar；以上先决条件缺任一，不允许对应场景触发。
- `turnover_burst=A[t]/median(A[历史 >=5 个有效的同分钟时段交易日])`。缺历史基准为 `null`；不得使用今天未来分钟、下一日数据或硬填为 1。

## S01 RAPID_RISE：快速拉升

- 正式价格触发：旧规则 `ret1 >=0.8%`，并通过基本门槛；匹配 `RAPID_RISE` 场景标签。
- `ret1>=1.8%`、`upper_wick_ratio<0.35` 且 `pullback_from_day_high<0.80%` 时，沿用 v1.0.1 `RAPID_PRICE_ATTENTION`：若基础优先级为 LOW，至少展示 MEDIUM；缺历史成交基准也不允许 HIGH。
- 不能宣称 10 秒内发现，也不能称 1m K 线揭示分钟内精确拉升顺序。

## S02 MOMENTUM_ACCELERATION：连续真正加速

- 需要连续 4 根分钟 K 线，形成最近 3 个完整的一分钟价格变化 `r[t-2]`, `r[t-1]`, `r[t]`；均为正，`r[t-2] >=0.20%`, `r[t-1] - r[t-2] >=0.10 个百分点`, `r[t] - r[t-1] >=0.10 个百分点`，并且 `ret3>=1.8%`、`r[t]>=0.30%`。
- 真正满足以上条件才标记 `MOMENTUM_ACCELERATION`；仅三分钟持续上涨但速率没有递增，则维持旧 `3m continuation` 普通价格触发，**绝不误标加速**。
- 可作为独立的**场景分类**，但不能绕过旧价格触发（事实上以上条件满足旧 ret3 条件）。
- 若分钟持续向上但第三分钟追高过度/严重回落，S04 风险否决优先。

## S03 VOLUME_BREAKOUT：横盘放量突破（新增独立触发）

- **此前 20 根完整 1m bar（不包含当前分钟）**的区间宽度 `100*(max(high) - min(low))/min(low) <=1.50%`；且期间没有其他缺失、午休跨段、非交易分钟。
- 当前分钟收盘 `close > max(previous20 high)*1.001`（高出平台最高价 **0.10%**），`ret1>=0.25%`；当前分钟成交额 `>=1,000,000` 元；`turnover_burst>=2.0` 且历史有效基准 >=5 个以前交易日；当前 bar 不应构成 S04 的明显冲高回落。
- 上述同时满足，即使 `ret1<0.8%` 且 `ret3<1.8%`，也**单独触发** `VOLUME_BREAKOUT`。只在该场景条件成立时以独立 `trigger_kind=BREAKOUT` 标注。
- 原 `breakout20` 评分加分保持不变、只加**一次**；新增触发不授予额外隐藏分。
- 不能凭量大或价格刚过前高就无条件触发；缺同分钟历史基准时该场景只能记 `BREAKOUT_UNVERIFIED` 诊断，**不得**进入正式 Top 机会卡（除非另有合法的旧价格触发）。

## S04 SPIKE_REVERSAL：冲高回落风险（负向门槛）

- 完整分钟 `high/previous_close -1 >=1.8%` 且 `(high-close)/high >=0.8%`，识别 `SPIKE_REVERSAL`。需要前一分钟 close，不能凭最高价推断在第几秒出现。
- 如基础价格 / 独立突破均未触发：仅生成 `DIAGNOSTIC_ONLY`，**不建新的 Top 卡/不发桌面通知**。
- 如价格 Spike 已触发但同分钟满足反转条件：**风险否决优先于 HIGH/快速关注**；输出记录 `raw_score`（可审计）但 `priority=LOW`, `action=IGNORE`, `is_attention_eligible=false`，不能因为原基础分高继续排 Top 或发 `HIGH_NEW/RAPID_NEW`。
- 对已存在 ACTIVE Episode，该分钟风险事件写 `episode_event=REVERSAL_OBSERVED` 并将状态变为 `WEAKENING`（优先于正向 strengthening）。同一 Episode 保留 ID，绝不额外创建第二条风险 Episode。
- 对未来分钟只以新收到的完整 bar 更新风险状态，不事后假设已知未来回落。

## 场景并存、裁决与优先级

1. `matched_scenarios` 可以同时包含多个**正向**标签：如 `RAPID_RISE` + `VOLUME_BREAKOUT`。
2. `primary_scenario` 选择：`SPIKE_REVERSAL`（优先否决） > `VOLUME_BREAKOUT` > `MOMENTUM_ACCELERATION` > `RAPID_RISE`。若旧 3m 价格触发而没有真正加速/快速 1m，则 `primary_scenario=null`、原因仍可写 `3分钟累计上涨`。
3. 场景与评分分别计算：先检查有效性与触发，再计算原 V1 score，之后应用 v1.0.1 RAPID MEDIUM 例外，最后应用 v1.0.2 REVERSAL veto。
4. HIGH **必须**有原 V1 `score>=65 && turnover_burst>=2`；正向场景标签不能强行将 MEDIUM 升到 HIGH。
5. 一个分钟允许多种 trigger kind，实际一个 `(symbol,bar_start,rule_version)` 决策记录。已有 Episode 只更新标签/状态，不能并列生成多个 alert 或卡片。
6. 诊断不代表真实成交细节，用户只看到“分钟内曾冲高且收盘回落，谨慎查看”。

## 版本和旧数据

- `rule_version=spike_rules_v1.0.2`，未来事件单独归档，`v1.0.0/1.0.1` 老事件不可静默改写。
- 增量规则必须修改：Rulebook / `rule_profile` / reference oracle / fixtures / API schema / Episode Alerts / Manifest / tests；不是单纯添加 UI 标签。
- 真实行情是否使规则有价值，需等运行后按场景统计频次、晚到率与误报，不得用静态测试代表预测能力。
