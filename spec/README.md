# A-Share Multi-Stock Spike Radar V1 — 1+4 Commercial Delivery Bundle

**交付日期**：2026-10-09  | **版本**：1.0.0 | **交付对象**：Codex / 产品负责人

本 ZIP 是可落地的 **产品与研发实施规格包**（不是已实现或已验证的生产程序）。包含 MASTER + 四个主包，以及机器可读合同、合成 Fixture、确定性规则参考实现、静态校验脚本、验收门禁和 Codex 开工指令。

## 一分钟了解

- **谁用**：个人投资者，在交易时间内监控其自选 A 股（目标 20–50，向 100 扩展需数据源压测）。
- **做什么**：闭合 1 分钟 K 线检测 Spike → 强弱分级 → Top 1–3 卡 → 浏览器提醒 → Episode 连续追踪。
- **不做什么**：买入评级、介入价、上涨概率、次日卖出、自动交易、L2、新闻 AI、全市场扫描、券商下单。
- **首要约束**：数据不新鲜即禁发；同一异动去重；用户不得误以为分钟收盘价是实时可成交价。

## 1+4 包目录

1. `00_MASTER.md` — 范围、主契约、冻结决策、实施边界
2. `01_PRODUCT/` — PRD / 体验与文案 / 用户旅程
3. `02_DOMAIN_RULES/` — 市场会话、标准化、检测、分级、Episode、通知
4. `03_IMPLEMENTATION/` — 技术架构、OpenAPI/存储契约、Codex 实施计划
5. `04_PRODUCTION_HANDOFF/` — 测试、发布门禁、运营手册、Codex 任务书

辅助目录：`contracts/`, `fixtures/`, `reference/`, `tests/`, `tools/`。

## 使用方式

```bash
python3 tools/validate_bundle.py
python3 -m unittest discover -s tests -v
# Codex 按 04_PRODUCTION_HANDOFF/03-CODEX-START.md 执行；
# 代码必须另建于真实项目仓库，不要将交付规格包冒充已实现的程序。
```

## 定义清楚的两种状态

- **SPEC_READY**：本包静态合同、Fixture、参考实现和文档一致。
- **RUNTIME_READY**：Codex 按门禁集成真实行情、通过连续交易时段测试后才能宣告；本 ZIP 不声明已达到。

## 关键外部依赖

AKShare 分时接口只作为 **候选开发数据源**，不能未经授权与负载验证就承诺稳定、商用和 50/100 股分钟刷新。Tushare 实时分钟或经授权的券商接口是备选，由能力探测及采购授权决定。详见 `02_DOMAIN_RULES/02-MARKET-DATA.md` 与 `SOURCES.md`。
