'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const checks=[];
 try{
  async function fixture(initial,{holdFirst=false}={}){
   const page=await browser.newPage(),errors=[],requests={get:0,check:0,download:0};let status=initial;
   const first=deferred();page.on('pageerror',error=>errors.push(error.message));
   const data=value=>({status:value,message:'fixture-'+value,managed:true,currentVersion:'1.0.0',version:'1.0.1',progress:50});
   await page.route('http://studio.test/**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<dialog id="settings"><section id="updates"></section></dialog>'});
    let response;
    if(url.pathname==='/api/updates'&&route.request().method()==='GET'){
     const ordinal=++requests.get;response=data(status);
     if(holdFirst&&ordinal===1)await first.promise;
    }else if(url.pathname==='/api/updates/check'){
     requests.check++;status='checking';response=data(status);
    }else if(url.pathname==='/api/updates/download'){
     requests.download++;status='downloading';response=data(status);
    }else throw Error('Unexpected request: '+url.pathname);
    return route.fulfill({contentType:'application/json',body:JSON.stringify(response)});
   });
   await page.goto('http://studio.test/');
   // Add the component after load, so its separate automatic startup updater
   // does not participate in these panel lifecycle checks.
   await page.addScriptTag({path:path.join(__dirname,'../app-updates.js')});
   await page.evaluate(()=>{document.querySelector('#settings').showModal();window.STUDIO_UPDATES.mount(document.querySelector('#updates'));});
   const deadline=Date.now()+5000;
   while(requests.get<1&&Date.now()<deadline)await page.waitForTimeout(10);
   assert.ok(requests.get>=1,'mount must request its initial state');
   const message=page.locator('#updates [role="status"]');
   return {page,requests,errors,first,message,set:value=>{status=value;},wait:value=>page.waitForFunction(value=>document.querySelector('#updates [role="status"]')?.textContent==='fixture-'+value,value),async finish(){assert.deepEqual(errors,[]);await page.close();}};
  }
  async function staysStopped(f){const count=f.requests.get;await f.page.waitForTimeout(850);assert.equal(f.requests.get,count,'terminal or closed panel must stop polling');}
  for(const terminal of ['available','current','error']){
   const f=await fixture('checking');await f.wait('checking');f.set(terminal);await f.wait(terminal);
   if(terminal==='available')assert.equal(await f.page.locator('[data-update-download]').count(),1);
   else assert.equal(await f.page.locator('[data-update-download],[data-update-restart]').count(),0);
   await staysStopped(f);await f.finish();checks.push('checking -> '+terminal+' updates panel and stops');
  }
  {
   const f=await fixture('checking');await f.wait('checking');f.set('downloading');await f.wait('downloading');
   assert.equal(await f.page.locator('progress').count(),1);f.set('ready');await f.wait('ready');
   assert.equal(await f.page.locator('[data-update-restart]').count(),1);await staysStopped(f);await f.finish();
   checks.push('background checking -> downloading -> ready exposes restart');
  }
  {
   const f=await fixture('idle');await f.wait('idle');await f.page.locator('[data-update-check]').click();await f.wait('checking');
   f.set('available');await f.wait('available');await f.page.locator('[data-update-download]').click();await f.wait('downloading');
   f.set('ready');await f.wait('ready');assert.equal(await f.page.locator('[data-update-restart]').count(),1);
   assert.deepEqual({check:f.requests.check,download:f.requests.download},{check:1,download:1});await staysStopped(f);await f.finish();
   checks.push('manual check returning checking and manual download both poll to completion');
  }
  for(const close of ['dialog','detach']){
   const f=await fixture('checking');await f.wait('checking');
   await f.page.evaluate(close=>close==='dialog'?document.querySelector('#settings').close():document.querySelector('#updates').remove(),close);
   await staysStopped(f);await f.finish();checks.push(close+' stops pending polling before another GET');
  }
  {
   const f=await fixture('checking',{holdFirst:true});
   await f.page.locator('[data-update-check]').click();await f.wait('checking');f.set('available');await f.wait('available');
   f.first.resolve();await f.page.waitForTimeout(100);
   assert.equal(await f.message.textContent(),'fixture-available');assert.equal(await f.page.locator('[data-update-download]').count(),1);
   await staysStopped(f);await f.finish();checks.push('late initial GET cannot overwrite newer button result');
  }
  {
   const f=await fixture('checking',{holdFirst:true});await f.page.locator('[data-update-check]').waitFor();
   await f.page.evaluate(()=>document.querySelector('#updates').remove());f.first.resolve();await staysStopped(f);await f.finish();
   checks.push('late response after panel removal does not restart polling');
  }
  const report={status:'passed',checks,nativeUI:'not run; isolated browser component regression only'};
  console.log(JSON.stringify(report,null,2));
  const index=process.argv.indexOf('--evidence');if(index>=0){const output=path.resolve(process.argv[index+1]);fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');}
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
