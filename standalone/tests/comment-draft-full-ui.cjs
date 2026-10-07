'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const ready=JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_READY,'utf8')),browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const enter=async()=>{await page.waitForFunction(()=>!STUDIO_BOOTSTRAPPING&&STUDIO_WORKSHOP_NAV.isOpen());await page.locator('#workshop [data-feature="posts"]').click();await page.locator('[data-social="comment"]').waitFor();};
 try{
  await page.goto(ready.url);await enter();await page.locator('[data-social="comment"]').click();await page.locator('[data-social-account="3"]').click();
  await page.locator('#social-comment-draft').fill('未完成等待时间仍要保存');await page.locator('#social-comment-delay').fill('-3');
  await page.locator('[data-social-compose-submit]').click();
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/social-save')&&r.request().method()==='POST');
  await page.locator('#studio-toolbar [data-nav="save"]').click();const response=await pending;assert.equal(response.status(),200);const result=await response.json();assert(result.warnings?.length);await page.waitForFunction(()=>!STUDIO_WORKSHOP_NAV.dirty());
  const posts=JSON.parse(fs.readFileSync(path.join(ready.cfg,'KZoneContentCfg.json'))),comments=JSON.parse(fs.readFileSync(path.join(ready.cfg,'KZoneCommentCfg.json')));const id=posts[101].comments[0][0];assert.equal(posts[101].comments[0][1],-3);assert.equal(comments[id].content,'未完成等待时间仍要保存');
  await page.reload();await enter();await page.locator('[data-comment-card="'+id+'"] .social-comment-text').click();assert.equal(await page.locator('[data-social-comment-delay]').inputValue(),'-3');assert.equal(await page.locator('#social-current-comment').inputValue(),'未完成等待时间仍要保存');assert.equal(await page.locator('.save-review-dialog[open]').count(),0);assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(ready.output,'comment-negative-delay-reopened.png')});const report={status:'passed',commentId:id,warnings:result.warnings,errors,checks:['compose applies negative delay and toolbar saves','real server persists negative value with warning','reload retains content and delay','no confirmation dialog'],scope:'Actual isolated StudioServer and full editor in Chrome, not OS-native acceptance'};fs.writeFileSync(path.join(ready.output,'result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(e){fs.writeFileSync(path.join(ready.output,'failure.json'),JSON.stringify({error:String(e),errors,body:await page.locator('body').innerText()},null,2));throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
