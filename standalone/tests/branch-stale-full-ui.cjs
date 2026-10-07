'use strict';
// Actual StudioServer and complete app. Only disposable STUDIO_TEST_READY data is edited.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const ready=JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_READY,'utf8'));
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 const disk=()=>JSON.parse(fs.readFileSync(path.join(ready.cfg,'TalkCfg.json'),'utf8'));
 const state=()=>JSON.parse(fs.readFileSync(path.join(ready.cfg,'../../StudentAgeStudio/editor-state.json'),'utf8'));
 const enter=async()=>{
  await page.waitForFunction(()=>!window.STUDIO_BOOTSTRAPPING&&window.STUDIO_WORKSHOP_NAV?.isOpen());
  await page.locator('#workshop [data-feature="story"]').click();await page.locator('[data-enter-event="7"]').click();
  await page.waitForFunction(()=>!window.StudentAgeStudioTest.S.conditionsLoading);
 };
 const add=async()=>{
  await page.locator('#talk-list .talk-card').filter({hasText:'分支残留完整流程开始'}).click();
  await page.locator('[data-action="add-branch"]').click();
  await page.locator('#modal [data-modal-button="0"]').click();
  await page.waitForFunction(()=>Object.values(window.StudentAgeStudioTest.S.branchFolders).some(f=>f.kind==='condition'));
 };
 const save=async()=>{
  const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/save')&&r.request().method()==='POST'),page.locator('#studio-toolbar [data-nav="save"]').click()]);
  assert.equal(response.status(),200);assert.equal((await response.json()).ok,true);
  await page.waitForFunction(()=>!window.StudentAgeStudioTest.S.dirty&&!window.StudentAgeStudioTest.S.saving);
 };
 const assertBody=()=>assert.ok(Object.values(disk()).find(row=>row.content==='保留完整流程正文'&&row.future.keep===9));
 try{
  await page.goto(ready.url);await enter();await add();await save();
  let folder=Object.values(state().branchFolders)[0],talks=disk();assert(folder);
  // Simulate the native editor: remove the unfinished router and restore its
  // parent's actual route, leaving the old Studio sidecar exactly as it was.
  delete talks[folder.routerId];talks[folder.parentTalkId].nextTalk=folder.baseNext;
  fs.writeFileSync(path.join(ready.cfg,'TalkCfg.json'),JSON.stringify(talks,null,2));
  await page.reload();await enter();
  assert.equal(await page.locator('[data-action="delete-branch"]').count(),0);
  assert.deepEqual(await page.evaluate(()=>window.StudentAgeStudioTest.S.branchFolders),{});assertBody();
  await add();await page.locator('[data-action="delete-branch"]').click();
  assert.deepEqual(await page.evaluate(()=>window.StudentAgeStudioTest.S.branchFolders),{});
  await page.locator('#scene-dialogue-content').fill('分支残留完整流程开始 · 外部删除后保存');
  await save();assert.deepEqual(state().branchFolders,{});assertBody();
  await add();await save();const oldFolders=state().branchFolders;folder=Object.values(oldFolders)[0];talks=disk();
  talks[folder.routerId].content='原版编辑器把连接句改成了正文';
  talks[folder.routerId].effect=[[1163,8,1]];
  fs.writeFileSync(path.join(ready.cfg,'TalkCfg.json'),JSON.stringify(talks,null,2));
  await page.reload();await enter();
  assert.deepEqual(await page.evaluate(()=>window.StudentAgeStudioTest.S.branchFolders),{});
  assert.equal(await page.locator('#talk-list .talk-card').filter({hasText:'原版编辑器把连接句改成了正文'}).count(),1);
  await add();await page.locator('[data-action="delete-branch"]').click();
  await page.locator('#scene-dialogue-content').fill('分支残留完整流程开始 · helper 正文保留后保存');
  // A historical draft may restore old ownership after the helper has become a
  // regular line. The production save button must release it before touching content.
  await page.evaluate(folders=>{const S=window.StudentAgeStudioTest.S;S.branchFolders=folders;S.activeFolder=Object.keys(folders)[0];},oldFolders);
  await save();assert.deepEqual(await page.evaluate(()=>window.StudentAgeStudioTest.S.branchFolders),{});
  assert.equal(await page.evaluate(()=>window.StudentAgeStudioTest.S.activeFolder),null);
  const body=Object.values(disk()).find(row=>row.content==='原版编辑器把连接句改成了正文');
  assert(body);assert.deepEqual(body.effect,[[1163,8,1]]);assertBody();assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(ready.output,'branch-stale-reopened.png')});
  const result={status:'passed',flow:'Full app creates unfinished branch → actual save → native row deletion with stale sidecar → reload → recreate/delete/save; repurposed helper prose/effect → reload → save without loss',errors,evidence:'Chrome + actual StudioStore/StudioServer, disposable Mod; external native edits simulated by changing the real TalkCfg file'};
  fs.writeFileSync(path.join(ready.output,'branch-stale-full-ui-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(error){fs.writeFileSync(path.join(ready.output,'branch-stale-full-ui-failure.json'),JSON.stringify({error:String(error),errors,body:await page.locator('body').innerText()},null,2));await page.screenshot({path:path.join(ready.output,'branch-stale-full-ui-failure.png')});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
