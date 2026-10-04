'use strict';
// Production warehouse, workshop and navigation with disposable HTTP fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),schemas=JSON.parse(fs.readFileSync(path.join(root,'catalog-schema.json'))).schemas;
const features=JSON.parse(fs.readFileSync(path.join(root,'workshop-features.json'))).filter(f=>f.id==='items');
const blocked=process.argv.includes('--expect-blocked');
(async()=>{const browser=await chromium.launch({executablePath:process.env.CHROME_PATH,headless:true});try{
 const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[],requests=[],checks=[];
 page.on('pageerror',error=>errors.push(error.message));
 const project={id:'local:warehouse-draft-qa',name:'物品草稿导航验收'};
 const local={ItemCfg:{1000000:{id:1000000,name:'已有物品',icon:'Mods/qa/item.png',type:1,desc:'已有说明',future:{keep:[1,2]}}},BookCfg:{1000001:{id:1000001,name:'已有书籍',icon:'Mods/qa/book.png',type:3001,capacity:50,future:'保留'}},ShopCfg:{1000000:{id:1000000,type:1,price:12,future:'保留商品'}}};
 const refs={ItemTypeCfg:{1:{id:1,name:'消耗品'},3:{id:3,name:'书籍'},3001:{id:3001,name:'故事'}}};
 let revision='r1',autoSave=false,warningOnce=false;
 const warning='ItemCfg 编号 1000000：模拟可确认的字段警告';
 const info=()=>({project,revision,features,tables:Object.keys(schemas).map(name=>({name,label:schemas[name].label,schema:schemas[name],localCount:Object.keys(local[name]||{}).length})),commands:{condition:[],effect:[]}});
 await page.route('http://studio.test/**',async route=>{
  const req=route.request(),url=new URL(req.url()),name=url.searchParams.get('name');requests.push({method:req.method(),path:url.pathname,name});
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!DOCTYPE html><html lang="zh-CN"><body></body></html>'});
  if(url.pathname==='/api/display-settings'){if(req.method()==='POST')autoSave=req.postDataJSON().autoSave;return route.fulfill({json:{workshopFavorites:[],autoSave,showRecordIds:true}});}
  if(url.pathname==='/api/workshop')return route.fulfill({json:info()});
  if(url.pathname==='/api/table')return route.fulfill({json:{name,schema:schemas[name]||{fields:[]},rows:{...refs[name],...local[name]},referenceRows:refs[name]||{},localRows:local[name]||{},localIds:Object.keys(local[name]||{}),revision}});
  if(url.pathname==='/api/warehouse-save'){
   const payload=req.postDataJSON();assert.equal(payload.revision,revision);
   if(warningOnce&&!payload._confirmedSaveWarnings?.includes(warning))return route.fulfill({status:400,json:{code:'save_warnings',error:'当前配置还有未完成内容。',warnings:[warning]}});
   warningOnce=false;Object.assign(local,structuredClone(payload.tables));revision+='x';return route.fulfill({json:{ok:true,revision,tables:local}});
  }
  if(url.pathname==='/api/assets'||url.pathname==='/icon.png')return route.fulfill({status:204});
  return route.fulfill({status:404,json:{error:'unexpected request '+url.pathname}});
 });
 await page.goto('http://studio.test/');for(const file of ['styles.css','workshop.css','characters.css'])await page.addStyleTag({path:path.join(root,file)});
 await page.evaluate(project=>{
  window.STUDIO_TOKEN='qa';window.STUDIO_BOOTSTRAPPING=true;window.STUDIO_PROJECTS=()=>[project];window.STUDIO_CURRENT_PROJECT=()=>project.id;
  let nextId=1000100;window.STUDIO_IDS={ensure:async()=>{},allocate:()=>nextId++,canUndo:()=>false,canRedo:()=>false};
  window.STUDIO_REQUEST_CLOSE=async()=>true;window.STUDIO_STORY_NAV={busy:()=>false};
  window.qaNotices=[];window.STUDIO_NOTIFY=(message,error)=>qaNotices.push({message,error});window.STUDIO_REPORT_ERROR=error=>qaNotices.push({message:error.message,error:true});
  window.StudentAgeConditions={mount:()=>{},summary:()=>'',parameterHTML:()=>''};window.StudentAgeEffects={mount:()=>{}};
 },project);
 for(const file of ['record-labels.js','search.js','character-ui.js','save-review.js','warehouse.js','workshop.js','navigation.js'])await page.addScriptTag({path:path.join(root,file)});
 await page.evaluate(()=>{const create=StudentAgeWarehouse.create;StudentAgeWarehouse.create=(...args)=>window.qaWarehouse=create(...args);return STUDIO_OPEN_WORKSHOP();});
 await page.evaluate(()=>{window.STUDIO_BOOTSTRAPPING=false;STUDIO_NAV.changed();});
 const open=async()=>{await page.locator('[data-feature="items"]').first().click();await page.waitForFunction(()=>document.querySelector('[data-wh="new"]')||qaNotices.some(n=>n.error));assert.equal(await page.locator('[data-wh="new"]').count(),1,JSON.stringify({errors,notices:await page.evaluate(()=>qaNotices)}));};
 const snapshot=()=>page.evaluate(()=>JSON.parse(qaWarehouse.snapshot()).tables);
 const saves=()=>requests.filter(r=>r.path==='/api/warehouse-save').length;
 const home=async decision=>{await page.click('[data-wh="home"]');await page.waitForSelector('#studio-unsaved[open]');await page.click('[data-leave="'+decision+'"]');};
 const settledHome=()=>page.waitForFunction(()=>StudentAgeWorkshopTest.W.mode==='home');
 const add=async()=>{await page.click('[data-wh="new"]');await page.waitForSelector('[data-wh-field="name"]');const id=await page.inputValue('[data-wh-field="id"]');await page.locator('.warehouse-editor footer [data-wh="close"]').click();return id;};
 await open();await page.click('[data-wh-card="ItemCfg:1000000"]');await page.fill('[data-wh-field="desc"]','已有物品的未保存修改');await page.locator('.warehouse-editor footer [data-wh="close"]').click();
 const blank=await add(),draft=await snapshot();assert.equal(draft.ItemCfg[blank].name,'');assert.equal(draft.ItemCfg[blank].icon||'','');
 await home('cancel');assert.equal(await page.evaluate(()=>StudentAgeWorkshopTest.W.mode),'warehouse');assert.deepEqual(await snapshot(),draft);assert.equal(saves(),0);checks.push('cancel preserves both existing edits and the new blank draft');
 await home('save');await page.waitForFunction(()=>StudentAgeWorkshopTest.W.mode==='home'||qaNotices.some(n=>n.message.includes('请填写物品名称并选择图片')));
 if(blocked){assert.equal(await page.evaluate(()=>StudentAgeWorkshopTest.W.mode),'warehouse');assert.equal(saves(),0);assert.deepEqual(await snapshot(),draft);assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'reproduced',cause:'warehouse.save rejects blank name/icon before POST; save-and-continue stays in warehouse',checks,notices:await page.evaluate(()=>qaNotices)},null,2));return;}
 assert.equal(await page.evaluate(()=>StudentAgeWorkshopTest.W.mode),'home','save-and-continue must return to the production workshop home');assert.equal(saves(),1);assert.deepEqual(local,draft);checks.push('save-and-continue saves the blank item, existing edits, books, products and unknown fields');
 await open();await page.click('[data-wh-card="ItemCfg:'+blank+'"]');assert.equal(await page.inputValue('[data-wh-field="name"]'),'');await page.fill('[data-wh-field="desc"]','下次继续的草稿说明');await page.locator('.warehouse-editor footer [data-wh="close"]').click();
 await page.click('[data-wh-card="ItemCfg:1000000"]');await page.fill('[data-wh-field="name"]','');await page.locator('.warehouse-editor footer [data-wh="close"]').click();await home('save');await settledHome();assert.equal(local.ItemCfg[1000000].name,'');assert.equal(local.ItemCfg[blank].desc,'下次继续的草稿说明');assert.deepEqual(local.ItemCfg[1000000].future,{keep:[1,2]});checks.push('reopen resumes blank draft and saves an existing item with its name cleared');
 await open();const saved=structuredClone(local);await page.click('[data-wh-card="ItemCfg:'+blank+'"]');await page.fill('[data-wh-field="desc"]','明确放弃的修改');await page.locator('.warehouse-editor footer [data-wh="close"]').click();const discarded=await add();await home('discard');await settledHome();assert.deepEqual(local,saved);assert.equal(local.ItemCfg[discarded],undefined);await open();assert.deepEqual(await snapshot(),saved);checks.push('explicit discard reverts only unsaved edits and retains prior saved drafts');
 await page.selectOption('[data-wh-filter]','3');const book=await add();await home('save');await settledHome();assert.equal(local.BookCfg[book].name,'');assert.equal(local.BookCfg[book].icon||'','');assert.deepEqual(local.BookCfg[1000001],saved.BookCfg[1000001]);checks.push('unnamed book saves and returns home without changing the existing book');
 await page.evaluate(()=>STUDIO_NAV.setAutoSave(true));await open();const automatic=await add();await page.click('[data-wh="home"]');await settledHome();assert.equal(local.ItemCfg[automatic].name,'');assert.equal(await page.locator('#studio-unsaved').count(),0);checks.push('automatic navigation saves a blank item without trapping the user');
 await open();await page.click('[data-wh-card="ItemCfg:'+blank+'"]');await page.fill('[data-wh-field="desc"]','需要确认仍保留的修改');await page.locator('.warehouse-editor footer [data-wh="close"]').click();const warningDraft=await snapshot();warningOnce=true;const beforeWarning=structuredClone(local);await page.click('[data-wh="home"]');await page.waitForSelector('.save-review-dialog[open]');await page.click('[data-review-cancel]');await page.waitForFunction(()=>qaNotices.some(n=>n.message.includes('已取消保存')));assert.equal(await page.evaluate(()=>StudentAgeWorkshopTest.W.mode),'warehouse');assert.deepEqual(await snapshot(),warningDraft);assert.deepEqual(local,beforeWarning);
 await page.click('[data-wh="home"]');await page.waitForSelector('.save-review-dialog[open]');await page.click('[data-review-confirm]');await settledHome();assert.deepEqual(local,warningDraft);checks.push('backend warning cancel keeps every draft; explicit confirmation saves and returns home');
 assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'passed',checks,saves:saves()},null,2));
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
