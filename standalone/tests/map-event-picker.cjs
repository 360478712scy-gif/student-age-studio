const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});try{
const page=await browser.newPage({viewport:{width:1200,height:850}});
await page.route('http://studio.test/**',route=>route.fulfill({contentType:'text/html',body:'<html><body></body></html>'}));await page.goto('http://studio.test');
await page.evaluate(()=>{window.STUDIO_TOKEN='qa';window.fetch=async url=>({ok:true,json:async()=>({rows:new URL(url,location.origin).searchParams.get('name')==='MapCfg'?{'1':{id:1,name:'家',type:0},'12':{id:12,name:'鹅城客运站',type:0},'101':{id:101,name:'不可直接触发的分区',type:1}}:{}})});});
for(const f of ['styles.css','characters.css'])await page.addStyleTag({path:'standalone/'+f});
for(const f of ['search.js','record-labels.js','event-types.js','conditions.js','event-bindings.js','character-ui.js'])await page.addScriptTag({path:'standalone/'+f});
for(const [kind,expected] of [[-900,912],[-800,812]]){
 await page.evaluate(()=>{window.result=null;StudentAgeCharacterUI.eventType('qa',0,{}).then(r=>window.result=r);});
 await page.locator(`[data-event-type-id="${kind}"]`).click();
 assert.equal(await page.locator('[data-event-type-id="901"]').count(),0);
 await page.locator('[data-event-confirm]').click();assert(await page.locator('.character-picker-error').textContent());
 await page.locator('[data-event-map-trigger]').click();await page.locator('[data-character-choice="12"]').click();await page.locator('[data-event-confirm]').click();
 const r=await page.evaluate(()=>window.result);assert.equal(r.id,expected);assert.equal(r.mapId,12);
 await page.evaluate(id=>{StudentAgeCharacterUI.eventType('qa',id,{});},expected);assert(await page.locator('[data-event-map-trigger]').textContent().then(t=>t.includes('客运站')));await page.locator('[data-event-cancel]').click();
}
const summary=await page.evaluate(()=>StudentAgeConditions.summary([[52,1,-1]],[],{}));assert.equal(summary,'恋爱状态：单身（没有恋人）');
console.log('map-event-picker: enter/leave, location selection, reopen, no per-location tiles, condition translation passed');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
