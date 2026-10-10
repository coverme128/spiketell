# 个人前台实盘验证闭环

用户已明确：开机自启与后台提醒延后，本轮优先“输入股票后进行真实行情验证”。未安装开机服务，未改变后台通知策略。

## 当前结果

- 已接收并核对 v1.0.1 原包，SHA-256 `a7ff085170dd0ba28b7cb41001a71feccbe589cca45161d62a0957dffcb7245e`，与 v1.0.2 声明一致。原件完整保存在 spec/upgrades。
- 行为版本保持 `spike_rules_v1.0.2`，不降回旧版本。Rapid MEDIUM、RAPID_NEW、开盘/午休/迟到保护均继承；R10 回落公式与否决以 v1.0.2 明确替换规则为准：`(high-close)/high`，触发后也否决上涨关注。
- 补齐 RAPID_PRICE_ATTENTION 原因、成交基准积累中提示，以及 `/setup` 的 baseline_ready_count / eligible_watch_count / baseline_status。READY 明确为全部 237 个连续竞价分钟槽位各有五个有效历史日；单个分钟可用的基准仍按实际槽位独立计算。零成交额不能算就绪。
- 自选股新增“实盘验证”入口与 `/api/v1/watchlist/{symbol}/verification`：展示实际保存的完整分钟 OHLC/成交额/来源/接收时间和延迟、今日接收分钟数、最后检测及未提醒原因、数据门禁。休市不插模拟数据，不靠等到 Spike 才判断是否正常检测。
- 修复日历尚未就绪时暂判限制、同日不再复查的问题；五分钟后自动重试。修复日内资料重查丢失价格口径变化警告的问题，只有重新核对历史后才能解除。

## 实际验证

**真实联网（休市）**：使用正式生产添加接口和真实行情请求，隔离数据库输入 600000 / 000001，取得浦发银行 / 平安银行，分别取得 9 个历史交易日。当前时间语义尚未校准，可用基准槽位仍为 0，状态 WAITING_SESSION。没有替用户确认使用范围，未写用户自选，未产生 LIVE 异动。[原始证据](real-user-input.json)。

**注入集成测试**：真实 HTTP 添加路径 → 证券准备 → 未知语义阻断 → 明确注入资格 → 三轮实际调度容量检查 → 新完整分钟 → 无历史基准 MEDIUM/RAPID_NEW → Radar 卡。这里的源、时钟与资格明确标注 INJECTED，不宣称盘中校准成功。

**自动化**：173 项后端、16 项浏览器通过；主包 8 项参考测试、v1.0.1 14 项文档契约完整性、v1.0.2 34 项参考测试通过；TypeScript/生产构建通过。新增前台入口已检查 390 宽度截图。[静态日志](validation-static.log)、[最新后端日志](validation-backend.log)、[浏览器日志](validation-browser.log)、[M101–M114](issue-matrix.csv)。

## 用户下周验证方法

1. 打开本机 http://127.0.0.1:8765 ，核实并确认数据使用范围，在“自选股票”输入自己的股票。
2. 点击该股“实盘验证”。休市出现 WAITING_SESSION 正常；开盘后观察校准、资料和采集能力是否通过。未知/过期/不完整数据仍阻断。
3. 通过后，今日完整分钟计数应增加，最后分钟时刻应持续推进，最后检测显示“正在检测”或具体的等待/风险原因。没有异动卡不等于停止采集。
4. 保持页面前台，需要通知时授权并测试。真实新分钟满足规则才有提示；不会为了验收而降低阈值或补发历史。
5. 若持续阻断，保存该股验证 JSON 与实盘运行记录，可据具体源错误/校准状态排查。

**剩余边界**：休市无法证明下周真实盘中自动校准一定成功。源分钟标签/稳定性、实际池连续性和提醒延迟仍需开盘观测；50 股两完整日验收 M113 仍 PENDING_RUNTIME。当前是可进行前台实盘验证的候选版，尚非已验收的 PERSONAL_RUNTIME_READY。后台提醒、开机自启按用户指示延后，不列为本轮交付阻塞。

## 变更与审计

核心变更：app/verification.py、app/preparation.py、app/domain/rules.py、app/main.py；web/src/StockVerification.tsx、SetupPanel.tsx、main.tsx、style.css；tests/test_minute_only.py、test_scenarios_v102.py、web/tests/app.spec.ts；scripts/test.py、check_personal_input.py。没有 Git commit/远端发布；当前工作区指纹见 source-manifest.json。升级前备份及原自选数量见 before-upgrade.json。
