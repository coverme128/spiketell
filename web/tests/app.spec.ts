import {test,expect} from '@playwright/test';
import fs from 'node:fs';

test.beforeEach(async({request})=>{await request.patch('/api/v1/settings',{data:{quiet_mode:false}});await request.post('/api/v1/setup/source',{data:{personal_use_confirmed:false}});const res=await request.get('/api/v1/watchlist');for(const w of await res.json())await request.delete('/api/v1/watchlist/'+w.symbol)});
test('real application CRUD and blocked feed',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await expect(page.getByText('新异动检测已暂停')).toBeVisible();await expect(page.getByText('等待可信行情接入')).toBeVisible();
 await page.getByRole('button',{name:'自选股票'}).click();await page.getByLabel('股票代码').fill('600000,000001,bad,600000');await page.getByRole('button',{name:'添加到自选股'}).click();
 await expect(page.getByText('已存在，无需重复添加')).toBeVisible();await expect(page.getByText('INVALID_SYMBOL')).toBeVisible();
 await expect(page.getByLabel('SH.600000 启用监控')).toBeChecked();const saved=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes('/watchlist/'));await page.getByLabel('SH.600000 启用监控').uncheck();await saved;await page.reload();await page.getByRole('button',{name:'自选股票'}).click();await expect(page.getByLabel('SH.600000 启用监控')).not.toBeChecked();
 await page.getByRole('button',{name:'活动日志'}).click();await expect(page.getByText('暂无符合条件的异动事件')).toBeVisible();expect(errors).toEqual([]);
});
for(const width of [1440,390,430])test(`responsive ${width}`,async({page})=>{
 await page.setViewportSize({width,height:1000});await page.goto('/');await expect(page.getByText('等待可信行情接入')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:`../evidence/radar-${width}.png`,fullPage:true});
 await page.getByRole('button',{name:'自选股票'}).click();await page.getByLabel('股票代码').fill('600000');await page.getByRole('button',{name:'添加到自选股'}).click();await expect(page.getByLabel('SH.600000 启用监控')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:`../evidence/watchlist-${width}.png`,fullPage:true});
 await page.getByRole('button',{name:'活动日志'}).click();await expect(page.getByText('暂无符合条件的异动事件')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:`../evidence/activity-${width}.png`,fullPage:true});
});
test('notification denied and quiet mode persist',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(Notification,'permission',{get:()=> 'denied'}));
 await page.goto('/');await expect(page.getByText(/通知权限已拒绝/)).toBeVisible();await expect(page.getByRole('button',{name:'开启浏览器通知'})).toHaveCount(0);
 const saved=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes('/settings'));await page.getByLabel('安静模式').check();await saved;await page.reload();await expect(page.getByLabel('安静模式')).toBeChecked();
});
test('SSE reconnect fallback and missing detail',async({page})=>{
 await page.route('**/api/v1/events/stream**',route=>route.abort());await page.goto('/#episode=missing');await expect(page.getByText('降级连接 · 15 秒轮询')).toBeVisible();await expect(page.getByText('找不到这条异动记录，请返回活动日志查看。')).toBeVisible();await page.getByRole('button',{name:'关闭详情'}).click();
});
test('simulation card visibly marked and source details',async({page})=>{
 const card=JSON.parse(fs.readFileSync('../spec/contracts/examples/spike_card.json','utf8'));
 await page.route('**/api/v1/episodes?**',route=>route.fulfill({json:{items:[card],next_cursor:null}}));
 await page.route('**/api/v1/episodes/'+card.episode_id,route=>route.fulfill({json:{card,history:[],bars:[]}}));
 await page.goto('/');await page.getByRole('button',{name:'活动日志'}).click();await expect(page.getByText('SIMULATION / 非实盘',{exact:true})).toBeVisible();await page.getByRole('button',{name:'立即查看走势'}).click();await expect(page.getByRole('dialog')).toBeVisible();await expect(page.getByText('来源分钟线与完整审计依据')).toBeVisible();await page.screenshot({path:'../evidence/episode-simulation.png',fullPage:true});
});

test('source onboarding records consent without fabricating qualification',async({page,request})=>{
 await page.goto('/');const button=page.getByRole('button',{name:'开始真实行情准备'});await expect(button).toBeDisabled();
 await page.getByLabel('我已核实数据使用范围，仅在本机个人使用').check();await button.click();
 await expect(page.getByText('分钟边界与收盘确认',{exact:false})).toBeVisible();
 await page.reload();await expect(page.getByRole('button',{name:'开始真实行情准备'})).toHaveCount(0);
 const setup=await (await request.get('/api/v1/setup')).json();expect(setup.provider.personal_use_confirmed).toBe(true);expect(setup.provider.finalization_verified).not.toBe(true);
});

test('security search selection adds to real watchlist API',async({page})=>{
 await page.route('**/api/v1/instruments/search?**',route=>route.fulfill({json:{items:[{symbol:'SH.600000',name:'浦发银行'}]}}));
 await page.goto('/');await page.getByRole('button',{name:'自选股票'}).click();await page.getByLabel('搜索证券',{exact:true}).fill('浦发银行');
 await expect(page.getByText('浦发银行',{exact:true})).toBeVisible();await page.getByRole('button',{name:'添加',exact:true}).click();
 await expect(page.getByLabel('SH.600000 启用监控')).toBeChecked();
});

test('activity exports full server history with exact version fields',async({page,request})=>{
 await page.goto('/');await page.getByRole('button',{name:'活动日志'}).click();await expect(page.getByLabel('活动排序')).toBeVisible();
 const response=await request.get('/api/v1/episodes/export?format=csv');expect(response.headers()['content-type']).toContain('text/csv');expect(await response.text()).toContain('rule_version');
});

test('watchlist capacity preference persists without qualifying provider',async({page,request})=>{
 await page.goto('/');await page.getByRole('button',{name:'自选股票'}).click();
 const saved=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes('/settings'));
 await page.getByLabel('自选股数量上限').selectOption('50');await saved;
 await page.reload();await page.getByRole('button',{name:'自选股票'}).click();await expect(page.getByLabel('自选股数量上限')).toHaveValue('50');
 const setup=await (await request.get('/api/v1/setup')).json();expect(setup.provider.capacity_verified).not.toBe(true);
 await request.patch('/api/v1/settings',{data:{max_watchlist:30}});
});

for(const width of [1440,390,430])test(`v102 four scenarios simulation ${width}`,async({page})=>{
 const radar=JSON.parse(fs.readFileSync('../evidence/v1.0.2/ui-simulation.json','utf8'));
 await page.route('**/api/v1/radar',route=>route.fulfill({json:radar}));
 await page.setViewportSize({width,height:1100});await page.goto('/');
 for(const name of ['快速拉升','多分钟加速','横盘放量突破','冲高回落风险'])await expect(page.getByText(name,{exact:true}).first()).toBeVisible();
 const risk=page.locator('.risk-section');await expect(risk.getByRole('button',{name:'查看风险详情'})).toBeVisible();
 await expect(risk.getByRole('button',{name:'立即查看走势'})).toHaveCount(0);
 await expect(page.getByText('SIMULATION / 非实盘',{exact:true})).toHaveCount(4);
 await expect(page.getByText(/触发分钟结束/).first()).toBeVisible();await expect(page.getByText(/接收延迟/).first()).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:`../evidence/v1.0.2/scenarios-${width}-SIMULATION.png`,fullPage:true});
});

test('v102 notification kinds dedup and reversal replay suppression - injected browser capability',async({page,request})=>{
 await request.patch('/api/v1/settings',{data:{notification_enabled:true,quiet_mode:false}});
 await page.addInitScript(()=>{
   const emitted:string[]=[];(window as any).__notifications=emitted;
   (window as any).Notification=class {static permission='granted';onshow:any;onclick:any;constructor(title:string){emitted.push(title)}close(){}};
   (window as any).EventSource=class {constructor(){(window as any).__source=this}handlers:Record<string,Function>={};onopen:any;onerror:any;addEventListener(k:string,fn:Function){this.handlers[k]=fn}close(){}};
 });
 await page.goto('/');await expect(page.getByLabel('重点提醒')).toBeChecked();
 await expect.poll(()=>page.evaluate(()=>Boolean((window as any).__source?.handlers.episode))).toBe(true);
 const radar=JSON.parse(fs.readFileSync('../evidence/v1.0.2/ui-simulation.json','utf8'));
 let sequence=0;
 const send=async(kind:string,id:string,delivery='LIVE',veto=false)=>{
   const card={...radar.top_cards[0],episode_id:id,data_mode:'LIVE',feed_health:'HEALTHY',is_attention_eligible:!veto,primary_scenario:veto?'SPIKE_REVERSAL':'RAPID_RISE'};
   const data={event_id:'test_event_'+id,episode_id:id,rule_version:'spike_rules_v1.0.2',delivery_mode:delivery,alert_kind:kind,bar_end_at:card.last_bar_end_at,card};
   await page.evaluate(async({data,sequence})=>{await (window as any).__source.handlers.episode({lastEventId:String(sequence),data:JSON.stringify(data)})},{data,sequence:++sequence});
 };
 for(const kind of ['RAPID_NEW','ACCEL_NEW','BREAKOUT_NEW','HIGH_NEW','HIGH_UPGRADE']){
   await send(kind,kind);await send(kind,kind);
 }
 await expect.poll(()=>page.evaluate(()=>(window as any).__notifications.length)).toBe(5);
 await send('HIGH_NEW','replay','REPLAY');await send('HIGH_NEW','reversal','LIVE',true);
 expect(await page.evaluate(()=>(window as any).__notifications.length)).toBe(5);
 const saved=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().includes('/settings'));
 await page.getByLabel('重点提醒').uncheck();await saved;
 await send('BREAKOUT_NEW','disabled');expect(await page.evaluate(()=>(window as any).__notifications.length)).toBe(5);
 await request.patch('/api/v1/settings',{data:{notification_enabled:true}});
});

test('personal foreground verification shows actual blockers after entering stock',async({page,request})=>{
 await page.setViewportSize({width:390,height:1000});await page.goto('/');
 await page.getByRole('button',{name:'自选股票'}).click();await page.getByLabel('股票代码').fill('600000');await page.getByRole('button',{name:'添加到自选股'}).click();
 await page.getByRole('button',{name:'实盘验证',exact:true}).click();
 const panel=page.getByRole('dialog',{name:'个股实盘验证'});
 await expect(panel).toBeVisible();await expect(panel.getByText('尚未接收通过校准与最终化检查的分钟线。没有填入演示行情。')).toBeVisible();
 await expect(panel.getByText('分钟时间标签尚未校准')).toBeVisible();
 const data=await (await request.get('/api/v1/watchlist/SH.600000/verification')).json();
 expect(data.latest_final_bar).toBeNull();expect(data.latest_decision).toBeNull();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'../evidence/minute-only/stock-verification-390.png',fullPage:true});
 await page.getByRole('button',{name:'关闭实盘验证'}).click();await expect(panel).toHaveCount(0);
});
