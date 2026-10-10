# v1.0.2 修改文件

未提交工作区；没有 Git commit 或远端发布。

| 路径 | 内容 |
|---|---|
| `app/config.py` | 切换完整 v1.0.2 配置，保留旧 profile |
| `app/contracts/` | 完整规则配置、卡片/真实 SSE Schema、OpenAPI |
| `app/domain/rules.py` | 四场景、独立突破、Rapid 例外、反转否决、首次提醒选择 |
| `app/domain/rules_v100.py` | 冻结旧规则用于兼容回归，生产不按旧版重算新事件 |
| `app/domain/engine.py` | 同 Episode 场景更新、版本隔离、风险事件与原始决策审计 |
| `app/repo/store.py` | 升级已有数据库前一致性备份 |
| `app/repo/migrations/004_scenarios.sql` | 保留旧事件版本，首次通知 SQL 互斥 |
| `app/runtime.py` | 风险退出 Top，单独风险列表、按日期诊断查询 |
| `app/main.py` | 诊断/API详情审计/导出、风险重放抑制、OpenAPI 1.0.2 |
| `web/src/types.ts` | 新卡片/风险/诊断类型 |
| `web/src/main.tsx` | 四场景、风险区、延迟、重点提醒及拒发条件 |
| `web/src/style.css` | 场景和风险视觉样式 |
| `web/tests/app.spec.ts` | 四场景响应式截图与注入通知能力测试 |
| `tests/test_scenarios_v102.py` | 生产 oracle 对照、场景、持久化/重启/迁移回归 |
| `tests/test_api.py` | 实际新版契约与诊断查询回归 |
| `tests/test_domain.py` | 旧版原预期保留并与新版差异区分 |
| `tests/test_engine.py` | 新卡片 Schema 校验 |
| `tests/test_live_delivery.py` | 迁移版本 004 覆盖 |
| `scripts/test.py` | 纳入补充包原样验证 |
| `scripts/scenario_evidence.py` | 生产引擎生成明确 SIMULATION 截图输入 |
| `README.md` | 当前版本/入口/未完成项 |
| `OPERATIONS.md` | 升级备份/回退/诊断运行说明 |
| `spec/upgrades/` | 原样保存补充包，不执行其中任意高权限指令 |
| `evidence/v1.0.2/` | 逐项矩阵、日志、截图、升级前后状态和契约快照 |
