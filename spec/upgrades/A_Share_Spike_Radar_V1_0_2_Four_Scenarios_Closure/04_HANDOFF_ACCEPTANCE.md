# 04 Production Handoff — Four-Scenario P0 Acceptance

本包新增 P0 `F201–F228`，不替代原主包的 `T001–T040` 和 v1.0.1 的 `M101–M114`，原 `G01–G14` 全部继承。

| ID | 场景 | 正确结果 |
|---|---|---|
| F201 | 1m +1.0%、amount>=100万、有效 bar | `RAPID_RISE` 正式 Trigger |
| F202 | 1m +1.9%、缺 5 历史槽、低 wick/低 pullback | `RAPID_PRICE_ATTENTION` 最低 MEDIUM，绝不 HIGH |
| F203 | 只有 20 秒内高点较高、分钟收盘未满足价格触发 | 仅按 `SPIKE_REVERSAL` 诊断，不能声称秒级复盘 |
| F204 | 连续三根 r 单调增速且总涨幅>=1.8% | `MOMENTUM_ACCELERATION` 场景成立 |
| F205 | 三分钟涨幅>=1.8%，每分钟都是正但涨速递减 | 旧 3m 价格 Trigger 保留，**不能标加速** |
| F206 | 三分钟有涨有跌、最后一根较大 | 按旧价格触发判断，不能标“连续加速” |
| F207 | 连续 K 线跨 11:30 午休 | ret3/accel 窗口无效 |
| F208 | 20 根窄幅平台 + 0.65% 突破 + 3×历史同槽量 | 即使 1m 未达 0.8%，仍触发独立 BREAKOUT |
| F209 | 不满足平台宽度（明显趋势）但有放量/突破 | 不触发独立 VOLUME_BREAKOUT，可按旧价格触发 |
| F210 | 平台窄但历史同分钟样本仅4日 | `BREAKOUT_UNVERIFIED` 诊断；无独立 BREAKOUT 或 OS 提醒 |
| F211 | 只有 19 根有效旧 K 线 | 不触发独立 BREAKOUT |
| F212 | 前 20 根有一分钟数据缺口 | 不拼接虚假区间；不触发独立 BREAKOUT |
| F213 | 当前 close 恰好等于最高价*1.001 | 因为是 `>` 严格不触发独立 BREAKOUT |
| F214 | ret1 恰好 0.25%、burst 恰好 2.0 | 符合 >= 两门槛时允许突破；其它闸门也必须满足 |
| F215 | 高点相对前收 +2%，高点→收盘回落>=0.8%，price trigger 失败 | DIAGNOSTIC_ONLY；不生成 Top/OS |
| F216 | 同 F215 但 ret1 仍>=0.8% | raw score 保留，`SPIKE_REVERSAL` 否决，LOW/IGNORE |
| F217 | 高分、高 burst 的同分钟明显回落 | 即使 raw HIGH，仍强制否决 HIGH/OS |
| F218 | 当前 Episode ACTIVE 又出现 reversal | 只更新原 episode、状态 WEAKENING、不发新上涨提醒 |
| F219 | 同一分钟既 Rapid 又 Breakout | 只有一条决策/卡，场景并列、主场景为 BREAKOUT |
| F220 | 同一 Episode 在后两分钟出现 accel / breakout | 更改卡片标签，不另建卡/不另发首次 OS 提醒 |
| F221 | 同一 Episode 多重场景均需要 OS 提醒 | 首次提醒互斥；升级 HIGH 时最多另发一次 HIGH_UPGRADE |
| F222 | 中午休市、集合竞价、非交易日、未知日历 | 不得触发正式 LIVE 信号 |
| F223 | AKShare 1m 时间标签语义不明、partial bar | Fail closed，无 LIVE |
| F224 | 120s 旧 K 线、历史补录 | 不发送新 LIVE OS 提醒 |
| F225 | 50 只股票真实时段两个完整交易日 | 原 G04 覆盖率>=95%、G05 p95<=45s 或明确 BLOCKED |
| F226 | 浏览器权限拒绝、关闭页面或后台不可达 | 不伪称送达，页内可用，按能力显示限制 |
| F227 | 同数据同版本重放、进程重启 | 规则结果确定、Episode ID/通知去重稳定 |
| F228 | 与 v1.0.0 / v1.0.1 历史数据共存 | 老事件 version 不变；不同版本结果可审计；不历史重发通知 |

## 必须提交的证据

- `issue-matrix.csv` 每个 F201–F228 含 `id,expected,actual,status,evidence_path,code_commit`，P0 不允许空白 PASS。
- 静态：本包 reference oracle 测试、主包旧测试、新行为测试、API schema validation 全 PASS。
- 运行：真实交易日 10→30→50 自选股扫描覆盖、真实 bar 标签确认、p50/p95 `bar_end→browser visible`、通知送达/拒绝、断线重启、一次异常修订证据。
- UX：新标签与风险覆盖的 1440/390/430 截图；源数据延迟、成交历史未就绪提示；Top 卡不得出现反转风险的“立即查看机会”标识。
- 没有两交易时段证据时只能 `IMPLEMENTED_PENDING_RUNTIME`，若 AKShare 阻塞则 `DATA_PROVIDER_BLOCKED`，不得 `PERSONAL_RUNTIME_READY`。

## 样本外真实性

本包测试只说明**场景检测契约**正确，不说明“高概率继续上涨”或“买入可赚钱”。要宣称交易优势，必须另有样本外 Outcome、提醒价与实际可成交价、T+1 风险和成本验证；不在本升级包范围。
