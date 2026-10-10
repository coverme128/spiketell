# 四场景 v1.0.2 实施报告

后续更新：v1.0.1 原包已收到并完成核对，原“缺包”项已解除，见 [最新个人实盘验证报告](../minute-only/implementation-report.md)。以下保留当时升级记录。

已在现有应用完成四场景规则、Episode、通知去重、API 契约与界面升级，本机 http://127.0.0.1:8765 已运行新版本。**发布状态仍是 DATA_PROVIDER_BLOCKED / 待实盘验收**，不能交付为已通过实盘验收的成品。

## 已实现

- 新决策使用完整 `app/contracts/rule_profile.v1.0.2.json`，与补充包逐字段相同。所有价格/百分比比较使用 Decimal。未放宽 final 1m、历史同槽基准、90 秒新鲜度、日历、时钟、证券资格和成交额门槛。
- 快速拉升；真正逐分钟加速；此前 20 根连续窄幅横盘后的独立放量突破；最高优先级的冲高回落否决。普通 3m 上涨不误标加速；缺 5 日基准的突破仅记 BREAKOUT_UNVERIFIED。
- 新风险诊断不创建关注卡；已有事件原 ID 更新为 WEAKENING，写 REVERSAL_OBSERVED，移出 Top 并在风险区展示。诊断可按日期查询，不伪装成上涨提醒。
- 四类首次关注按 HIGH→BREAKOUT→ACCEL→RAPID 选择；SQLite trigger 在同一事务里互斥，并覆盖旧 MEDIUM_NEW/RAPID_NEW 记录。HIGH_UPGRADE 沿用独立唯一键，最多一次；普通 MEDIUM 不自动发重点 OS 通知。重放与风险状态禁止通知。
- 卡片显示主/匹配场景、触发分钟结束时刻、接收时刻/延迟与模式。重点提醒默认开启，可关闭；风险区单独展示。详情包含原始决策和分数，CSV/JSON 导出包含新场景字段。
- 自动备份后迁移 004，保留旧事件字节、分数和规则版本；活跃旧版本事件以旧版本关闭，冷却后才能有新轮次。

## 测试证据

- 主包原件完整性、8 项原参考测试通过；补充包完整性、34 项参考测试通过。
- **157 项后端测试通过**，含 22 组补充场景逐字段对照、生产数据库/事件链、风险否决、四类通知选择与互斥、升级一次、重启、版本迁移和实际 API Schema。
- **15 项浏览器测试通过**，含 1440/390/430 四场景截图、风险退出重点关注、五类通知的注入能力测试及去重。通知能力桩不证明 OS 实际送达。
- TypeScript 检查、生产前端构建、Python 编译检查通过；静态日志保留 Starlette 的 httpx 弃用警告。
- [静态日志](validation-static.log)、[浏览器日志](validation-browser.log)、[逐项 F201–F228](issue-matrix.csv)、[390 截图（SIMULATION）](scenarios-390-SIMULATION.png)、[升级后实例状态](runtime-after-upgrade.json)。

## 版本差异和未完成项

1. **v1.0.1 原包未提供**：已询问路径；已实现 v1.0.2 合并配置明确包含的 Rapid MEDIUM 例外、RAPID_NEW、分钟反转诊断。不能据此宣称 v1.0.1 全部 M101–M114 已核对/通过。收到原包后仍需逐项对照。
2. **明确冲突 S05**：v1.0.0 同分钟冲高回落样本为 MEDIUM，v1.0.2 要求 LOW/IGNORE 风险否决。旧用例及原期望未改，仍跑冻结旧规则；当前规则另跑全部旧样本，并对 S05 写明新版预期，保留相同 raw_score。版本/Schema/迁移数量相关测试随契约升级更新。
3. 补充包事件 Schema 是通用 envelope，现有接口是平铺 SSE payload。本次保留现有字段结构，提供匹配真实接口的严格 `episode_event.v1.0.2.schema.json`，保留旧事件种类并扩展 REVERSAL_OBSERVED/SCENARIOS_CHANGED 等；OpenAPI 同步。原包原件未改。
4. 合成 fixture 缺少 source/received_at。生产集成测试显式补 SYNTHETIC_V102 来源和虚拟收盘后 5 秒接收时间；未降低生产 validate_bar 校验，未写入用户数据库。
5. 真实盘中校准、50 股两完整日覆盖/延迟、真实 OS 送达与异常恢复仍缺证据，详见 [运行门禁](runtime-gates.md)。

## 交付与回退

代码为未提交工作区（基线 `28b713a76d25ab9aff1d4da4cbc5e462059dfcad`），没有创建或发布 Git commit。完整文件指纹见 source-manifest.json；[修改文件清单](changed-files.md)。升级前人工备份路径见 before-upgrade.json，自动备份为 `data/radar-before-v102.sqlite3`，用户自选/历史数量未变化。回退应停止服务，并成对恢复旧代码与升级前数据库；不改写新旧版本审计记录。
