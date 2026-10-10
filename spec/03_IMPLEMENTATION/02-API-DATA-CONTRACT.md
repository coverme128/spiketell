# 03 — API, Database & Event Contracts

完整 REST/SSE 机读草案见 `contracts/openapi.yaml`；领域 JSON Schema 见 `contracts/*.schema.json`。

## C01｜REST API（`/api/v1`）

| Method | Path | 意义 |
|---|---|---|
| GET | `/health/live` | 进程存活，不等于可监控 |
| GET | `/health/ready` | Provider + 日历 + 本轮覆盖 + DB 状态 |
| GET | `/radar` | 当前 Top1–3 + 计数 + feed health |
| GET | `/watchlist` | 监控股票、enabled、provider 状态 |
| POST | `/watchlist` | 批量添加，部分失败逐项返回 |
| DELETE | `/watchlist/{symbol}` | 停止监控并保留历史 |
| GET | `/episodes` | cursor 分页历史，筛选时间和状态 |
| GET | `/episodes/{id}` | 事件变更与计算理由 |
| GET | `/settings` | 通知行为和扫描约束（不改策略历史） |
| PATCH | `/settings` | 保存用户配置，审计新版本 |
| GET | `/events/stream` | SSE 有序增量和重放 |
| GET | `/diagnostics` | 有效覆盖、滞后、请求频次、错误原因 |

所有写入使用校验并返回结构化错误：`INVALID_SYMBOL`, `NOT_SUPPORTED`, `WATCHLIST_LIMIT`, `INVALID_SETTINGS`, `FEED_UNAVAILABLE`；禁止 200 + 模糊 `success=false`。DELETE 幂等。Schema 变化采用 API 版本控制。

## C02｜数据库表

- `instruments(symbol PK, name, board, risk_status, list_date, metadata_source, checked_at)`
- `watchlist(symbol PK FK, enabled, added_at, updated_at)`
- `minute_bars(symbol,bar_start_at,interval,source,revision,open,high,low,close,volume_shares,amount_cny,bar_end_at,received_at,is_final,quality, PK(symbol,bar_start_at,interval,source,revision))`
- `bar_decisions(symbol,bar_start_at,rule_version,triggered,score,priority,reasons_json,quality,source_revision, unique(symbol,bar_start_at,rule_version))`
- `episodes(episode_id PK,symbol,session_date,trigger_bar_start,trigger_bar_close,rule_version,current_state,current_priority,current_score,last_bar_end,weak_count,nontrigger_count,started_at,ended_at,updated_at)`
- `episode_events(event_id PK,sequence UNIQUE,episode_id FK,event_type,prior_state,new_state,bar_start_at,bar_end_at,details_json,recorded_at, UNIQUE(episode_id,event_type,bar_start_at))`
- `alert_outbox(alert_id PK,episode_id,kind,created_at,notified_at, UNIQUE(episode_id,kind))`
- `provider_health(provider PK,last_ok_at,lag_ms,coverage_ratio,status,last_error)`
- `settings(id PK, key UNIQUE, value_json,revision,updated_at)`

Schema 推荐由 migrations versioned SQL/ Alembic 唯一管理；数据库 WAL，事务内更新 episode & append event & enqueue alert，事务后 SSE 读取事件序号。

## C03｜金融精度

将价格与成交金额以 Decimal/string 存储，API JSON 字段定义为 decimal string，UI 格式化显示，不允许数据库浮点误差破坏阈值或重复处理。原始行情传入 float 时先 `Decimal(str(value))`；同一分钟数据修订存 revision 与 fingerprint，前次事件不可删除。

## C04｜回放与快照

新客户端先 `GET /radar`，再通过 SSE 监听最新序号；服务端若序号已超出 retention 返回 `resync_required`，客户端回读快照。接受 `Last-Event-ID` 或明确 cursor，不得同时从多个 cursor 重放造成漏事件。后端全程 append-only event 实现崩溃恢复，frontend toast 与系统桌面通知必须根据 `delivery_mode=LIVE` 决定是否产生。

## C05｜可观测指标

`feed_lag_seconds`, `watchlist_coverage_ratio`, `poll_requests_per_minute`, `poll_failure_rate`, `valid_final_bar_count`, `suppressed_stale_count`, `episode_created_count`, `alert_dedup_count`, `sse_reconnect_count`, `backend_uptime`。所有指标都要带时间窗口和观察样本数量，不能只有“正常/异常”标签。

## C06｜可直接用于前端联调的静态样本

`contracts/examples/minute_bar.json`、`spike_card.json`、`episode_event.json`、`radar_response.json` 均为具有 `SIMULATION` 标识的合成合同示例，可用于 Schema / Component Tests，**不可**在 Live 模式作为真实行情回退数据。
