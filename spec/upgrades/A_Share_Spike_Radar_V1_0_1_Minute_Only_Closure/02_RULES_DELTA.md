# 02 Domain Rules Delta — Minute-Only v1.0.1

## 保持不变
输入仍仅为 **FINAL/VALID 1m OHLCV**；基础 Price Trigger、成交额 >= 100 万元、HIGH 所需 `turnover_burst>=2` 且 `score>=65`、旧分数构成、时区、午休/竞价过滤、数据过期停止通知、Episode 冷却不变。缺历史基准不能伪造 1 或推算概率。

## R09 — 新增 Rapid Price Attention（信息级，非 HIGH）
- 前提：通过所有正常交易/标的/数据质量/最新完整分钟检查，至少两根连续、已完成的分钟 K 线，`ret1_pct>=1.8`、`amount_cny>=1_000_000`、`upper_wick_ratio < 0.35`、`pullback_from_day_high_pct < 0.80`。
- 原始 Price Trigger 必须已成立。无论是否已有 5 个历史基准日，如计算结果原本为 LOW，则**仅将最终展示优先级提升至 MEDIUM**，`score` 仍保持原始规则计算值，并标记 `RAPID_PRICE_ATTENTION`，决策原因写明价格信号而非成交异常。MEDIUM 并不等于高胜率。
- 如果没有 5 个历史基准日，风险增加 `成交基准积累中`；不得将其提升至 HIGH。
- 触发时可发一次 `RAPID_NEW` 浏览器通知；同一 Episode 若 HIGH_NEW 已通知则不得再弹 RAPID_NEW，反之若随后升级 HIGH，可保留原一次 HIGH_UPGRADE 行为；通知有独立去重键 `episode_id:RAPID_NEW`，不因进程重启重复。
- 本规则是 V1 的**冷启动可用性修正**：免费近期分钟数据窗口与历史 >=5 日基准不总能同时成立，正式通知不能因缺基准而完全静默。需要在观察期内统计该信息级提醒的误报，不得据此宣称已验证的买入机会。

## R10 — 分钟内曾冲高又回落，诊断而非正式 Spike
- 如完整一分钟 `high/上一完整分钟close-1 >= 1.8%` 且 `high/当前close-1 >=0.8%`，但是 Price Trigger 不成立，可追加 `INTRAMINUTE_PEAK_REVERSAL` **诊断事件**；仅记活动历史，不进入 Top1–3、无桌面通知。
- OHLC 不具备交易顺序，不能声称「20 秒内急拉又回落」或精准重现最高点到达时刻。
- 如 Price Trigger 已成立，沿用原负向 wick/pullback 评分，仍可以是 MEDIUM/LOW；不得因分钟最高价高就自动提升关注级别。

## R11 — 开盘与二次拉升
- 09:30–09:31 第一根分钟 K 线缺当日相邻 minute close，**不制造假上一分钟，也不直接用昨收替代**；首个有效同比最早从第二根完整分钟开始，实际取决于行情源的分钟标签校准。
- 第二波符合触发条件时：活跃 Episode 内只更新卡；只有旧 Episode 进入终态、交易分钟冷却和完整安静窗口同时满足，才可建立新的 Episode。
- 午休及 14:57 以后均不追加连续竞价新信号。

## R12 — 历史基准温启动
- AKShare 近期 1m 可用窗口有限，不可假设首次使用时已拥有 5 个**以前交易日**同一分钟记录；今日样本不能冒充历史基准。
- 服务启动时返回 `baseline_ready_count / eligible_watch_count` 与 `baseline_status=READY|WARMING|UNAVAILABLE`；当不足 5 个历史有效日时，`turnover_burst=null`。
- 在 5 日样本积累前允许符合 R09 的 MEDIUM 级快速拉升提示；不解除 HIGH 对成交基准的约束。若连连续分钟数据也不足，则不允许产生正式 Trigger。

## 规则版本
该修改影响用户可见优先级及通知语义，必须更新 `rule_version=spike_rules_v1.0.1`，旧信号按原规则保留，不静默篡改。
