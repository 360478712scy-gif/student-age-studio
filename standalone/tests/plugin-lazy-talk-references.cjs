'use strict';
// Complete production plugin workbench in Chrome, disposable HTTP responses only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),copy=value=>JSON.parse(JSON.stringify(value)),size=500000;
(async()=>{const browser=await chromium.launch({executablePath:process.env.CHROME_PATH,headless:true});try{
 const page=await browser.newPage({viewport:{width:1500,height:1050}}),errors=[],requests=[],submitted=[];page.on('pageerror',error=>errors.push(error.message));
 const project={id:'local:plugin-lazy-qa',name:'小游戏保存隔离验证'};
 let revision='r1',failReference=false,delayReference=false,releaseReference;
 const levels=Array.from({length:5},(_,index)=>({id:12345601+index,needRelation:1,cost:1.2,startTalk:11,winTalk:12,loseTalk:700001,effect:[[5,2]],future:{keep:'stage '+index}}));
 const data={revision,readOnly:false,enabled:['studio.studentage.campusuno'],groups:[{id:123456,template:9102,name:'自建五子棋',levels,tuning:{'Gomoku.Win1':.6},future:{keep:'group'}}],builtin:[{id:9102,template:9102,name:'原版五子棋',levels:[{...levels[0],id:910201}],tuning:{'Gomoku.Win1':.5},future:{keep:'builtin'}}],catalog:{stages:Object.fromEntries(levels.map((row,index)=>[910201+index,{...row,id:910201+index}])),games:{9102:{name:'五子棋'}},settings:[{section:'Gomoku',key:'Win1',desc:'第一关胜率',min:0,max:1,integer:false,default:.5}]},sections:{9102:'Gomoku'}};
 // The reference endpoint really returns a half-million dialogue directory.
 // It is created only when an explicit picker asks for it, never on load/save.
 let talkRows=null;function references(){if(!talkRows){talkRows={};for(let id=1;id<=size;id++)talkRows[id]={id,content:id===499999?'指定的末页对话':id===11?'已有入口摘要':id===12?'胜利入口摘要':'测试对话 '+id};}return talkRows;}
 await page.route('http://studio.test/**',async route=>{const request=route.request(),url=new URL(request.url());requests.push({method:request.method(),path:url.pathname,name:url.searchParams.get('name'),names:url.searchParams.get('names')});
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!DOCTYPE html><html lang="zh-CN"><body><button id="save">保存</button><p id="status"></p><main id="plugin"></main></body></html>'});
  if(url.pathname==='/api/plugins'){
   if(request.method()==='POST'){const payload=request.postDataJSON();assert.equal(payload.revision,revision);submitted.push(copy(payload));if(payload.groups)data.groups=copy(payload.groups);if(payload.enabled)data.enabled=copy(payload.enabled);if(payload.builtin){const index=data.builtin.findIndex(group=>group.id===payload.builtin.id);data.builtin[index]=copy(payload.builtin);}revision+='x';}
   return route.fulfill({json:{...data,revision}});
  }
  if(url.pathname==='/api/table'){assert.notEqual(url.searchParams.get('name'),'TalkCfg','plugin must use the lightweight reference endpoint');return route.fulfill({json:{rows:{},revision}});}
  if(url.pathname==='/api/command-references'){
   assert.equal(url.searchParams.get('names'),'TalkCfg');
   if(delayReference){await new Promise(resolve=>releaseReference=resolve);delayReference=false;}
   if(failReference){failReference=false;return route.fulfill({json:{revision,tables:{TalkCfg:{rows:{}}},errors:{TalkCfg:'模拟目录读取失败'}}});}
   return route.fulfill({json:{revision,tables:{TalkCfg:{rows:references(),localIds:['11','12']}},errors:{}}});
  }
  return route.fulfill({status:404,json:{error:'unexpected '+url.pathname}});
 });
 await page.goto('http://studio.test/');for(const file of ['styles.css','characters.css','plugin-mode.css'])await page.addStyleTag({path:path.join(root,file)});
 for(const file of ['remote-talks.js','search.js','plugin-mode.js'])await page.addScriptTag({path:path.join(root,file)});
 await page.evaluate(project=>{
  const summaries={11:{record:{id:11},fields:['id','content'],excerpt:'已有入口摘要',hasText:true},12:{record:{id:12},fields:['id','content'],excerpt:'胜利入口摘要',hasText:true}};
  window.qaRemote=StudentAgeRemoteTalks.create({version:1,generation:'plugin-qa',ids:['11','12'],summaries},()=>{throw Error('bound labels must not load dialogue bodies');},'r1');
  window.STUDIO_PICKER_CONTEXT=()=>({project,doc:{talks:qaRemote}});
  async function api(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined}),result=await response.json();if(!response.ok)throw Error(result.error);return result;}
  window.qaSaved=0;window.qaEditor=StudentAgePluginMode.create(document.querySelector('#plugin'),{api,project,selected:123456,nativeGames:[],status(message){document.querySelector('#status').textContent=message;},onState(value){document.querySelector('#save').disabled=!!value.busy;},onSaved(){qaSaved++;}});document.querySelector('#save').onclick=()=>qaEditor.save();
 },project);
 const referenceRequests=()=>requests.filter(request=>request.path==='/api/command-references').length;
 await page.evaluate(()=>qaEditor.load());assert.equal(referenceRequests(),0);assert.equal(await page.locator('#plugin select option').count(),0);assert.equal(await page.locator('[data-talk-level]').count(),15);assert.match(await page.locator('[data-talk-level="0"][data-talk-key="startTalk"]').textContent(),/11.*已有入口摘要/);assert.match(await page.locator('[data-talk-level="0"][data-talk-key="loseTalk"]').textContent(),/700001/);assert.equal(await page.evaluate(()=>StudentAgeRemoteTalks.stats(qaRemote).loaded),0);
 await page.fill('[data-level="0"][data-key="cost"]','2.5');await page.click('#save');await page.waitForFunction(()=>qaSaved===1);assert.equal(referenceRequests(),0);assert.equal(data.groups[0].levels[0].cost,2.5);assert.equal(data.groups[0].levels[0].loseTalk,700001);assert.deepEqual(data.groups[0].future,{keep:'group'});assert.deepEqual(data.groups[0].levels[0].future,{keep:'stage 0'});assert.deepEqual(data.groups[0].levels[0].effect,[[5,2]]);assert.equal(await page.locator('#plugin select option').count(),0);
 // An explicit failed read must keep bindings and remain retryable.
 failReference=true;await page.click('[data-talk-level="0"][data-talk-key="startTalk"]');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('模拟目录读取失败'));assert.equal(await page.locator('dialog[open]').count(),0);assert.equal(JSON.parse(await page.evaluate(()=>qaEditor.snapshot())).groups[0].levels[0].startTalk,11);
 await page.click('[data-talk-level="0"][data-talk-key="startTalk"]');await page.waitForSelector('[data-talk-choice="80"]');assert.equal(referenceRequests(),2);assert.equal(await page.locator('[data-talk-rows] [data-talk-choice]').count(),80);assert.match(await page.locator('[data-talk-count]').textContent(),/500000.*6250/);await page.click('[data-talk-page="1"]');await page.waitForSelector('[data-talk-choice="81"]');assert.equal(await page.locator('[data-talk-rows] [data-talk-choice]').count(),80);
 await page.fill('[data-talk-search]','499999');await page.waitForSelector('[data-talk-choice="499999"]');assert.equal(await page.locator('[data-talk-rows] [data-talk-choice]').count(),1);await page.click('[data-talk-choice="499999"]');await page.click('#save');await page.waitForFunction(()=>qaSaved===2);assert.equal(referenceRequests(),2);assert.equal(data.groups[0].levels[0].startTalk,499999);assert.equal(data.groups[0].levels[0].loseTalk,700001);assert.deepEqual(data.groups[0].levels[0].future,{keep:'stage 0'});assert.equal(await page.locator('#plugin select option').count(),0);
 // Native/builtin overrides use the same save path without rescanning references.
 await page.click('[data-group="9102"]');await page.fill('[data-level="0"][data-key="needRelation"]','3');await page.click('#save');await page.waitForFunction(()=>qaSaved===3);assert.equal(data.builtin[0].levels[0].needRelation,3);assert.deepEqual(data.builtin[0].future,{keep:'builtin'});assert.equal(referenceRequests(),2);
 // Reload invalidates reference cache; closing during a delayed request never reopens it.
 await page.evaluate(()=>qaEditor.load());delayReference=true;await page.click('[data-talk-level="0"][data-talk-key="winTalk"]');await page.waitForSelector('[data-talk-rows]');await page.waitForFunction(()=>document.querySelector('[data-talk-search]').disabled);while(!releaseReference)await new Promise(resolve=>setTimeout(resolve,10));await page.click('[data-talk-cancel]');releaseReference();await page.waitForTimeout(100);assert.equal(await page.locator('dialog[open]').count(),0);assert.equal(data.builtin[0].levels[0].winTalk,12);
 // Read-only controls stay disabled and retain original bindings.
 data.readOnly=true;await page.evaluate(()=>qaEditor.load());assert.equal(await page.locator('[data-talk-level]:enabled').count(),0);assert.equal(await page.locator('#plugin select option').count(),0);assert.deepEqual(errors,[]);
 const report={status:'passed',referenceDirectorySize:size,checks:'Open/parameter/custom and builtin save without TalkCfg prefetch or native options; unloaded summary and missing binding IDs; unknown group/stage/effect fields retained; reference errors remain retryable; explicit directory uses 80-row pagination and searches/selects/saves arbitrary Talk; late response after close does not reopen; read-only controls preserved',referenceRequests:referenceRequests(),editableTalkRequests:requests.filter(request=>request.path==='/api/table'&&request.name==='TalkCfg').length,submitted,requests};console.log(JSON.stringify(report,null,2));
 if(process.env.UI_SCREENSHOT){fs.mkdirSync(process.env.UI_SCREENSHOT,{recursive:true});fs.writeFileSync(path.join(process.env.UI_SCREENSHOT,'plugin-lazy-talk-references.json'),JSON.stringify(report,null,2)+'\n');await page.screenshot({path:path.join(process.env.UI_SCREENSHOT,'plugin-lazy-talk-references.png')});}
 }finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
