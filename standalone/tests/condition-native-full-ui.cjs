'use strict';
// Actual production app + StudioServer against a disposable Mod, configured by STUDIO_TEST_READY.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const ready=JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_READY,'utf8')),browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],saves=[];
 page.on('pageerror',error=>{errors.push(error.message);console.error('Page error:',error.message);});
 page.on('request',request=>{if(request.url().endsWith('/api/save'))saves.push(request.postDataJSON());});
 const disk=table=>JSON.parse(fs.readFileSync(path.join(ready.cfg,table+'.json'),'utf8'));
 const openEvents=async()=>{
  await page.waitForFunction(()=>!window.STUDIO_BOOTSTRAPPING&&window.STUDIO_WORKSHOP_NAV?.isOpen());
  await page.locator('#workshop [data-feature="story"]').click();
  await page.locator('[data-edit-event="7"]').click();
  await page.locator('#event-conditions [data-condition-library]').waitFor({state:'visible'});
  await page.waitForFunction(()=>!window.StudentAgeStudioTest.S.conditionsLoading);
 };
 try{
  await page.goto(ready.url);
  await openEvents();
  assert.deepEqual(disk('EvtCfg')['7'].condition,[[7,1,3,30],[7,9006,3,50],[1163,5,1]]);
  assert.deepEqual(disk('TalkCfg')['7001'].check.slice(0,1),[[7,1,3,30]]);
  await page.locator('#event-conditions [data-condition-library]').click();
  const selected=page.locator('.condition-selected-card');
  assert.equal(await selected.nth(0).locator('[data-library-operator]').textContent(),'≥');
  assert.match(await selected.nth(1).textContent(),/尚未转换.*手动修改/);
  assert.equal(await selected.nth(1).locator('[data-library-raw]').inputValue(),'7,9006,3,50');
  assert.equal(await selected.nth(2).locator('[data-library-raw]').inputValue(),'1163,5,1');
  await selected.nth(0).locator('[data-library-param="3"]').fill('35');
  await page.locator('.condition-library-search').fill('智力');
  await page.locator('[data-library-key="attr:101"]').click();
  const attr=selected.nth(3);assert.equal(await attr.locator('[data-library-operator]').textContent(),'≥');
  await attr.locator('[data-library-param="3"]').fill('60');
  await page.locator('[data-library-apply]').click();
  await page.locator('#modal [data-modal-button="1"]').click();
  assert.equal(await page.locator('#modal').evaluate(modal=>modal.open),false);
  await page.waitForFunction(()=>window.StudentAgeStudioTest.S.dirty);
  console.log('Applied event conditions; saving through the visible production toolbar.');
  const [response]=await Promise.all([page.waitForResponse(response=>response.url().endsWith('/api/save')&&response.request().method()==='POST'),page.locator('#studio-toolbar [data-nav="save"]').click()]);
  assert.equal(response.status(),200);assert.equal((await response.json()).ok,true);
  await page.waitForFunction(()=>!window.StudentAgeStudioTest.S.dirty&&!window.StudentAgeStudioTest.S.saving);
  const expected=[[7,1,3,35],[7,9006,3,50],[1163,5,1],[4,1,101,60]];
  assert.deepEqual(disk('EvtCfg')['7'].condition,expected);
  assert.deepEqual(disk('EvtCfg')['7'].future,{keep:[4,9001,101,30]});
  const savedTalk=Object.values(disk('TalkCfg')).find(row=>row.content==='完整编辑器保存重开验证');
  assert(savedTalk);assert.deepEqual(savedTalk.effect,[[1163,5,1]]);
  assert.equal(savedTalk.future.keep,9);
  await page.reload();await openEvents();
  await page.locator('#event-conditions [data-condition-library]').click();
  assert.equal(await selected.nth(0).locator('[data-library-param="3"]').inputValue(),'35');
  assert.equal(await selected.nth(1).locator('[data-library-raw]').inputValue(),'7,9006,3,50');
  assert.match(await selected.nth(1).textContent(),/尚未转换.*手动修改/);
  assert.equal(await selected.nth(2).locator('[data-library-raw]').inputValue(),'1163,5,1');
  assert.equal(await selected.nth(3).locator('[data-library-param="3"]').inputValue(),'60');
  assert.equal(await selected.nth(3).locator('[data-library-operator]').textContent(),'≥');
  assert.deepEqual(disk('EvtCfg')['7'].condition,expected);assert.deepEqual(errors,[]);assert.equal(saves.length,1);
  await page.screenshot({path:path.join(ready.output,'full-app-condition-reopened.png')});
  const report={status:'passed',flow:'Full production app → workshop story feature → event settings → condition directory → apply → actual HTTP save → full app reload → event settings and condition directory',checks:'Load repairs convertible conditions before UI baseline; native defaults and edits persist; unresolved comparisons and manual notice survive; UP/unknown fields unchanged; one actual save; no page errors',savedCondition:expected,requests:saves.length,errors,evidence:'Actual StudioStore/StudioServer with disposable Mod and Chrome; no native desktop window or Unity game acceptance'};
  fs.writeFileSync(path.join(ready.output,'full-ui-result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(error){fs.writeFileSync(path.join(ready.output,'full-ui-failure.json'),JSON.stringify({error:String(error),errors,body:await page.locator('body').innerText(),state:await page.evaluate(()=>{const S=window.StudentAgeStudioTest?.S;return S?{dirty:S.dirty,saving:S.saving,doc:JSON.parse(StudentAgeIndexedTalks.stringify(S.doc)),saved:StudentAgeIndexedTalks.parse(S.saved),order:S.order,idMappings:S.idMappings}:null;}),saves},null,2));await page.screenshot({path:path.join(ready.output,'full-ui-failure.png')});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
