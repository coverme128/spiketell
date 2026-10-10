# 02 — Market Data, Session & Provider Adapter Contract

## D01｜行情源策略：可观测，不假设免费可用

**初始 Provider**：AKShare `stock_zh_a_hist_min_em(symbol, period='1', adjust='')` 只作为本机实现候选；文档表明 1 分钟约覆盖近期 5 个交易日，数据单只股票按调用获取。对于 30/50/100 只股票，不能凭文档假定可按时拉全，须实测请求延迟、配额、服务稳定性和相关使用条款。

**可切换 Provider**：Tushare `rt_min(freq='1MIN',ts_code=...)` 官方支持多代码，实时分钟权限独立付费；历史分钟 `pro_bar` **不是**实时分钟替代品。经券商授权的 QMT `xtdata.subscribe_quote(period='1m')` 可作为后续接入，依运行环境和用户资格而定。接口文档不代表用户已获权益。

Adapter 唯一返回标准：`fetch_final_bars(symbols, from_cursor)->{bars,coverage,lag,errors,provider_clock}`；可以逐只或批量，**无论 provider 怎样命名字段，都必须转换单位/时区/时间标签/最终状态**。

## D02｜数据语义

- 交易所 ID：`SH`/`SZ`；适配器可转换如 `600000.SH` → `SH.600000`，`000001.SZ` → `SZ.000001`。
- 1m K 线必须有明确区间 `[start,end)`，时间为上海交易所本地 `+08:00`；bar_end 不得大于服务器正确时间。
- `volume_shares` 单位为股（AKShare 分时 `成交量` 标明为手，按正常 A 股一手=100 股转换，并对可能的特殊交易产品排除）；`amount_cny` 单位元；不得与千元/万元混淆。
- K 线不复权并保持原始价格；拆分/复权时历史跨日基准需要审计，指标不允许跨除权日出现假 Spike。
- 时间戳标记 start 或 end 由实测校准；**不允许仅凭标签“09:31”推断它代表 09:30–09:31 还是 09:31–09:32**。
- `data_quality`: VALID / STALE / GAP / PARTIAL / REVISED_PENDING / INVALID / SOURCE_UNAVAILABLE。额外显示 coverage 比例。

## D03｜交易时段

沪深 A 股连续竞价：`09:30–11:30` 与 `13:00–14:57`；集合竞价：`09:15–09:25` 与 `14:57–15:00`；实际交易日按交易所公告交易日历。仅连续竞价生成上涨 Spike；第一个合法完整 bar 的划分必须由校准的 bar 边界决定。午休跨越、非交易日、停牌均不推新信号。不得用工作日硬编码替代休市日历。

日历应支持本地缓存 + 来源/更新时间 + 校验失败时 fail closed；交易制度或行情权限变化不得由 AI 臆造。

## D04｜安全与能力探测门禁

真实 Provider 启用前依次进行：

1. 元信息合法性：可识别交易所、普通 A 股、ST/新股/停牌状态、最新交易日；未知则禁止重点提醒。
2. 两只公开样本在盘中观察，核对 1m 时间标签、完整状态与价格/成交金额单位；实测对齐权威行情页面（允许合理更新差异）。
3. 数据延迟记录 `close_to_received_ms`, `latest_available_bar_end`; 不允许缓存值假装实时；对 provider 轮询限流/断路器。
4. 测试 10→30→50 只股票时的全量轮询吞吐和覆盖。测试时不要伪造 100 只全部合格。
5. 明确 provider 权限/terms，个人自用不代表自动获得重分发许可；对外商用单独审批。

## D05｜Provider 健康状态

- `HEALTHY`: 有效股票覆盖达到设定门槛，延迟符合 Gate。
- `DEGRADED`: 部分标的缺失或者延迟接近上限；缺失股票停止出信号，界面显式覆盖率。
- `STOPPED`: 数据完全不可得、语义无法确定、时钟严重漂移、交易日历未知；所有**新**信号停止。

源切换必须防同一分钟跨 Provider 重复出卡（同 bar symbol+start 只一个标准记录；revision 有版本标识）。本地导入的 Fixture 只允许在 `SIMULATION` 模式，不得与 `LIVE` UI 混淆。

## D06｜部署与许可

默认 Python 运行在用户本地 macOS / Windows / Linux，AKShare/付费 API 用环境变量。QMT 可能需要券商专用客户端与 Windows 环境，必须以实际账户适配，不做默认运行依赖。对外服务前完成商用行情数据许可、提示文案及可能的证券投资咨询监管评估。
