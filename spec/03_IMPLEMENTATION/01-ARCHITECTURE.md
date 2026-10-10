# 03 — Implementation Architecture (Single-User, Production-Quality)

## A01｜合理技术栈

| 层 | 首选 | 不引入 |
|---|---|---|
| 行情接入 | Python Adapter：AKShare，Tushare/QMT 接口预留 | Crawlee、浏览器定时爬虫 |
| 策略/服务 | Python 3.11+、FastAPI、Pydantic 2、APScheduler 或单循环 Scheduler | AI 模型、复杂事件总线 |
| 数据存储 | SQLite WAL + Alembic/显式 migration，UTC 或带时区时间戳规范化 | Redis、BullMQ、PGVector |
| 前端 | React 19 + TypeScript + Vite + TanStack Query（可选） | 原生 App、微前端 |
| 推送 | SSE + Browser Notifications + 前台 Toast | SMS、付费推送平台 |
| 可观测 | JSON structured logs + health/readiness + 诊断页 | 全套 APM 复杂平台 |

## A02｜模块职责

```text
app/
  api/          rest handlers, SSE replay, input validation
  domain/       canonical models, pure price math, rules, state machine
  providers/    adapter interface; akshare_adapter; tushare_adapter [optional]
  jobs/         market calendar, polling orchestrator, EOD journal, recovery
  repo/         SQLite repositories, migrations, outbox audit + indexes
  security/     localhost-only default, credentials, origin checks
  config/       rules profile, symbols, source quotas, calendar
web/
  pages/Radar,Watchlist,Activity
  components/SpikeCard,FeedHealth,NotificationGate,EpisodeTimeline
  hooks/useEventStream,useWatchlist
```

**唯一调度实例**：独立单服务进程驱动 1m scheduler。运行 `uvicorn --workers 1`；如要水平扩容，先换分布式租约机制，V1 禁止多 worker 引发重复轮询/重复 Episode。

## A03｜正常流程

1. Session Scheduler 查询合法交易日/连续竞价窗口、加载本地 watchlist 与源预算。
2. Poll Coordinator 按配置并发/批次获取 K 线，记录原始 fetch 元数据；正确处理分页/缺口/重试，限流采用指数退避和抖动。
3. Adapter 映射为规范 `MinuteBar`，校验 OHLC、字段单位、最终化、时间语义。`(symbol,bar_start_at,source)` Upsert，但修订产生 revision log。
4. Rule Engine 对每只股票封闭的历史窗口计算 Trigger、score、priority 与 reason；持久化唯一 decision。
5. Episode Projector 原子更新 active episode、活动时间线、alert_outbox；DB 事务提交后 SSE 广播。
6. 前端获取最新投影并监听增量；浏览器通知只由用户授权、可见的客户端触发一次。

## A04｜获取吞吐约束

- “每分钟 50 只”不等于每分钟免费逐只抓取必然可靠。针对不同源配请求预算 `max_calls_per_minute`, `max_concurrency`, `batch_supported`, `min_poll_interval`。
- 每分钟按 bar_end 排定任务，并在 provider 报告 finalized 且 `received_at` 可审计时接受。
- 期望的响应目标：已拿到有效 bar 后 card 计算+持久化 p95 <2s；从 K 线结束至提醒的延迟要实测，预发布建议 gate p95 <=45s；出现达不到时标为 Provider 不合格，不用模拟“0延迟”。
- 避免每分钟为每只股票抓 5 天完整历史：首次冷启动拉基线，再以 cursor 增量；Provider 不支持增量时缓存已拿 K 线并将结果去重。

## A05｜安全与数据处理

- 默认监听 `127.0.0.1:8765`，CORS 仅开发指定 localhost 地址，不暴露公网。
- 凭据 `.env.local` / 环境变量，严禁日志打印 token；zip 不携带真实秘钥。
- provider 响应不可信，校验行数/内存/取值上限，单 Symbol 超时与断路器。
- Web UI 输入 stock code 做白名单格式+股票元数据校验；日志保留 14 天、Episode 本地保留 90 天默认可调；一键导出 JSON/CSV，一键清除历史。
- 审计事件含 provider、规则版本、raw bar fingerprint，但不保存第三方私有凭据/账号交易信息。

## A06｜运行方式

Mac/Linux/Windows 本机 Python venv + 前端 build 后 FastAPI 静态托管可选；使用容器时挂载 SQLite 数据卷。设置时区 `Asia/Shanghai` 用于交易逻辑，内部 datetime 全部 timezone-aware。必须做进程自动启动选项、崩溃恢复和单实例锁（文件锁/PID 锁经过异常退出恢复）；浏览器关闭不等于监控后端退出，但**不保证桌面推送**。

## A07｜失败优先级

P0 blocking：时间戳错位、成交额单位错位、旧数据发新提醒、重启重推、缺日历仍放行、Provider 延迟未显示、UI 假 Live。P1：通知声音、多种图表、历史导出样式等。Codex 不得为了视觉完成而降低 P0 数据门禁。
