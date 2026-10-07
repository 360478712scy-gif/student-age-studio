'use strict';
// Production condition directory + select popup, with unloaded dialogue bodies.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),templates=JSON.parse(fs.readFileSync(path.join(root,'condition-templates.json'),'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('http://conditions.test/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<html lang="zh-CN"><body><script src="/remote-talks.js"></script><script src="/conditions.js"></script><script src="/condition-library.js"></script><script src="/search.js"></script><script src="/ui-controls.js"></script></body></html>'});
   if(url.pathname.startsWith('/api/'))return route.fulfill({json:url.pathname==='/api/table'?{rows:{}}:{templates:[],entries:[]}});
   return route.fulfill({contentType:'text/javascript; charset=utf-8',body:fs.readFileSync(path.join(root,url.pathname.slice(1)),'utf8')});
  });
  await page.goto('http://conditions.test/');await page.addStyleTag({path:path.join(root,'styles.css')});
  await page.evaluate(templates=>{
   const R=StudentAgeRemoteTalks,summaries={};
   for(let i=0;i<10000;i++){const id=7001+i;summaries[id]={fields:['id','content'],record:{id},excerpt:id===7002?'':id===7249?'后页目标对话':'对话摘要 '+id,hasText:id!==7002};}
   window.qaBodyReads=0;window.qaTable=R.create({version:1,generation:'condition-qa',ids:Object.keys(summaries),summaries},()=>{qaBodyReads++;throw Error('条件引用不得载入正文');},'r1');
   qaTable[7300].content='当前草稿的目标';
   window.qaRefs={TalkCfg:R.referenceView({7001:{id:7001,content:'被本地覆盖的原版'},99:{id:99,content:'原版目录目标'}},qaTable)};
   window.STUDIO_CURRENT_PROJECT=()=> 'qa-only';window.STUDIO_PROJECTS=()=>[];
   window.qaOptions={templates,refs:qaRefs,projectId:'qa-only'};window.qaResult=null;
   StudentAgeConditionLibrary.open({...qaOptions,rows:[]}).then(value=>window.qaResult=value);
  },templates);
  const add=async(label,key)=>{await page.locator('.condition-library-search').fill(label);await page.locator('[data-library-key="'+key+'"]').click();};
  await add('对话到达','event:3');await add('本回合对话','event:30');
  const cards=page.locator('.condition-selected-card');assert.equal(await cards.count(),2);assert.equal(await page.locator('[data-selected-count]').textContent(),'2 项');
  assert.equal(await cards.nth(0).locator('option').filter({hasText:'对话摘要'}).count(),0);
  assert.equal(await page.evaluate(()=>StudentAgeRemoteTalks.stats(qaTable).loaded),0);
  await cards.nth(0).locator('[data-library-variant]').selectOption({label:'未对话到达 · 任一项'});
  const pick=async(card,param,query,label)=>{
   await card.locator('[data-library-param="'+param+'"]').locator('..').locator('.uc-trigger').click();
   await page.locator('.uc-search').fill(query);
   await page.locator('.uc-option').filter({hasText:label}).click();
  };
  await cards.nth(0).locator('[data-library-param="2"]').locator('..').locator('.uc-trigger').click();
  assert.equal(await page.locator('.uc-option').count(),80,'the popup renders one page');
  await page.locator('.uc-popup-foot button').last().click();assert.equal(await page.locator('.uc-option').count(),80);
  await page.locator('.uc-search').fill('7249');await page.locator('.uc-option').filter({hasText:'后页目标对话'}).click();
  await pick(cards.nth(0),3,'7002','[7002]'); // Empty summaries are valid references.
  await pick(cards.nth(1),2,'当前草稿的目标','[7300]');
  await page.locator('[data-library-apply]').click();
  const expected=[[3,-3,7249,7002],[3,30,7300]];assert.deepEqual(await page.evaluate(()=>qaResult),expected);
  await page.evaluate(()=>{qaResult=null;StudentAgeConditionLibrary.open({...qaOptions,rows:[[3,-3,7249,7002],[3,30,7300],[3,3,1999999]]}).then(value=>qaResult=value);});
  assert.equal(await cards.nth(0).locator('[data-library-param="2"]').inputValue(),'7249');
  await cards.nth(0).locator('[data-library-param="2"]').locator('..').locator('.uc-trigger').click();
  assert.equal(await page.locator('.uc-option[aria-selected="true"]').count(),1);
  await page.locator('.uc-search').press('Enter');
  assert.equal(await cards.nth(0).locator('[data-library-param="2"]').inputValue(),'7249','opening and accepting keeps an off-page current choice');
  assert.match(await cards.nth(1).textContent(),/当前草稿的目标/);
  assert.match(await cards.nth(2).textContent(),/编号 1999999/);
  await page.locator('[data-library-apply]').click();
  assert.deepEqual(await page.evaluate(()=>qaResult),[...expected,[3,3,1999999]]);
  assert.equal(await page.evaluate(()=>qaBodyReads),0);assert.deepEqual(errors,[]);
  console.log('CONDITION_TALK_REFERENCES_OK: both families, variants, search, paging, draft overrides, empty/unknown references, apply/reopen; zero body reads and page errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
