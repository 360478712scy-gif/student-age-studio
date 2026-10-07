'use strict';
// Actual server, complete app and user controls. Incomplete events must persist.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const ready=JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_READY,'utf8')),browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],saves=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/api/save'))saves.push(r.postDataJSON());});
 const enter=async()=>{await page.waitForFunction(()=>!STUDIO_BOOTSTRAPPING&&STUDIO_WORKSHOP_NAV.isOpen());await page.locator('#workshop [data-feature="story"]').click();await page.waitForFunction(()=>!StudentAgeStudioTest.S.conditionsLoading);};
 const save=async()=>{const [r]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST'),page.locator('#studio-toolbar [data-nav="save"]').click()]);assert.equal(r.status(),200);const out=await r.json();assert(out.ok);await page.waitForFunction(()=>!StudentAgeStudioTest.S.dirty&&!StudentAgeStudioTest.S.saving);return out;};
 const events=()=>JSON.parse(fs.readFileSync(path.join(ready.cfg,'EvtCfg.json'),'utf8'));
 try{
  await page.goto(ready.url);await enter();await page.locator('[data-events-create]').first().click();
  await page.locator('#event-title').fill('');await page.locator('#modal [data-modal-button="1"]').click();await page.waitForFunction(()=>!document.querySelector('#modal').open);
  const id=await page.evaluate(()=>StudentAgeStudioTest.S.event);assert(id&&id!==7);await save();assert.equal(events()[id].title,'');
  await page.locator('[data-edit-event="'+id+'"]').click();await page.locator('#event-type').click();await page.locator('[data-event-type-id="110"]').click();await page.locator('[data-event-confirm]').click();
  await page.locator('#event-maxcount').fill('1.5');await page.locator('#event-id').fill('');await page.locator('#modal [data-modal-button="1"]').click();await page.waitForFunction(()=>!document.querySelector('#modal').open);
  const out=await save(),row=events()[id];assert.equal(row.title,'');assert.equal(row.type,110);assert.equal(row.maxcount,1.5);assert.equal(row.studioEventBindingDraft.gifts[0].npc,0);assert.equal(row.studioEventBindingDraft.gifts[0].item,0);
  const original=events()[7];assert.equal(original.future.keep[3],30);
  await page.reload();await enter();await page.locator('[data-edit-event="'+id+'"]').click();assert.equal(await page.locator('#event-title').inputValue(),'');assert.equal(await page.locator('#event-maxcount').inputValue(),'1.5');assert.equal(await page.locator('#event-type').getAttribute('value'),'110');
  const loaded=await page.evaluate(id=>StudentAgeStudioTest.S.doc.events[id],id);assert.deepEqual(loaded.studioEventBindingDraft.gifts,row.studioEventBindingDraft.gifts);assert.deepEqual(errors,[]);assert.equal(saves.length,2);
  await page.screenshot({path:path.join(ready.output,'unfinished-event-reopened.png')});
  const report={status:'passed',eventId:id,saveRequests:saves.length,warnings:out.warnings||[],errors,checks:['unnamed event creates and saves','fractional count preserves authored value','unselected gift target stays in persistent binding draft','unfinished event reopens','unrelated event unknown fields retained'],scope:'Actual StudioServer + full Chrome UI in a disposable Mod; no real Mod or native game writes'};
  fs.writeFileSync(path.join(ready.output,'event-drafts-full-ui-result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(e){fs.writeFileSync(path.join(ready.output,'event-drafts-full-ui-failure.json'),JSON.stringify({error:String(e),errors,saves,body:await page.locator('body').innerText()},null,2));throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
