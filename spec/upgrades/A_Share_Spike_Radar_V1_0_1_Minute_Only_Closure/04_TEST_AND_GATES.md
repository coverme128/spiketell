# 04 Production Handoff Delta — Mandatory Scenarios

以下均为 P0。覆盖原 1+4 的其余 G01–G14、T001–T040，不降低原验收标准。

| ID | 场景 | 预期 |
|---|---|---|
| M101 | 已完成 1m 收盘相对上根 +1.9%，数据有效 | Spike Trigger，有机会获得 RAPID_PRICE_ATTENTION，严禁标注「秒级」 |
| M102 | 分钟内最高价相对上一收盘 +2.0%，收盘相对上一收盘仅 +0.1%，冲高回落 | 无正式上涨 Spike/无 OS 通知，可记录诊断风险 |
| M103 | 最近 3 根累计 +2.1%，末分钟 +0.4% | 3m 触发，不跨午休 |
| M104 | 首次完整分钟无上一根当日收盘 | 不触发，显示等待可比分钟 |
| M105 | 缺 5 个以前交易日成交基准，但分钟收盘 +1.9%，上影线小、回撤小、成交 >=100 万 | 保留 turnover_burst=null；MEDIUM 信息级关注；一次 RAPID_NEW；不提升 HIGH |
| M106 | 同 M105，但分钟长上影 / 冲高回落大 | 不适用 Rapid override，不冒充强关注 |
| M107 | 同一 Episode 再次达到 Rapid 条件 | 原卡更新，通知不重复 |
| M108 | MEDIUM RAPID 之后首次升级 HIGH | 满足原 HIGH 的基准才可升级，可发送一次 HIGH_UPGRADE |
| M109 | 午休/14:57 后的伪行情 Spike | 无新信号/通知 |
| M110 | Provider 迟到 120s，或补录 20 分钟前行情 | 不推送历史新异动，显示 stale/backfill |
| M111 | 5 个以前交易日数据未齐，当前分钟只有价格跳升但成交额 <100万 | 不触发正式 Spike/强提醒 |
| M112 | 1m bar timestamp 标签未知 start/end | Fail closed，不发 LIVE |
| M113 | 50 股票分钟级轮询 | 给出完整分钟覆盖率与 p95 延迟实测，未达门禁不得宣布 READY |
| M114 | 进程崩溃/重启/重复轮询 | RAPID_NEW / HIGH_NEW / HIGH_UPGRADE 通知去重有效 |

## 不允许声称
- 通过合成测试 ≠ AKShare 在真实交易日的 50 股高覆盖率；1 分钟 K 线 ≠ 秒级交易回放。
- 展示 MEDIUM/RAPID ≠ 有统计验证的继续上涨概率或买入建议。

## Codex 回传
`issue-matrix.csv`（上述 M101–M114 每项结果）、修改文件清单、测试日志、变更后完整 Rulebook/Profile/Schema、两交易日真实 Feed Gate 证据（若尚未执行请写 `PENDING_RUNTIME`）、未闭环问题与最终结论。
