'use strict';
// Exercise the editor's real choice markup, existing search popup and change
// handlers with a large synthetic mod. Never open or save a user's project.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const section=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end));
const Timeline=require('../timeline.js'),Branches=require('../branches.js');

// Creating named options, including the conditions shortcut, is one undoable edit.
{
 const S={selected:1,doc:{talks:{1:{id:1,option:[]}},options:{}},branchFolders:{},folderOpen:{}};
 let edits=0,closed=0,actions=[],settings=[],next=100,input='自定义选择',allowed=true;
 const c={S,Timeline,Branches,ids:v=>Array.isArray(v)?v.map(Number):[],talk:()=>S.doc.talks[S.selected],editable:()=>allowed,toast:()=>{},setTimeout:()=>{},$:()=>({value:input}),modal:(_,__,buttons)=>actions=buttons,closeModal:()=>closed++,nextId:()=>++next,eventForTalk:()=>1,mutate:(_,fn)=>{if(!allowed)return false;edits++;fn();return true;},openConditionSettings:(...args)=>settings.push(args)};
 vm.createContext(c);vm.runInContext(section('function addOptionWithSettings(){','function replaceEdges(')+section('function addOption(', 'function deleteOption('),c);
 c.addOptionWithSettings();actions.find(a=>a.label==='创建').run();assert.equal(edits,1);assert.equal(S.doc.options[101].content,input);assert.equal(S.folderOpen['1:101'],true);assert.equal(closed,1);
 input='条件选择';c.addOptionWithSettings();actions.find(a=>a.label==='创建并设置条件').run();assert.equal(edits,2);assert.equal(S.doc.options[102].content,input);assert.equal(settings[0][1],102);
 c.addOption({dataset:{action:'add-option'}});assert.equal(S.doc.options[103].content,'新的选择');
 const before=JSON.stringify(S);allowed=false;assert.equal(c.addOption('拒绝'),null);assert.equal(JSON.stringify(S),before);
 allowed=true;S.branchFolders.condition={kind:'condition',parentTalkId:1,branchId:1};assert.equal(c.addOption('被分支挡住'),undefined);assert.equal(edits,3);
}

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<main id="host"></main>');await page.addStyleTag({path:'standalone/styles.css'});await page.addStyleTag({content:'body{overflow:auto;padding:16px}label{display:block;margin:8px}main{max-width:700px}.uc-trigger{min-height:30px}'});
  for(const file of ['timeline.js','branches.js','search.js','record-labels.js'])await page.addScriptTag({path:'standalone/'+file});
  await page.addScriptTag({content:`const S={order:[],project:{},doc:{talks:{},options:{10:{id:10,talkId:[2,3],talkId2:[999999],nextEvtId:0}},events:{1:{id:1,title:'当前事件',talkId:[1]},2:{id:2,title:'跨事件接续',talkId:[43827]}},persons:{}},branchFolders:{},folderOpen:{},selected:1};
const Timeline=StudentAgeTimeline,Branches=StudentAgeBranches,ids=v=>Array.isArray(v)?v.map(Number).filter(Number.isFinite):[],values=v=>Object.values(v||{}),h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),talkLabel=id=>S.doc.talks[id]?.content||'外部对话 · '+id,talk=()=>S.doc.talks[S.selected],mutate=(_,fn)=>fn();
${section('function continuationOptions(', 'function setFolderFailure(')}
${section('function talkOptions(', 'function syncTalkActionCodes(')}
const changes=[];document.addEventListener('change',event=>{const e=event.target;if(e.tagName==='SELECT')changes.push({id:e.id,value:e.value});${source.slice(source.indexOf("  if(e.dataset.optionField&&e.tagName==='SELECT'){"),source.indexOf("  if(e.dataset.arg&&e.tagName==='SELECT')"))}});
window.choiceFixture={S,changes};`});
  const initial=await page.evaluate(()=>{
   for(let id=1;id<=43827;id++){S.order.push(id);S.doc.talks[id]={id,content:'对话内容 '+id,nextTalk:[],option:[]};}S.doc.talks[1].option=[10];S.doc.talks[20].option=[10];
   S.branchFolders['1:10']={parentTalkId:1,optionId:10,talkIds:[],continuation:{kind:'end'}};
   for(let i=0;i<300;i++)S.branchFolders['branch'+i]={kind:'condition',parentTalkId:i+100,branchId:1,routerId:30000+i*3,exitId:30001+i*3,endId:30002+i*3,talkIds:[],failureNext:null};
   const start=performance.now(),html='<label>成功'+targetSelect(S.doc.options[10],'talkId','data-option-id="10" data-option-field="talkId"',1)+'</label><label>失败'+targetSelect(S.doc.options[10],'talkId2','id="failure-target" data-option-id="10" data-option-field="talkId2"',1)+'</label><label>夹结束<select id="continuation" data-folder-continuation="1:10">'+continuationOptions(S.branchFolders['1:10'])+'</select></label><label>条件失败<select id="condition-failure" data-folder-failure="branch0">'+failureOptions(S.branchFolders.branch0,100)+'</select></label><label>默认入口<select id="event-first">'+talkOptions(3)+'</select></label><select id="disabled" disabled>'+talkOptions(2)+'</select><select id="native"><optgroup label="普通分组"><option value="a">甲</option><option value="b" disabled>乙</option><option value="c">丙</option></optgroup></select><select id="multiple" multiple><option value="a" selected>甲</option><option value="b">乙</option></select>';
   document.querySelector('#host').innerHTML=html;return {ms:performance.now()-start,htmlBytes:html.length*2,optionCount:document.querySelectorAll('option').length};
  });assert(initial.optionCount<25,JSON.stringify(initial));
  const candidateEvidence=await page.evaluate(()=>{
   const success=document.querySelector('[data-option-field="talkId"]'),rows=STUDIO_SELECT_ROWS(success),folderRows=STUDIO_SELECT_ROWS(document.querySelector('#continuation')),failureRows=STUDIO_SELECT_ROWS(document.querySelector('#condition-failure'));
   const result={successCount:rows.length,folderCount:folderRows.length,conditionCount:failureRows.length,foreignTalk:rows.some(r=>r.value==='43827'),externalSelected:STUDIO_SELECT_ROWS(document.querySelector('#failure-target')).some(r=>r.value==='999999'),folderForeignEvent:folderRows.some(r=>r.value==='event:2'),folderExcludesParent:!folderRows.some(r=>r.value==='talk:1'),folderExcludesInternal:!folderRows.some(r=>r.value==='talk:30000'),failureExcludesParent:!failureRows.some(r=>r.value==='100'),failureExcludesInternal:!failureRows.some(r=>r.value==='30000')};
   const populated={parentTalkId:2,optionId:11,talkIds:[4,5],continuation:{kind:'event',eventId:2}};S.branchFolders.populated=populated;const extra=document.createElement('select');extra.dataset.folderContinuation='populated';extra.innerHTML=continuationOptions(populated);const extraRows=STUDIO_SELECT_ROWS(extra);result.populatedCurrentEvent=extra.value==='event:2';result.populatedExcludesOwnLines=[2,4,5].every(id=>!extraRows.some(row=>row.value==='talk:'+id));delete S.branchFolders.populated;
   extra.innerHTML=failureOptions({...S.branchFolders.branch0,failureNext:[]},100);result.conditionEndCurrent=extra.value==='end';extra.innerHTML=targetSelect({nextTalk2:[]},'nextTalk2','').match(/<select[^>]*>([\s\S]*)<\/select>/)[1];result.alternateDefault=extra.options[0].textContent==='沿用普通出口';S.project.readOnly=true;result.readOnlyRetainsCurrent=STUDIO_SELECT_ROWS(success).some(row=>row.value==='2');result.readOnlyBounded=STUDIO_SELECT_ROWS(success).length===2;result.readOnlyFolderChoicesRetained=STUDIO_SELECT_ROWS(document.querySelector('#continuation')).length===folderRows.length;S.project.readOnly=false;
   return result;
  });for(const [key,value]of Object.entries(candidateEvidence))if(typeof value==='boolean')assert(value,key);assert.equal(candidateEvidence.successCount,43827-900);assert.equal(candidateEvidence.folderCount,43827-900+1);assert.equal(candidateEvidence.conditionCount,43827-900+1);
  await page.addScriptTag({path:'standalone/ui-controls.js'});await page.waitForFunction(()=>document.querySelectorAll('.uc-trigger').length>=9);
  const trigger=selector=>page.locator(selector).locator('..').locator('.uc-trigger');
  async function pick(selector,query){await trigger(selector).click();const search=page.locator('.uc-search');await search.fill(query);await page.locator('.uc-option').filter({hasText:query}).first().click();}
  await pick('[data-option-field="talkId"][data-target-sex="0"]','43827');assert.deepEqual(await page.evaluate(()=>S.doc.options[10].talkId),[43827,3]);
  await pick('[data-option-field="talkId"][data-target-sex="1"]','43826');assert.deepEqual(await page.evaluate(()=>S.doc.options[10].talkId),[43827,43826]);
  await pick('#failure-target','43825');assert.deepEqual(await page.evaluate(()=>S.doc.options[10].talkId2),[43825]);assert.equal(await page.locator('#failure-target option').count(),3);
  await pick('#failure-target','43824');assert.deepEqual(await page.evaluate(()=>S.doc.options[10].talkId2),[43824]);assert.equal(await page.locator('#failure-target option').count(),3,'chosen DOM must stay bounded over repeated selections');
  await trigger('#continuation').click();assert((await page.locator('.uc-option').count())<=80);assert((await page.locator('.uc-optgroup').allTextContents()).includes('接续后续剧情'));await page.locator('.uc-search').fill('跨事件接续');await page.locator('.uc-option').filter({hasText:'跨事件接续'}).click();assert.equal(await page.locator('#continuation').inputValue(),'event:2');assert.equal(await page.locator('#continuation optgroup[label="接续后续剧情"] option').count(),1);
  await pick('#continuation','43827');assert.equal(await page.locator('#continuation').inputValue(),'talk:43827');assert.equal(await page.locator('#continuation option').count(),2);
  await pick('#condition-failure','43827');assert.equal(await page.locator('#condition-failure').inputValue(),'43827');
  await pick('#event-first','43827');assert.equal(await page.locator('#event-first').inputValue(),'43827');
  assert.equal(await trigger('#disabled').isDisabled(),true);
  await trigger('#native').click();assert.equal(await page.locator('.uc-option').filter({hasText:'乙'}).isDisabled(),true);await page.locator('.uc-option').filter({hasText:'丙'}).click();assert.equal(await page.locator('#native').inputValue(),'c');
  await trigger('#multiple').click();await page.locator('.uc-option').filter({hasText:'乙'}).click();assert.deepEqual(await page.locator('#multiple').evaluate(s=>Array.from(s.selectedOptions,o=>o.value)),['a','b']);await page.keyboard.press('Escape');
  const selected=await page.evaluate(()=>({talkId:S.doc.options[10].talkId,talkId2:S.doc.options[10].talkId2,sharedParents:Object.values(S.doc.talks).filter(t=>t.option.includes(10)).map(t=>t.id),changes:choiceFixture.changes}));assert.deepEqual(selected.sharedParents,[1,20]);assert.deepEqual(errors,[]);
  const report={initial,candidates:candidateEvidence,selected,checks:'single mutation, all targets, external current value, gender routes, shared options, search/page DOM bounds, optgroups, disabled, native and multiple selects passed'};
  console.log(JSON.stringify(report,null,2));const evidenceIndex=process.argv.indexOf('--evidence');if(evidenceIndex>=0){const target=path.resolve(process.argv[evidenceIndex+1]);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,JSON.stringify(report,null,2)+'\n');}
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
