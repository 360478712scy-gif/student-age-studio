'use strict';
// Actual StudioServer + complete editor against a disposable Mod (STUDIO_TEST_READY).
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const ready=JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_READY,'utf8')),browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],saves=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(request.url().endsWith('/api/save'))saves.push(request.postDataJSON());});
 const disk=()=>JSON.parse(fs.readFileSync(path.join(ready.cfg,'TalkCfg.json'),'utf8'));
 const enter=async()=>{
  await page.waitForFunction(()=>!window.STUDIO_BOOTSTRAPPING&&window.STUDIO_WORKSHOP_NAV?.isOpen());
  await page.locator('#workshop [data-feature="story"]').click();await page.locator('[data-enter-event="7"]').click();
  await page.waitForFunction(()=>!window.StudentAgeStudioTest.S.conditionsLoading);
 };
 try{
  await page.goto(ready.url);await enter();
  await page.locator('[data-action="add-branch"]').click();
  await page.locator('#route-condition-editor [data-condition-library]').click();
  for(const [label,key,id] of [['对话到达','event:3','7249'],['本回合对话','event:30','7300']]){
   await page.locator('.condition-library-search').fill(label);await page.locator('[data-library-key="'+key+'"]').click();
   const card=page.locator('.condition-selected-card').last();
   await card.locator('[data-library-param="2"]').locator('..').locator('.uc-trigger').click();
   await page.locator('.uc-search').fill(id);await page.locator('.uc-option').filter({hasText:'完整流程目标 '+id}).click();
  }
  await page.locator('[data-library-apply]').click();await page.locator('#modal [data-modal-button="0"]').click();
  await page.waitForFunction(()=>Object.values(window.StudentAgeStudioTest.S.branchFolders).some(folder=>folder.kind==='condition'&&folder.routerId===7002));
  const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST'),page.locator('#studio-toolbar [data-nav="save"]').click()]);
  assert.equal(response.status(),200);assert.equal((await response.json()).ok,true);
  await page.waitForFunction(()=>!window.StudentAgeStudioTest.S.dirty&&!window.StudentAgeStudioTest.S.saving);
  const talks=disk(),router=Object.values(talks).find(row=>row.check?.length===2),first=Object.values(talks).find(row=>row.content==='完整流程目标 7249'),second=Object.values(talks).find(row=>row.content==='完整流程目标 7300');
  assert(router);const expected=[[3,3,first.id],[3,30,second.id]];assert.deepEqual(router.check,expected);
  assert.equal(Object.values(talks).filter(row=>row.content?.startsWith('完整流程目标')).length,300);assert.equal(second.future.keep,9);
  await page.reload();await enter();
  await page.locator('[data-condition-id="'+router.id+'"] [data-condition-library]').click();
  const cards=page.locator('.condition-selected-card');assert.equal(await cards.count(),2);
  assert.equal(await cards.nth(0).locator('[data-library-param="2"]').inputValue(),String(first.id));
  assert.equal(await cards.nth(1).locator('[data-library-param="2"]').inputValue(),String(second.id));
  assert.match(await cards.nth(0).textContent(),/完整流程目标 7249/);assert.match(await cards.nth(1).textContent(),/完整流程目标 7300/);
  assert.deepEqual(errors,[]);assert.equal(saves.length,1);
  await page.screenshot({path:path.join(ready.output,'full-app-reopened.png')});
  const report={status:'passed',savedCondition:expected,dialogues:300,saveRequests:saves.length,errors,flow:'Full app → event → add branch → add both dialogue conditions → search unloaded targets → apply → toolbar save → app reload → reopen conditions',evidence:'Actual StudioStore/StudioServer with disposable Mod and Chrome; no Windows native or Unity game acceptance'};
  fs.writeFileSync(path.join(ready.output,'full-ui-result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(error){fs.writeFileSync(path.join(ready.output,'full-ui-failure.json'),JSON.stringify({error:String(error),errors,body:await page.locator('body').innerText(),saves},null,2));await page.screenshot({path:path.join(ready.output,'full-ui-failure.png')});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
