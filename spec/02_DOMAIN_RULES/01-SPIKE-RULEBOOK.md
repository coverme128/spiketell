# 02 — Spike Rulebook v1.0.0 (Frozen)

**重要声明**：以下阈值是用于第一版发现/排序的可解释工程起点，并非经验胜率或投资建议。不同板块的波动尺度不同，V1 先共享阈值并标记板块，后续仅凭真实观测决定是否分板块校准，禁止未来函数。

## R01｜输入和闸门

输入仅为**完整且已最终确认的 1 分钟 OHLCV**，来自受支持的沪深 A 股连续竞价时段。必须满足交易日、可监控、价格 >0、`low<=min(open,close)<=max(open,close)<=high`、`amount_cny>=0`、`volume_shares>=0`、不缺相邻对比 bar、与当前时间延迟可接受。1m 的 close 不等于当前买价。

首次开盘时可用 1m 比较不足，不制造虚拟缺失 K 线。Provider 每分钟需要具有明确 `bar_start_at/bar_end_at` 语义；适配器未验证 provider 的时间标签，不得对外发 `LIVE`。

最小流动性：触发 K 线成交额 `>=1_000_000 CNY`。仅支持 `SH` 与 `SZ` 可识别的普通 A 股；非普通 A、板块未知/新上市无合法限制信息、ST 风险无法确认、暂停交易的标的可留 watchlist，但 V1 不自动出重点提醒。市场/公司元数据必须有来源和更新时间。

## R02｜基础计算（对数无关，简单收益）

设 `C[t]` 是本交易时段最后完整分钟的收盘价，`A[t]` 是对应成交额，`H[t]` 是最高价。

- `ret1_pct = 100*(C[t]/C[t-1]-1)`，需要两个连续交易分钟 bar。
- `ret3_pct = 100*(C[t]/C[t-3]-1)`，需要当前及之前 3 根连续的分钟 bar；窗口不能跨午休或缺失分钟。
- `breakout20 = C[t] > max(H[t-20...t-1]) * 1.001`；需要前 20 根连续的完整分钟数据，不能把当前 bar 包进去。
- `persistence3`: 最近 3 个相邻的收盘价变化中至少 2 次为正，需最近 4 根 bar。
- `turnover_burst = A[t] / median(A_same_minute_slot[previous_sessions])`；历史 >=5 个有效、无停牌的交易日且 median>0 才有效。历史回测需按当时可获得的数据，不得用未来数据。缺历史则标记 `BASELINE_INSUFFICIENT` 而非填 1 或推测。
- `upper_wick_ratio = (H[t] - max(O[t], C[t])) / (H[t]-L[t])`，振幅为零时 0。
- `pullback_from_day_high_pct = 100*(intraday_high_so_far - C[t])/intraday_high_so_far`，此高点只由当前及之前连续竞价分钟得出（不含未来）。

## R03｜Spike Trigger

全部满足基础数据闸门、`A[t]>=1m CNY`，再满足以下任一条件：

- `ret1_pct >= 0.8`；或
- `ret3_pct >= 1.8 AND ret1_pct >= 0.3`。

事件是上涨 Spike；下跌异动不纳入 V1。比较阈值时使用实数精度 Decimal，不提前四舍五入。触发后不会自动等于 HIGH。

## R04｜优先级分数，仅用于观察排序

| 因子 | 条件 | 分数 |
|---|---|---:|
| 1m 价格强度 | >=1.8% / >=1.2% / >=0.8% | +30 / +20 / +10 （择一） |
| 成交异常倍数 | >=5.0 / >=3.0 / >=2.0 | +25 / +20 / +10 （择一） |
| 20m 区间突破 | `breakout20=true` | +20 |
| 最近 3 次收盘变化的延续 | `persistence3=true` | +15 |
| 上影线警惕 | `upper_wick_ratio>=0.50` | -15 |
| 冲高回撤警惕 | `pullback_from_day_high_pct>=0.80` | -15 |

分数 `score=max(0,min(90,sum))`，只对 Trigger 成立的 bar 计算。对于成交历史基准不足，成交得分=0；不允许因为其它因子达到阈值而将其评为 HIGH。

- HIGH：`score>=65 AND turnover_burst>=2.0 AND data_quality=VALID`。
- MEDIUM：`score>=40 AND data_quality=VALID`。
- LOW：其余触发候选仅记入活动日志，不出 Top1–3 主榜。

不做“上涨概率 85%”“成功率 90%”字样。HIGH 仅代表规则定义下的告警优先级。

## R05｜原因标签与排序

原因取 `价格快速上行`、`成交额显著高于历史同分钟`、`突破20分钟区间高位`、`最近多分钟上涨延续`；按优先级最多 3 条。风险标签 `冲高回落`、`上影线明显`、`成交历史不足`。排序先 HIGH>MEDIUM，再按 score 降序，最后按首次触发时间降序，依旧相同时股票 ID 字典序，保证重放确定。

## R06｜Freshness 与 fail closed

- 对当下应有新 K 线的股票，以最近 final bar `bar_end_at` 与当前 `Asia/Shanghai` 时间差判断；默认超过 90 秒为 `STALE`，不能出新的 HIGH/MEDIUM 提醒。
- Data Feed 本轮报错/回放缺口/时钟偏移 >2s/交易日历异常：暂停新信号并明确显示原因；已经发生的 Episode 留在历史但不可标 LIVE。
- 如果 provider 为 `PARTIAL`、`REVISED_PENDING`、`UNKNOWN_TIMESTAMP_SEMANTICS`：不得触发正式信号。
- 离线补齐的旧 K 线只补证据与时间线，**不触发新桌面提醒**。发生修订时写更正审计事件，必要时将 Episode 标记 INVALIDATED；不悄悄改写原信号。

## R07｜无法保证的事情

分钟级数据很可能晚于分钟收盘才可用；告警不是毫秒级；一分钟数据不包含逐笔买卖方向/盘口队列/可成交保证；没有理由推导次日收益；股票异动不等于买点。

## R08｜冻结与版本变更

阈值统一由 `contracts/rule_profile.v1.json` 提供。线上变更必须生成新 rule_version、新对照统计和留痕；旧事件不追溯按新版本悄悄重算。参考算法 `reference/rule_oracle.py` 需与此文本以及 Fixture 测试一致。
