# P0 验收

- DIAGNOSIS_COMPLETE：通过。两只股票各93根真实分钟，原始数据、判断与同规则回放并列，启动前单列。
- P0_PRODUCT_CLOSURE_PASS：通过。后端180项测试；浏览器19项；原始规范8项、V1.0.2参考34项及22场景fixture校验通过；前端构建通过。最后的缺失/迟到区分再跑5项诊断测试通过。
- REAL_MARKET_VALIDATION_PENDING：仍待验证。真实保存数据已在部署页面展示，重点0/其他8；部署时午休，没有新实时符合提醒条件的事件，尚无实际 OS 送达样本，不能宣告新版本完整实盘通知闭环通过。
- REAL_MARKET_VALIDATION_PASS：未宣告。

截图 deployed-real-*.png 来自真实本机服务，没有替换响应。real-data-ui-*.png 为浏览器测试渲染保存的真实快照，属于UI回归，不是当时实时行情证明。通知失败测试使用明确标注的注入浏览器能力，不是实盘失败证据。

minute_bars.json / bar_decisions.json / episode_events.json / alert_outbox.json / notification_receipts.json / runtime_evidence.json 是实施前快照；source-runtime.log 是源采集日志。没有真实通知事件时空数组是正确证据，不创造发送日志。

未改生产阈值，未增加5m触发、Level-2、秒行情、预测或交易；没有对正式库执行回放写入。用户13只自选继续保留。后台/自启动仍按此前范围延期。

已知边界：旧决策缺少新处理轨迹时明确标为推断；起始时间以首个判断分钟接收时刻估计并在UI标注；浏览器 onshow 仅证明确认展示，不证明用户已读；无回执不能断言送达或失败。缺失统计按加入自选后的应覆盖股票分钟计算，未及时覆盖还包括启动准备/迟到，与保存行情缺失分开。
