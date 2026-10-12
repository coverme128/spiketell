import {test,expect} from '@playwright/test';
import fs from 'node:fs';
test('recorded real candidates remain visible with empty top cards',async({page})=>{
 const fixture=JSON.parse(fs.readFileSync('../evidence/p0-2026-10-12/radar-snapshot.json','utf8'));
 await page.route('**/api/v1/radar',route=>route.fulfill({json:fixture}));
 await page.goto('/');
 await expect(page.getByRole('heading',{name:/今日其他异动/})).toBeVisible();
 await expect(page.getByText('已记录，未达到重点等级', {exact:false}).first()).toBeVisible();
 await page.getByText('监控运行信息',{exact:true}).click();
 await page.screenshot({path:'../evidence/p0-2026-10-12/real-data-ui-desktop.png',fullPage:true});
 await page.reload();await expect(page.getByRole('heading',{name:/今日其他异动/})).toBeVisible();
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'../evidence/p0-2026-10-12/real-data-ui-mobile.png',fullPage:true});
});
test('unavailable feed never claims healthy no movement',async({page})=>{
 const fixture=JSON.parse(fs.readFileSync('../evidence/p0-2026-10-12/radar-snapshot.json','utf8'));
 fixture.movements.items=[];fixture.movements.health.candidate_count=0;fixture.movements.health.state='DATA_UNAVAILABLE';
 await page.route('**/api/v1/radar',route=>route.fulfill({json:fixture}));await page.goto('/');
 await expect(page.getByText('行情不可用，不能判断是否无异动')).toBeVisible();
 await expect(page.getByText('监控有效，当前无符合基础异常条件的股票。')).toHaveCount(0);
});
test('notification constructor failure is recorded, never delivered - injected capability',async({page,request})=>{
 await request.patch('/api/v1/settings',{data:{notification_enabled:true,quiet_mode:false}});
 const receipts:string[]=[];
 await page.route('**/api/v1/notifications/receipt',route=>{receipts.push(route.request().postDataJSON().kind);return route.fulfill({status:204})});
 await page.addInitScript(()=>{
  (window as any).Notification=class {static permission='granted';constructor(){throw new Error('injected OS failure')}};
  (window as any).EventSource=class {constructor(){(window as any).__source=this}handlers:Record<string,Function>={};addEventListener(k:string,fn:Function){this.handlers[k]=fn}close(){}};
 });
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>Boolean((window as any).__source?.handlers.episode))).toBe(true);
 const card=JSON.parse(fs.readFileSync('../evidence/v1.0.2/ui-simulation.json','utf8')).top_cards[0];
 const data={event_id:'p0_failure_event_0001',episode_id:'p0-failure',rule_version:'spike_rules_v1.0.2',delivery_mode:'LIVE',alert_kind:'HIGH_NEW',bar_end_at:card.last_bar_end_at,card:{...card,is_attention_eligible:true,primary_scenario:'RAPID_RISE'}};
 await page.evaluate(async data=>await (window as any).__source.handlers.episode({lastEventId:'1',data:JSON.stringify(data)}),data);
 await expect.poll(()=>receipts.includes('OS_FAILED')).toBe(true);
 expect(receipts).toContain('OS_ATTEMPTED');expect(receipts).not.toContain('OS_SHOWN');
});
