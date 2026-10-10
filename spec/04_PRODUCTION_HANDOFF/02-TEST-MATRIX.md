# 04 — P0/P1 Acceptance Test Matrix

| ID | Scenario | Expected | Prio |
|---|---|---|---|
| T001 | 合法 1m + 成交异常 + 突破 | NEW HIGH 单一卡 + 允许一次通知 | P0 |
| T002 | 1m 涨幅低于触发且 ret3 不达标 | 不生成 Episode | P0 |
| T003 | 价格触发但 amount<100万元 | 不生成 Episode | P0 |
| T004 | 基线少于5个有效日 | 成交倍数缺省；不得 HIGH | P0 |
| T005 | 多次获取同一 bar | 不增加 Episode/Notification 计数 | P0 |
| T006 | 当前 bar 带未来 timestamp / partial | 拒绝/停发 | P0 |
| T007 | 9:29 / 11:45 / 14:59 | 不发新连续竞价 Spike | P0 |
| T008 | 13:00 开始且 ret3 跨午休 | `ret3` 不可用，不拼接 | P0 |
| T009 | Provider 断网 120s | STALE/STOPPED banner，旧卡不显示 LIVE | P0 |
| T010 | 断网 10min 补入旧 bar | 只补历史，不能弹历史新通知 | P0 |
| T011 | MEDIUM 由同一 episode 升级 HIGH | 最多一次升级通知，无第二张卡 | P0 |
| T012 | 高强度持续 5 分钟 | 同 episode，最新状态更新，无新卡刷屏 | P0 |
| T013 | 3 次持续走弱 | episode EXPIRED，保留可查历史 | P0 |
| T014 | 未到 15 交易分钟 cooldown 又涨 | 不新建 episode | P0 |
| T015 | 15 cooldown + 10 quiet 完整成立后再涨 | 可建新 episode | P0 |
| T016 | 真实交易日为休市日 | NO_SESSION，禁止扫描 | P0 |
| T017 | 开盘新股 / ST / 停牌/未知 board | 限定禁止重点提醒，状态说明 | P0 |
| T018 | Provider 返回 volume=手（AKShare） | 标准化为股，金额为元 | P0 |
| T019 | 数据时间标签意义未知 | 不得进入 HEALTHY | P0 |
| T020 | 日历服务失效/时间漂移>2s | STOPPED，禁止新提醒 | P0 |
| T021 | OS 通知权限 denied | 页内提示继续、无重复授权请求 | P0 |
| T022 | 关闭浏览器 | UI 告知无法保证桌面通知 | P0 |
| T023 | 前端 SSE 断开与重连 | last id 补发 UI，无历史桌面通知 | P0 |
| T024 | DB 重启恢复 | episode、去重计数保持，不重复告警 | P0 |
| T025 | 50 只实盘持续两交易日 | 按 G04/G05 统计，报告合格与否 | P0 |
| T026 | 手机 390px 与 430px | 不横向溢出、卡片核心字段可读 | P0 |
| T027 | API 非法股票代码/重复导入 | 逐项错误、已存在幂等返回 | P0 |
| T028 | 已生效 bar 被 Provider 修订 | append correction，必要时 INVALIDATED | P0 |
| T029 | 分数 65 恰好、成交倍数差一点 2 | 不错判 HIGH | P0 |
| T030 | 同分排序/不同扫描顺序 | 相同 Top 排序 | P0 |
| T031 | 浏览器系统通知点击卡 | 跳对应 episode id，若不存在友好提示 | P0 |
| T032 | 用户选择安静模式 | 不发 OS 通知，Radar 仍正常更新 | P0 |
| T033 | 提醒开始之后行情过期 | 撤销 LIVE 标记，不悄悄继续显示“当前重点” | P0 |
| T034 | 采集部分股票成功 | 健康比例准确显示，缺失票不能警报 | P0 |
| T035 | 多 worker 意外同时启动 | 第二实例拒绝调度；不重复事件 | P0 |
| T036 | 交易所代码格式 SH/SZ 转换 | 错误转换会拦截、不混淆股票 | P0 |
| T037 | 只跑模拟回放但无实盘 | 明确 SIMULATION，不可宣布 Runtime Ready | P0 |
| T038 | 通知文案任何情况 | 不含“确定上涨”“买入”“收益率概率”等误导词 | P0 |
| T039 | 源账号无权限/订阅超额 | 显式 DATA_PROVIDER_BLOCKED，提供诊断信息 | P0 |
| T040 | 股票被用户停用时仍有 episode | 停新信号，历史保留 | P0 |
| T041 | 导出历史 CSV/JSON | 价格时间戳精确、有规则版本 | P1 |
| T042 | 图表线条/主题 | 响应式、无视觉干扰 | P1 |

测试需要提供：case ID、输入事件/Fixture、预期、实际、PASS/FAIL、截图或日志、git commit。任何 P0 FAIL 必须先关闭才允许 UI Freeze / Runtime Ready。
