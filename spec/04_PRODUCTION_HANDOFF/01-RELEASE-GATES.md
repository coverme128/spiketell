# 04 — Production Readiness, Gates & Evidence

## H01｜状态定义

- `SPEC_READY`：本交付包静态校验通过；并不意味着真实程序已实现。
- `IMPLEMENTED_PENDING_RUNTIME`：Codex 代码和自动化测试完成，缺少连续真实交易时段证据。
- `DATA_PROVIDER_BLOCKED`：获取不到授权、可信、足时的 1m 数据或 50 只股票的吞吐不足。
- `PERSONAL_RUNTIME_READY`：所有 P0 门禁通过，指定个人设备上的已授权数据源可可靠运行；不等于适合 SaaS 商用。
- `COMMERCIAL_DISTRIBUTION_PENDING`：个人运行已过，但数据再分发/证券咨询/服务合规未验证，不可宣称商业可对外运营。

## H02｜P0 发布门禁表

| Gate | 必须具备的证据 | PASS 规则 |
|---|---|---|
| G01 Scope | 真实代码功能清单/三页截图 | 没有买入评级、AI 预测、自动交易等越界功能 |
| G02 Provider Rights | provider、账号可用性、条款与时间 | 明确个人使用范围；禁止未经验证的再分发 |
| G03 Timestamp Semantics | 2+ 样本对齐报告及场内时间 | K 线标签已确证属于 start/end，OHLCV 与同场行情合理对齐 |
| G04 Valid Coverage | 10→30→50 压测与交易时段数据 | 50 只启用股，实测有效完整分钟覆盖率 >=95%；单个缺失明确列示并禁发其信号 |
| G05 Latency | 两个完整交易时段的分钟数据分布 | 收盘至有效提醒（可见页面环境）p95 <=45s；无法达到则不得宣告符合分钟级目标 |
| G06 Staleness | 实际或注入旧报文 | 大于 90s、非 final、闭市、无日历、错时钟都绝不发新 HIGH/MEDIUM |
| G07 Determinism | 规则 Fixture/重放日志 | 同样数据+版本返回相同分数、优先级、原因和Episode |
| G08 Dedup | 重轮询、重连、重启测试 | 每根 K 线处理幂等，HIGH_NEW 每个 Episode 只通知一次 |
| G09 UX Trust | 1440/390/430 截图与交互录像 | 交易状态、时间、源健康、权限、无卡空态真实，不假装实时买价 |
| G10 Failure | 超时/限流/断网/数据修订 | 系统降级可见；恢复不把历史异动作为新通知 |
| G11 Persistence | SQLite migration + backup/restore | 进程异常退出后可恢复并保留事件审计 |
| G12 Notification | 授权/拒绝/后台浏览器三组场景 | 明确桌面通知可达范围，不虚称浏览器关闭还可提醒 |
| G13 No Leakage | 本机部署/端口检查/环境检查 | token 不进 repo/日志；默认仅 localhost 暴露 |
| G14 Evidence | Release Evidence + commit | 上述每条有文件路径、时间和截图/日志，不允许空白 PASS |

## H03｜测量口径

`bar_close_to_visible_alert = browser_visible_timestamp - bar_end_at`，以**真正最终可用**的 K 线为起点，排除历史重放但不能排除接入源本身延迟。覆盖率 = `VALID_FINAL_SYMBOL_MINUTES / EXPECTED_ELIGIBLE_SYMBOL_MINUTES`；排除停牌和公告非交易分钟须有元数据证明，不能任意缩小分母。至少两个完整正常交易时段（如两个完整交易日），不足时标记 `INSUFFICIENT_EVIDENCE`。

有效数据所占比不能用 “本轮接收到过一次报价”的粗糙口径替代。因浏览器通知权限被拒绝导致的 OS 通知不达，不计算为 provider 延迟，但必须计入用户可达性声明。

## H04｜上线禁令

不能在没有实时行情授权、没有交易时间样本、没有时钟校验、没有断线重启验证的情况下标记 Runtime Ready。不能拿 SIMULATION 截图替代 LIVE；不能把任何分数解释为胜率。不可使用未经验证的 AI 猜测去填补缺失数据。
