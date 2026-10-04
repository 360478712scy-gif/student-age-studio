'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage(),errors=[],counts={};let mode='delayed',gameGate=deferred(),cacheGate=deferred(),updateManaged=false,updateStatus='idle';
  const updateState=()=>({status:updateStatus,managed:updateManaged,currentVersion:'1.0.0',currentDisplayVersion:'1.4.9.7',message:'fixture-'+updateStatus,...(updateStatus==='idle'?{}:{version:'1.0.1',displayVersion:'1.4.9.8'})});
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('http://studio.test/**',async route=>{
   const url=new URL(route.request().url()),name=url.pathname.slice('/api/'.length);
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<header class="app-header"></header><script>window.STUDIO_BOOTSTRAPPING=true</script>'});
   if(!url.pathname.startsWith('/api/'))return route.fulfill({status:404,body:''});
   const ordinal=counts[name]=(counts[name]||0)+1,requestMode=mode;
   if(requestMode==='delayed'&&name==='game-locations')await gameGate.promise;
   if(requestMode==='delayed'&&name==='cache-settings')await cacheGate.promise;
   if(requestMode==='error'&&name==='game-locations')return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'模拟设置接口暂时不可用'})});
   if(name==='updates/check'){assert.equal(route.request().method(),'POST');updateStatus='available';}
   if(name==='updates/download'){assert.equal(route.request().method(),'POST');updateStatus='ready';}
   const payload={
    'game-locations':{status:'idle',managed:true,modsStatus:{path:'fixture-mods-'+ordinal},workshopStatus:{},storage:{},backups:{},installations:[]},
    'cache-settings':{path:'fixture-cache',required:false},'asset-folders':{revision:1,folders:{}},
    'project-preferences':{ignoredProjectIds:[],projects:[],defaultProjectId:''},
    'ai-tools':{prompt:'',claudeCode:'',json:{},codex:'',cliExample:''},
    'display-settings':{idCheckExcludedProjects:[]},projects:[],updates:updateState(),
    'updates/check':updateState(),'updates/download':updateState(),
   }[name];
   assert.notEqual(payload,undefined,'Unexpected request: '+name);
   return route.fulfill({contentType:'application/json',body:JSON.stringify(payload)});
  });
  await page.goto('http://studio.test/');
  await page.addScriptTag({path:path.join(__dirname,'../app-updates.js')});
  await page.addScriptTag({path:path.join(__dirname,'../locations.js')});
  const dialog=page.locator('#game-locations');
  const click=()=>page.evaluate(()=>document.querySelector('#game-location-button').click());
  const panelReads=['asset-folders','project-preferences','ai-tools','display-settings','projects','updates'];
  const updates=dialog.locator('.location-section[data-settings-group="about"]').first();
  const openAbout=()=>dialog.locator('[data-settings-tab="about"]').click();
  const assertUpdatePanel=async()=>{
   await updates.getByRole('heading',{name:'版本更新',exact:true}).waitFor({state:'visible'});
   await updates.getByText(/当前版本：1\.4\.9\.7/).waitFor({state:'visible'});
   assert.match(await updates.textContent(),/当前版本：1\.4\.9\.7/);
   assert.equal(await updates.locator('[data-update-check]').isVisible(),true,'the settings update panel must remain usable');
  };
  // Observe requests and rendered state instead of assuming a network delay or
  // accessing the application's private closure variables.
  const waitRequests=async(name,count)=>{const deadline=Date.now()+5000;while((counts[name]||0)<count&&Date.now()<deadline)await new Promise(done=>setTimeout(done,10));assert(counts[name]>=count,name+' did not reach '+count);};

  // A slow backend must not delay showing a closable settings window. Repeated
  // clicks share the two outstanding reads, and closing prevents a late reopen.
  await click();assert.equal(await dialog.evaluate(node=>node.open),true);
  assert.match(await dialog.locator('[data-notice]').textContent(),/正在读取/);
  assert.equal(await dialog.locator('[data-close]').isEnabled(),true);
  await waitRequests('game-locations',1);await waitRequests('cache-settings',1);
  await click();await click();assert.equal(counts['game-locations'],1);assert.equal(counts['cache-settings'],1);
  await dialog.locator('[data-close]').click();gameGate.resolve();cacheGate.resolve();
  await page.waitForFunction(()=>window.STUDIO_MODS_STATUS?.path==='fixture-mods-1');
  assert.equal(await dialog.evaluate(node=>node.open),false);assert.equal(await dialog.locator('.location-section').count(),0);
  assert.equal(counts['project-preferences']||0,0,'closed load must not mount settings panels');

  // Each successful refresh renders one time, even when settings are already
  // open. A panel's own API read is a reliable observable render count.
  mode='immediate';await click();await waitRequests('project-preferences',1);
  await page.waitForFunction(()=>document.querySelectorAll('#game-locations [data-settings-tab]').length===5);
  assert.equal(await dialog.evaluate(node=>node.open),true);
  for(const name of panelReads){await waitRequests(name,1);assert.equal(counts[name],1,name+' should mount once');}
  // Mount through the real settings render, where the update section is built
  // before the settings body is attached. Source previews still show a panel.
  await openAbout();await assertUpdatePanel();
  assert.match(await updates.textContent(),/当前为源码预览/);
  assert.equal(await updates.locator('[data-update-download],[data-update-restart]').count(),0);
  updateManaged=true;
  await click();await waitRequests('project-preferences',2);await page.waitForFunction(()=>window.STUDIO_MODS_STATUS?.path==='fixture-mods-3');
  for(const name of panelReads){await waitRequests(name,2);assert.equal(counts[name],2,name+' should mount once on refresh');}
  await openAbout();await assertUpdatePanel();
  await updates.locator('[data-update-check]').click();
  await updates.locator('[data-update-download]').waitFor({state:'visible'});
  assert.equal(counts['updates/check'],1);
  await updates.locator('[data-update-download]').click();
  await updates.locator('[data-update-restart]').waitFor({state:'visible'});
  assert.equal(counts['updates/download'],1);
  await dialog.locator('[data-settings-tab="directories"]').click();
  assert.equal(await updates.isVisible(),false);
  await openAbout();await assertUpdatePanel();
  assert.equal(await updates.locator('[data-update-restart]').isVisible(),true);
  assert.equal(counts.updates,2,'changing tabs must not remount or reread updates');

  // Keep the previous settings usable while reloading. A response that arrives
  // after closing still updates the cache without creating another panel set.
  mode='delayed';gameGate=deferred();cacheGate=deferred();await click();await waitRequests('game-locations',4);
  assert.equal(await dialog.locator('[data-current-mods]').textContent(),'fixture-mods-3');
  await dialog.locator('[data-close]').click();gameGate.resolve();cacheGate.resolve();
  await page.waitForFunction(()=>window.STUDIO_MODS_STATUS?.path==='fixture-mods-4');
  assert.equal(await dialog.evaluate(node=>node.open),false);assert.equal(counts['project-preferences'],2);

  // A failed read remains visible and closable, and retry succeeds in the same
  // window instead of requiring a reload or losing the cached settings.
  mode='error';await click();await page.waitForFunction(()=>document.querySelector('#game-locations [data-settings-retry]')?.hidden===false);
  assert.match(await dialog.locator('[data-notice]').textContent(),/模拟设置接口暂时不可用/);
  assert.equal(await dialog.locator('[data-close]').isEnabled(),true);
  mode='immediate';await dialog.locator('[data-settings-retry]').click();await waitRequests('project-preferences',3);
  await page.waitForFunction(()=>window.STUDIO_MODS_STATUS?.path==='fixture-mods-6');
  assert.equal(await dialog.locator('[data-settings-retry]').count(),0);
  assert.equal(await dialog.locator('[data-current-mods]').textContent(),'fixture-mods-6');
  for(const name of panelReads){await waitRequests(name,3);assert.equal(counts[name],3,name+' should mount once after retry');}
  await openAbout();await assertUpdatePanel();
  assert.equal(await updates.locator('[data-update-restart]').isVisible(),true);
  await dialog.locator('[data-close]').click();await click();await waitRequests('project-preferences',4);
  for(const name of panelReads){await waitRequests(name,4);assert.equal(counts[name],4,name+' should mount once after reopening');}
  await openAbout();await assertUpdatePanel();
  assert.equal(await updates.locator('[data-update-restart]').isVisible(),true,'a ready update must remain visible after settings reopen');
  assert.equal(counts['updates/check'],1);assert.equal(counts['updates/download'],1);
  assert.deepEqual(errors,[]);
  const report={status:'passed',checks:'immediate closable loading, pending click coalescing, one render per refresh, no late reopen, cached settings retained, visible failure and retry, real settings update panel in source and managed modes, check/download/ready, tab switch and reopen',requests:counts,nativeUI:'not run; browser settings integration regression only'};
  console.log(JSON.stringify(report,null,2));
  const index=process.argv.indexOf('--evidence');if(index>=0){const output=path.resolve(process.argv[index+1]);fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');}
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
