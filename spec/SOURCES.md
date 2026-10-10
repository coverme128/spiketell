# Source Register / External Facts Checked 2026-10-09

1. AKShare A 股 1 分钟历史分时字段/时间/限量（1分钟近 5 个交易日、成交量单位“手”）：https://github.com/akfamily/akshare/blob/main/docs/data/stock/stock.md
2. Tushare `rt_min` 实时分钟、多股票代码、输出成交额/股数：https://tushare.pro/document/2?doc_id=374
3. Tushare `rt_min_daily` 单日历史实时分钟：https://tushare.pro/document/2?doc_id=457
4. Tushare 实时分钟独立权限与公开价格（核验时为个人约 1000 元/月）：https://tushare.pro/document/2?doc_id=290
5. XtQuant `subscribe_quote` / `subscribe_whole_quote` 文档（仅证明存在接口，不能证明任何券商已授权使用）：https://zsrl.github.io/xtquant-doc/xtquant/xtdata.html
6. 上海证券交易所《交易规则（2026年修订）》连续竞价时间/法定休市： https://www.sse.com.cn/lawandrules/sselawsrules2025/fund/trading/c/c_20260424_10817739.shtml
7. 深圳证券交易所交易时段说明：https://www.szse.cn/www/investor/knowledge/stock/deal/t20191204_572383.html

## 审慎说明

官方或项目文档证明接口存在、字段意义及某时点的权限价格，不证明它在你的账户、机器、网络上**一定可访问**，更不保证延迟/稳定性。商用与再分发权要独立核查，不能因 Python 包开源就默认免费商用行情。SSE/Browser Notification 需要浏览器有效运行条件，不能把“浏览器关闭后的推送”算成已交付能力。
