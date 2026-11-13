// Lifecycle regression: use the actual picker with isolated HTTP fixtures.
const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));let slow=false,pending=0;
  await page.route('http://picker.test/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><body></body>'});
   if(url.pathname==='/api/projects'){if(slow){pending++;await new Promise(r=>setTimeout(r,200));}return route.fulfill({json:[{id:'local:qa',name:'QA'}]}).catch(()=>{});}
   if(url.pathname==='/api/asset-folders')return route.fulfill({json:{folders:{},revision:'folders'}});
   if(url.pathname==='/api/asset-catalog')return route.fulfill({json:{items:[],total:0}});
   if(url.pathname==='/pending.png')return route.fulfill({status:425,json:{error:'preview pending'}});
   if(url.pathname==='/image.png')return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1sAAAAASUVORK5CYII=','base64')});
   return route.fulfill({status:404});
  });
  await page.goto('http://picker.test');
  await page.evaluate(()=>{
   window.STUDIO_TOKEN='qa';window.StudentAgeRecordLabels={html:(id,name)=>id+' '+name};window.StudentAgeSearch={matches:()=>true};
   window.draft={content:'未保存'};window.STUDIO_PICKER_CONTEXT=()=>({project:{id:'local:qa',name:'QA'},revision:'r1',doc:{persons:{},draft},localIds:{}});
   window.openRecords=()=>STUDIO_ASSET_PICKER.pickRecords('portrait',{title:'表情',multiple:true,rows:[{id:1,name:'普通',selectionOnly:true},{id:2,name:'微笑',selectionOnly:true}],image:()=>'/image.png'});
  });
  await page.addScriptTag({path:path.resolve(__dirname,'../asset-picker.js')});
  for(let i=0;i<50;i++){
   await page.evaluate(()=>{window.picked=openRecords()});
   await page.waitForFunction(()=>document.querySelectorAll('[data-picker-asset-id]').length===2);
   if(i%5===0){await page.locator('[data-picker-asset-id]').first().click();await page.locator('[data-picker-enter-selected]').click();assert.deepEqual(await page.evaluate(async()=> (await picked).map(r=>r.id)),[1]);}
   else{await page.evaluate(()=>STUDIO_ASSET_PICKER.close());assert.equal(await page.evaluate(()=>picked),null);}
   assert.equal(await page.locator('#asset-picker > *').count(),0);
  }
  assert.equal(await page.evaluate(()=>draft.content),'未保存');
  await page.evaluate(()=>{
   const later=window.setTimeout,cancel=window.clearTimeout;window.longTimers=new Set();
   window.setTimeout=(fn,delay,...args)=>{const id=later(()=>{longTimers.delete(id);fn(...args)},delay);if(delay>=1000)longTimers.add(id);return id};
   window.clearTimeout=id=>{longTimers.delete(id);cancel(id)};
   window.pendingFace=STUDIO_ASSET_PICKER.pickRecords('portrait',{rows:[{id:1,name:'待缓存表情',selectionOnly:true}],image:()=>'/pending.png'});
  });
  await page.waitForFunction(()=>longTimers.size>0);await page.evaluate(()=>STUDIO_ASSET_PICKER.close());
  assert.equal(await page.evaluate(()=>longTimers.size),0);assert.equal(await page.evaluate(()=>pendingFace),null);
  // An explicit record source list belongs to the caller, not the global story context.
  for(const kind of ['portrait','background']){
   await page.evaluate(kind=>{window.sourcePick=STUDIO_ASSET_PICKER.pickRecords(kind,{projectId:'local:other',rows:[{id:101,name:'Original'},{id:103,name:'Mod',source:'original'}],localIds:['103']})},kind);
   await page.waitForSelector('[data-picker-source-id="101"]');assert.equal(await page.locator('[data-picker-source-id="103"]').count(),0);
   await page.locator('[data-asset-source="mod"]').click();await page.waitForSelector('[data-picker-source-id="103"]');assert.equal(await page.locator('[data-picker-source-id="101"]').count(),0);
   await page.locator('[data-picker-source-id="103"]').click();assert.equal((await page.evaluate(()=>sourcePick)).id,103);
  }
  await page.evaluate(()=>{window.emptySource=STUDIO_ASSET_PICKER.pickRecords('portrait',{rows:[{id:1,name:'Original',source:'mod'}],localIds:[]})});
  await page.waitForSelector('[data-picker-source-id="1"]');await page.locator('[data-asset-source="mod"]').click();
  await page.waitForSelector('.ap-empty');await page.evaluate(()=>STUDIO_ASSET_PICKER.close());assert.equal(await page.evaluate(()=>emptySource),null);
  await page.addScriptTag({path:path.resolve(__dirname,'../character-ui.js')});
  await page.addScriptTag({path:path.resolve(__dirname,'../event-bindings.js')});
  await page.evaluate(()=>{
   window.giftHost=document.createElement('div');document.body.append(giftHost);
   window.gift=StudentAgeEventBindings.create({bindings:{gifts:[]},persons:{103:{id:103,name:'Mod recipient'}},refs:{PersonCfg:{101:{id:101,name:'Original recipient'}}},localIds:{PersonCfg:['103']}});
   gift.mount(giftHost,{type:110,projectId:'local:other',repaint:()=>{},error:e=>{throw e}});
  });
  await page.locator('[data-gift-person="0"]').click();await page.waitForSelector('[data-picker-source-id="101"]');
  assert.equal(await page.locator('[data-picker-source-id="103"]').count(),0);
  await page.locator('[data-asset-source="mod"]').click();await page.waitForSelector('[data-picker-source-id="103"]');await page.locator('[data-picker-source-id="103"]').click();
  await page.waitForFunction(()=>gift.value().gifts[0].npc===103);
  slow=true;
  await page.evaluate(()=>{const original=window.fetch;window.abortedReads=0;window.fetch=(...args)=>original(...args).catch(e=>{if(e.name==='AbortError')abortedReads++;throw e});window.opening=STUDIO_ASSET_PICKER.open('background')});
  await page.waitForTimeout(50);await page.evaluate(()=>STUDIO_ASSET_PICKER.close());
  assert.equal(await page.evaluate(()=>opening),false);assert.ok(await page.evaluate(()=>abortedReads)>0);assert.ok(pending>0);slow=false;
  await page.evaluate(async()=>{await STUDIO_ASSET_PICKER.open('background',{selectFromDocument:true,onClose:()=>STUDIO_ASSET_PICKER.open('portrait',{selectFromDocument:true})});STUDIO_ASSET_PICKER.close()});
  await page.waitForTimeout(100);assert.equal(await page.locator('#asset-picker[open] h2').textContent(),'选择人物');
  await page.evaluate(()=>STUDIO_ASSET_PICKER.close());assert.deepEqual(errors,[]);
  console.log('PASS: 50 open/close cycles, selection/cancel, draft preservation, retry timer cleanup, in-flight read cancellation, immediate reopen');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
