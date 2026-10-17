'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const ready=JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_READY,'utf8'));
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const open=async()=>{await page.waitForFunction(()=>!STUDIO_BOOTSTRAPPING&&STUDIO_WORKSHOP_NAV.isOpen());await page.locator('#workshop [data-feature="story"]').click();await page.locator('[data-edit-event="7"]').click();await page.waitForFunction(()=>!StudentAgeStudioTest.S.conditionsLoading);};
 const disk=()=>JSON.parse(fs.readFileSync(path.join(ready.cfg,'EvtCfg.json'),'utf8'))['7'];
 try{
  await page.goto(ready.url);await open();
  await page.locator('#event-map').selectOption('12');
  await page.locator('#event-conditions [data-condition-library]').click();
  await page.locator('.condition-library-search').fill('是否假期');
  await page.locator('[data-library-key]').filter({hasText:'是否假期'}).first().click();
  const holiday=page.locator('.condition-selected-card').filter({hasText:'是否假期'});
  await holiday.locator('select[data-library-param="2"]').selectOption('-1');
  await page.locator('[data-library-apply]').click();
  await page.locator('#modal [data-modal-button="1"]').click();
  const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST'),page.locator('#studio-toolbar [data-nav="save"]').click()]);
  assert.equal(response.status(),200);assert((await response.json()).ok);
  await page.waitForFunction(()=>!StudentAgeStudioTest.S.dirty&&!StudentAgeStudioTest.S.saving);
  const row=disk();assert.equal(row.mapId,12);
  assert(row.condition.some(r=>JSON.stringify(r)==='[2,8,-1]'));
  assert(!row.condition.some(r=>r[0]===7&&r[1]===101&&r[2]===3));
  assert(row.condition.some(r=>JSON.stringify(r)==='[7,101,4,5]'));
  assert(row.condition.some(r=>JSON.stringify(r)==='[0,1,0.5]'));
  assert.deepEqual(row.future,{keep:true});
  await page.reload();await open();assert.equal(await page.locator('#event-map').inputValue(),'12');
  await page.locator('#event-conditions [data-condition-library]').click();
  assert.equal(await page.locator('.condition-selected-card').filter({hasText:'是否假期'}).locator('select[data-library-param="2"]').inputValue(),'-1');
  assert.deepEqual(disk(),row);assert.deepEqual(errors,[]);
  const result={status:'passed',flow:'Full editor: select location and non-holiday → apply → HTTP save → reload → reopen',event:row,errors,scope:'Synthetic data with real StudioServer and Chrome; no native desktop or game verification'};
  fs.writeFileSync(path.join(ready.output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){fs.writeFileSync(path.join(ready.output,'failure.json'),JSON.stringify({error:String(e),errors,body:await page.locator('body').innerText()},null,2));throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
