# SpikeTell · A 股异动雷达

本机单用户应用：真实自选股 → 已完成分钟 → 固定规则 → 同一轮异动追踪 → 页面与浏览器通知。

**真实接入流程已实现，盘中验收尚未完成。** 2026-10-10 休市检查证明了真实搜索、个股资料和历史分钟取数；不能据此宣称个人实盘已经验收。完整状态见 [交付审计](evidence/IMPLEMENTATION_AUDIT.md)。不使用合成行情补实盘数据，不改变规则阈值制造提醒。

## 用户启动

本机已有依赖时，macOS 双击 **启动 SpikeTell.command**。Windows 提供 `启动 SpikeTell.cmd`（尚待真机验收）。启动器复用已运行实例并打开 http://127.0.0.1:8765 。

首次安装需 Python 3.12+、Node.js 22+ 和网络；本机验证 Python 3.13。

```sh
python3 scripts/setup.py
python3 scripts/launch.py
```

也可在终端前台运行 `python3 scripts/start.py`。默认只监听 localhost，单 worker；已有实例不会被第二实例绕过锁。

## 使用流程

1. 在首页核实并确认所选数据源的个人使用范围。这是用户声明，不是自动获得数据授权。
2. 到“自选股票”搜索真实名称/代码添加，或粘贴/导入 CSV。默认上限 30 只，可在自选股页调整至最多 50 只；采集能力按实际股票池另行验证。
3. 点击每只股票的“实盘验证”，可查看真实完整分钟、最后检测和未提醒原因；休市保持等待，不使用演示行情补齐。服务自动获取股票资料、交易日历、时钟见证和历史成交额。每只股票显示准备进度与失败原因，失败可重试。
4. 连续竞价时段自动观察两只股票，核验变化分钟的成交额/成交量与带时间戳报价的增量、分钟边界和收盘后稳定性。主行情与历史基准分别核验：历史源未对齐时可先进行合格的价格检测，未验证基准不得用于 HIGH 或放量突破。条件不够时保持等待，休市数据不能替代此步骤。
5. 实际股票池连续三轮满足采集检查后，恢复后的新分钟才可产生提醒；历史补入只存证据。缺基准不能 HIGH，未通过资料核验的股票不发信号。
6. 用户自行开启浏览器通知，并使用“测试通知”检查 OS 权限。页面关闭/隐藏、OS 限制或安静模式时不保证系统通知；页面内记录与后台采集按各自状态运行。

顶部持续显示交易状态、行情时间、覆盖数与暂停原因。“真实行情准备”展示实际验收进度；完整测量在 `/api/v1/measurements`。规则分数不是上涨概率，页面不提供买入评级或自动交易。

## 数据路径

- 分钟行情：东方财富公开接口，采用 AKShare 官方字段定义；生产热路径直接以有界 curl 请求，避免每股每轮重复导入 AKShare。保留原 AKShare worker 用于诊断对照。
- 历史成交额：新浪真实分钟数据独立保存；只有时间语义核验后才成为可用基准，不伪造 OHLC。
- 日历：AKShare/Sina 日历缓存；源范围不足停止放行，不以星期推断交易日。
- 元数据：真实名称、上市时间、板块、源提供的涨跌停价；须当日新鲜成交证据及新鲜分钟共同放行。未知状态不当作正常。
- 最终化：收盘至少 8 秒后，两次间隔至少 5 秒的相同观察；后续修订仍作为 correction 审计。
- 所有请求有超时、响应字节上限、共享并发/分钟预算；单股票故障有退避与断路器。

默认生产请求预算 120 次/分钟（包含双观察及共享资料请求），并发 3。股票池增加、网络性能或源限制变化时重新检查，配置数字不能替代实际吞吐。数据源可能随时变化，不能承诺免费接口永久可用。

`.env.example` 可配置数据库、端口和预算；本地 `.env` 与 `config/runtime.json` 不入包。旧的人工核验配置兼容，但正常用户不需要编辑 JSON。数据库中的自动观测记录不会捏造已有资格。

## 运行与数据

每日自动 SQLite 一致性备份，保留最近七个常规备份；默认 90 日历史保留可在活动页调整。清理过往事件会先备份，保留今天事件和去重状态。手动清理前的备份需自行管理。

```sh
.venv/bin/python scripts/manage.py backup /tmp/radar-backup.sqlite3
.venv/bin/python scripts/manage.py restore /tmp/radar-backup.sqlite3 --db data/restored.sqlite3
```

macOS 登录后自动运行是可选项：先停止手动实例，审阅后执行 `scripts/install_service.py install`；`render` 只输出配置，`uninstall` 移除服务并保留数据。不要同时运行多 worker。

## 检查与证据

```sh
python3 scripts/test.py --browser
.venv/bin/python scripts/check_shutdown.py
.venv/bin/python scripts/validate_real_history.py --semantics end
```

浏览器测试使用独立端口 18765 和测试数据库，不操作用户自选股。历史回放使用实际价格与明确的虚拟时钟，参数只是候选标签语义，不能用其证明生产校准。合成 Fixture 只在隔离的 SIMULATION 数据库中运行。

- [当前交付审计](evidence/IMPLEMENTATION_AUDIT.md)
- [AKShare 故障定位](evidence/PROVIDER_QUALIFICATION.md)
- [真实准备证据](evidence/real-preparation-check.json)
- [真实历史数据回放](evidence/real-history-replay.json)
- [发布门禁](evidence/release-gates.json)
- [运行手册](OPERATIONS.md)

原附件在 `spec/` 原样保留；当前规则版本 `spike_rules_v1.0.2`（新决策）；旧事件保留原版本。运行 API 文档为 `/openapi.json`。四场景增量原件位于 `spec/upgrades/`，生产完整配置与 Schema 位于 `app/contracts/`。

四场景升级支持快速拉升、多分钟加速、横盘放量突破，以及冲高回落风险否决。同一轮异动只更新一张卡，首次重点通知互斥，升为 HIGH 最多再提醒一次；缺乏历史成交基准的突破只记诊断。

详见 [v1.0.2 实施报告](evidence/v1.0.2/implementation-report.md)。v1.0.1 原包已核对并完成前台验证闭环，见 [个人实盘验证报告](evidence/minute-only/implementation-report.md)。真实盘中验收仍未完成；开机自启和后台提醒按用户要求延后。
