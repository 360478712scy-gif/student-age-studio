const {chromium}=require(process.env.PLAYWRIGHT_MODULE),fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
 const out=path.join(__dirname,'../../output/pr3-review/ui');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const results={checks:[],errors:[]};
 const inspect=async(page,selector)=>page.locator(selector).evaluate(el=>{
  const keys=['background','background-color','background-image','opacity','backdrop-filter','-webkit-backdrop-filter','color','border','box-shadow'];
  const safe=v=>v?.replace(/data:image\/[^;)]+;base64,[A-Za-z0-9+/=]+/g,'data:image/[omitted]');
  const state=e=>({tag:e.tagName,id:e.id,classes:e.className,inline:safe(e.getAttribute('style')),style:Object.fromEntries(keys.map(k=>[k,safe(getComputedStyle(e).getPropertyValue(k))]))});
  const rules=[];const walk=(list,sheet,context=[])=>{for(const r of list){if(r.selectorText){try{if(el.matches(r.selectorText)&&keys.some(k=>r.style?.getPropertyValue(k)))rules.push({sheet,context,selector:r.selectorText,style:Object.fromEntries(keys.filter(k=>r.style.getPropertyValue(k)).map(k=>[k,r.style.getPropertyValue(k)]))});}catch{}}else if(r.cssRules)walk(r.cssRules,sheet,[...context,r.conditionText||r.name||r.constructor.name]);}};
  for(const s of document.styleSheets)try{walk(s.cssRules,s.href||s.ownerNode?.id||'inline');}catch{}
  return {element:state(el),parents:[el.parentElement,document.body,document.documentElement].filter(Boolean).map(state),rules};
 });
 try{
  const page=await browser.newPage({viewport:{width:1366,height:900}});page.on('pageerror',e=>results.errors.push(e.message));
  await page.goto(JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_READY)).url);
  await page.waitForFunction(()=>window.STUDIO_EVENTS&&window.StudentAgeGoals&&window.STUDIO_SAVE_REVIEW&&window.StudentAgeStudioTest);
  await page.locator('#studio-onboarding').waitFor({state:'hidden',timeout:45000});
  await page.evaluate(()=>{
   const doc={events:{901001:{id:901001,title:'共同对白的事件',talkId:[901001001]},901002:{id:901002,title:'继续保留的事件',talkId:[901001001]}},talks:{901001001:{id:901001001,content:'这是共同使用的对白',nextTalk:[]}},options:{},persons:{}};
   window.STUDIO_EVENT_CONTEXT=()=>({project:{id:'ui-review',name:'PR 3 界面检查'},doc,currentEvent:901001});STUDIO_EVENTS.open();
  });
  for(const theme of ['glass','glass-dusk','glass-moon']){
   await page.evaluate(t=>STUDIO_SET_THEME(t),theme);await page.locator('[data-delete-event="901001"]').click();
   assert.equal(await page.locator('dialog[open]').count(),1);assert(await page.locator('[data-event-delete-cancel]').evaluate(e=>e===document.activeElement));
   assert((await page.locator('dialog[open]').innerText()).includes('其他事件共用的对话和选项会保留'));
   if(theme==='glass-moon')results.deleteStyles={dialog:await inspect(page,'dialog[open]'),button:await inspect(page,'[data-event-delete-cancel]')};
   await page.screenshot({path:path.join(out,`delete-${theme}.png`)});await page.keyboard.press('Enter');assert.equal(await page.locator('dialog[open]').count(),0);
  }
  results.checks.push('Event delete: existing dialog, shared-line wording, cancel focused; Enter cancels in all three themes');
  await page.evaluate(()=>{window.pr3SaveResult='pending';STUDIO_SAVE_REVIEW.retry({warnings:['未选择人物立绘']},'/unused',{},()=>{window.pr3SaveResult='saved';}).catch(e=>window.pr3SaveResult=e.code);});
  await page.locator('.save-review-dialog[open]').waitFor();assert(await page.locator('[data-review-cancel]').evaluate(e=>e===document.activeElement&&e.classList.contains('primary')));
  results.saveStyles={dialog:await inspect(page,'.save-review-dialog[open]'),button:await inspect(page,'[data-review-cancel]')};
  await page.waitForTimeout(800);
  results.saveStyles.settledDialog=await inspect(page,'.save-review-dialog[open]');results.saveStyles.settledButton=await inspect(page,'[data-review-cancel]');
  await page.screenshot({path:path.join(out,'save-review-settled.png')});
  fs.writeFileSync(path.join(out,'computed-styles.json'),JSON.stringify({delete:results.deleteStyles,save:results.saveStyles},null,2));delete results.deleteStyles;delete results.saveStyles;
  if(process.env.PR3_CSS_ONLY)return;
  await page.screenshot({path:path.join(out,'save-review.png')});await page.keyboard.press('Enter');await page.waitForFunction(()=>window.pr3SaveResult==='save_cancelled');
  results.checks.push('Save warning: Return to edit is primary/focused and Enter cancels');
  await page.evaluate(async()=>{
   STUDIO_EVENTS.close();const host=document.createElement('section');host.id='pr3-goal-review';host.style.cssText='position:fixed;inset:64px 0 0;z-index:1000;background:var(--bg);overflow:auto';document.body.append(host);
   const goal={id:1234567,name:'目标编辑检查',desc:'检查错误提示与图片导入',npc:0,finishType:0,round:0,weight:1,group:999,demand:[],condition:[],reward:[],futureParameters:[1,2]};
   window.pr3Goal=StudentAgeGoals.create(host,{project:{id:'ui-review'},token:STUDIO_TOKEN,info:{commands:{}},status:()=>{},onState:()=>{},api:async(url,data)=>{
    if(url.startsWith('/api/goals?'))return {revision:'test',goals:{localRows:{1234567:goal},rows:{1234567:goal},referenceRows:{},localIds:['1234567'],schema:{fields:[]}},people:{rows:{},localRows:{},referenceRows:{},localIds:[]},images:{}};
    if(url.startsWith('/api/table?'))return {rows:{},localIds:[]};
    if(url==='/api/goal-ui')return {sprites:{}};
    if(url==='/api/image-normalize'){const r=await fetch(url,{method:'POST',headers:{'X-Studio-Token':STUDIO_TOKEN,'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error);return v;}
    throw Error('Unexpected UI review request: '+url);
   }});await pr3Goal.load();
  });
  await page.locator('[data-goal-tab="advanced"]').click();const json=page.locator('[data-goal-json="futureParameters"]');await json.fill('[broken');await page.locator('[data-goal-save]').click();
  assert(await json.evaluate(e=>e===document.activeElement&&e.getAttribute('aria-invalid')==='true'));await page.screenshot({path:path.join(out,'goal-invalid-focus.png')});await json.fill('[1,2]');assert.equal(await json.getAttribute('aria-invalid'),null);
  await page.locator('[data-goal-tab="basic"]').click();await page.locator('[data-goal-field="round"]').fill('-1');await page.locator('[data-goal-save]').click();assert(await page.locator('[data-goal-field="round"]').evaluate(e=>e===document.activeElement));await page.locator('[data-goal-field="round"]').fill('0');
  results.checks.push('Goal save: malformed extension JSON and negative round focus correct fields; corrected JSON clears error');
  await page.evaluate(()=>STUDIO_IDS.configure({tables:{}}));await page.locator('[data-goal-action="image"]').click();
  const chooser=page.waitForEvent('filechooser');await page.locator('[data-image-add]').click();const file=await chooser;
  // Uncompressed top-origin 2x2 RGB TGA, intentionally not browser-decodable.
  const header=Buffer.alloc(18);header[2]=2;header.writeUInt16LE(2,12);header.writeUInt16LE(2,14);header[16]=24;header[17]=32;
  await file.setFiles({name:'preview-check.tga',mimeType:'image/x-tga',buffer:Buffer.concat([header,Buffer.from([40,140,220,40,140,220,40,140,220,40,140,220])])});
  await page.locator('.goal-image-library').waitFor({state:'detached'});await page.waitForFunction(()=>{const img=document.querySelector('.goal-image-select img');return img?.src.startsWith('data:image/png;base64,')&&img.complete&&img.naturalWidth===2;});
  const goalSnapshot=JSON.parse(await page.evaluate(()=>pr3Goal.snapshot()));assert.equal(goalSnapshot.pending.length,1);await page.screenshot({path:path.join(out,'goal-tga-preview.png')});
  results.checks.push('Goal TGA: real normalization API returns PNG and draft preview decodes before save');
  await page.evaluate(()=>{pr3Goal.destroy();document.getElementById('pr3-goal-review').remove();document.documentElement.classList.remove('game-ui-ready');});
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==','base64');let fail=true,metadataRequests=0;
  await page.route('**/api/preview-ui*',async route=>{const resource=new URL(route.request().url()).searchParams.get('resource');if(!resource){metadataRequests++;return route.fulfill({json:{files:['name-male.png','dialogue-male.png'],colors:{male:['#f9f3df','#181818','#dad3c0','#181818'],female:['#f9f3df','#181818','#dad3c0','#181818']}}});}if(resource==='name-male.png'&&fail)return route.abort();if(resource.endsWith('.png'))return route.fulfill({contentType:'image/png',body:png});return route.fulfill({status:404});});
  await page.addScriptTag({url:new URL('/preview-ui.js',page.url()).href});
  await page.evaluate(async()=>{await StudentAgePreviewUI.load();const scene=document.createElement('div');scene.id='pr3-fallback';scene.className='story-scene';scene.innerHTML='<div class="scene-dialogue"><button class="scene-speaker-name">人物</button></div><div class="story-history-line"><div class="story-history-text"><strong>人物</strong>历史对白</div></div>';document.body.append(scene);});
  assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('game-ui-ready')),false);
  const colors=await page.locator('#pr3-fallback').evaluate(e=>[...e.querySelectorAll('.scene-speaker-name,.story-history-text')].map(n=>getComputedStyle(n).backgroundColor));assert(colors.every(c=>c!=='rgba(0, 0, 0, 0)'));
  fail=false;await page.evaluate(()=>StudentAgePreviewUI.load());assert(metadataRequests>=2);assert(await page.evaluate(()=>document.documentElement.classList.contains('game-ui-ready')));
  results.checks.push('Preview partial failure: fallback name/history backgrounds remain; subsequent call retries and enables native styling after success');
  assert.deepEqual(results.errors,[]);results.passed=true;fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
