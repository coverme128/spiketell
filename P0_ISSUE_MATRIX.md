# P0 问题与验收矩阵

| 项目 | 修复 / 证据 | 状态 |
|---|---|---|
| P0-A 真行情回放 | 两只股票各93根；生产 evaluate；启动前独立标记 | 完成 |
| P0-B 检测/分级/提醒混淆 | 原始决策派生候选，LOW和待确认可见，不改阈值 | 完成 |
| P0-C 首页普通异动 | 今日其他异动，时间/场景/收益/原因/JSON；重开保留 | 完成 |
| P0-D 监控健康 | 起始证据、数量、行情时间、延迟、缺失、候选/场景/HIGH、回执 | 完成 |
| P0-E 诊断与追踪 | 只读API/CLI、逐分钟判定、原始Episode与通知记录 | 完成 |
| 历史 LOW 展示 | 全池实际记录中美年健康及突破候选；不伪造回放提醒 | 完成 |
| 四场景与去重 | 原测试保留，新测试验证回放无写入与重收不重复 | 已测 |
| 实盘 OS 推送闭环 | 当前没有符合条件的实时通知样本 | 待真实交易时段验证 |
| P1 新规则 | 样本不足，不调整5m/反弹/动态阈值 | 未启动 |

文件清单：app/movement_diagnostics.py、app/domain/rules.py（仅追加诊断条件）、app/domain/engine.py（追加处理轨迹）、app/main.py、web/src/MovementPanel.tsx、web/src/main.tsx、web/src/types.ts、scripts/replay_movement.py、tests/test_movement_diagnostics.py、web/tests/p0.spec.ts，以及本轮报告/证据。既有 calibration 修改属于前轮工作，未在此轮重写。

测试及最终 Gate 见 evidence/p0-2026-10-12/VALIDATION.md。
