'use strict';
// Real StudioServer, full editor, and disposable Mod supplied by STUDIO_TEST_READY.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const ready=JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_READY,'utf8'));
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],saves=[],apiErrors=[],checks=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(request.url().endsWith('/api/save'))saves.push(request.postDataJSON());});
 page.on('response',response=>{if(new URL(response.url()).pathname.startsWith('/api/')&&response.status()>=400)apiErrors.push({url:new URL(response.url()).pathname,status:response.status()});});
 const disk=()=>Object.fromEntries(ready.files.map(file=>[file,crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')]));
 const state=()=>page.evaluate(()=>{const s=StudentAgeStudioTest.S;return {dirty:s.dirty,saved:s.saved,order:[...s.order],selected:s.selected,pinned:{talks:[...s.pinned.talks],events:[...s.pinned.events]},unconnected:s.doc.talks[7003]?.future};});
 const enter=async()=>{await page.waitForFunction(()=>!window.STUDIO_BOOTSTRAPPING&&window.STUDIO_WORKSHOP_NAV?.isOpen());await page.locator('#workshop [data-feature="story"]').click();await page.locator('[data-enter-event="7"]').click();await page.waitForFunction(()=>!StudentAgeStudioTest.S.projectOpening&&!StudentAgeStudioTest.S.conditionsLoading);};
 const add=async()=>{await page.locator('[data-action="add-blank-talk"]').first().click();await page.waitForFunction(()=>StudentAgeStudioTest.S.dirty);};
 const decide=async value=>{await page.waitForSelector('#studio-unsaved[open]');await page.locator('[data-leave="'+value+'"]').click();};
 try{
  await page.goto(ready.url);await enter();
  assert(await page.evaluate(()=>STUDIO_REQUEST_CLOSE.toString().includes('closing:true')),'native close hook must be navigation policy');
  const saved=await state(),original=disk();assert.equal(saved.dirty,false);assert.deepEqual(saved.unconnected,{keep:'saved orphan'});assert.deepEqual(saved.pinned.talks,[7001,7002,7003]);
  await add();const draft=await state();assert(draft.order.length>saved.order.length);
  await page.locator('#studio-toolbar [data-nav="home"]').click();await decide('cancel');assert.equal((await state()).dirty,true);assert((await state()).order.length>saved.order.length);assert.deepEqual(disk(),original);checks.push('home cancel retains the incomplete draft and saved files');
  await page.locator('#studio-toolbar [data-nav="home"]').click();await decide('discard');await page.waitForFunction(()=>StudentAgeWorkshopTest.W.mode==='home');
  const discarded=await state();assert.equal(discarded.dirty,false);assert.deepEqual(discarded.order,saved.order);assert.deepEqual(discarded.pinned,saved.pinned);assert.deepEqual(discarded.unconnected,saved.unconnected);assert.deepEqual(disk(),original);checks.push('home discard exits without saving, retaining saved unconnected content and pinned IDs');
  await enter();await add();
  const cancel=page.evaluate(()=>STUDIO_REQUEST_CLOSE());await decide('cancel');assert.equal(await cancel,false);assert.equal((await state()).dirty,true);assert.deepEqual(disk(),original);checks.push('native close hook cancel denies exit and retains draft');
  const close=page.evaluate(()=>STUDIO_REQUEST_CLOSE());await decide('discard');assert.equal(await close,true);assert.equal((await state()).dirty,false);assert.deepEqual((await state()).pinned,saved.pinned);assert.deepEqual(disk(),original);checks.push('native close hook discard authorizes exit with no save request');
  assert.equal(saves.length,0);assert.deepEqual(errors,[]);assert.deepEqual(apiErrors,[]);
  await page.screenshot({path:path.join(ready.output,'full-ui-discarded.png')});
  const report={status:'passed',checks,saveRequests:saves.length,errors,apiErrors,savedFilesByteIdentical:true,scope:'Actual StudioStore/StudioServer and full editor controls plus the same global close hook invoked by WebView2; browser acceptance, not an OS native window run'};
  fs.writeFileSync(path.join(ready.output,'full-ui-result.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
 }catch(error){fs.writeFileSync(path.join(ready.output,'full-ui-failure.json'),JSON.stringify({error:String(error),errors,apiErrors,saves,body:await page.locator('body').innerText()},null,2)+'\n');await page.screenshot({path:path.join(ready.output,'full-ui-failure.png')});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
