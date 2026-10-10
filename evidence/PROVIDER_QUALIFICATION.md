# AKShare 实测与实盘资格

核对日期：2026-10-10，Asia/Shanghai；本机 AKShare 1.19.1。**原始取数已经修通，实盘资格仍为 DATA_PROVIDER_BLOCKED。** 以下为本机观察，不能推定所有网络环境均如此。

## 最新实现补充

生产热路径已改为直接对 AKShare 上游公开接口做有界 curl 请求，避免每股每轮重复导入 AKShare；原 worker 仍可用于对照诊断。新增真实证券搜索、资料准备、独立新浪历史成交额、自动盘中校准及双观察最终化。实际代码能力与待验收项以 [最新交付审计](IMPLEMENTATION_AUDIT.md) 为准。以下初次修复记录保留其原始观察时间，不代表新流程已经完成盘中验收。

## 故障定位与修复

1. DNS、TLS 握手成功，未设置代理环境变量。原版 AKShare 使用 requests 请求东方财富分钟接口时，两个股票均出现 `ConnectionError → ProtocolError → RemoteDisconnected`，没有 HTTP 响应。不是 import 失败，也不是返回空表。证据：[分层诊断](akshare-diagnosis.json)。
2. 同一地址、公开参数，用 requests 加普通 User-Agent/Referer 仍失败；标准 curl_cffi 请求返回 HTTP 200、73,676 字节。证据：[传输对照](akshare-transport-checks.json)。这支持本机传输兼容性差异，不能证明具体风控、IP 封禁或 TLS 指纹原因。
3. `app/providers/worker.py` 现默认 `RADAR_HTTP_TRANSPORT=curl`，仅在隔离子进程中替换该 AKShare 模块的 HTTP 客户端，沿用其数据转换。没有代理轮换或浏览器身份模拟。可设为 `requests` 复现原路径；未来 AKShare 内部实现变更需复验，部署使用锁定依赖。
4. 先前异常被吞成通用错误，现保留不含 URL/凭据的错误类型链，并把错误码传至诊断。
5. AKShare 官方说明东财一分钟旧日 open 为 0；原适配器因此拒收整个股票。本次逐行隔离这类历史记录、未完成分钟及集合竞价；其余真正坏行仍让该股票停发，不用假 OHLC 补齐。

## 修复后样本

实测时间约 2026-10-10 10:13，见 [provider-probe-fixed.json](provider-probe-fixed.json)。原失败记录 [provider-probe.json](provider-probe.json) 保留，不再代表最新可达性。

| 股票 | 原始行数 | 历史 open=0 行数 | 子进程总耗时 | 最后原始标签 |
|---|---:|---:|---:|---|
| SH.600000 | 1,205 | 964 | 1.536 秒 | 2026-10-09 15:00 |
| SZ.000001 | 1,205 | 964 | 1.372 秒 | 2026-10-09 15:00 |

这不是盘中到达率或收盘至提醒延迟。实际日历将 10 月 10 日列为休市。原始最后标签包含收盘集合竞价，不是可发信号分钟。

[实际归一化样本](normalization-real-samples.json) 分别试算 start/end 候选语义：每股有效行数 236/237，最后候选连续竞价 bar_end 均为 14:57，无额外坏行。两种试算均为 `semantics_verified=false`；不能用数量差异选择正确语义。

## 其他实际结果

- 新浪 `stock_zh_a_minute` 可取到 1,970 行，5.485 秒，实际含 `amount` 字段；当前仅探测，未实现生产适配或自动切源。见 [替代接口探测](akshare-alternatives.json)。
- 已将有来源的 2026 全年日历及真实 SNTP 见证写入本地运行配置。NTP 偏差约 0.556 秒，往返 0.206 秒。见 [日历记录](calendar-refresh.log)、[时钟记录](clock-refresh.log)。日历还应与交易所公告复核；时钟见证不是永久有效。

## 尚不能宣称实盘就绪的原因

源使用范围证明、盘中双样本时间语义与最终化核验、每日股票主数据、历史基准、10/30/50 股负载及两个完整交易日指标尚未完成。覆盖率与 p95 聚合也还缺代码，详见 [逐项实现审计](IMPLEMENTATION_AUDIT.md)。不把开关改成 true 充当证据。

参考：[AKShare 官方股票接口文档](https://github.com/akfamily/akshare/blob/main/docs/data/stock/stock.md)、[东方财富分钟实现](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)。
