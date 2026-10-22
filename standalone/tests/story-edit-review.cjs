'use strict';
// Run against the existing checkout; only synthetic in-memory documents are used.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=process.env.STUDIO_ROOT||path.join(__dirname,'../..');
const I=require(path.join(root,'standalone/indexed-talks.js')),R=I.Remote,Ownership=require(path.join(root,'standalone/event-ownership.js'));
const source=fs.readFileSync(path.join(root,'standalone/app.js'),'utf8');
const take=(a,b)=>{const x=source.indexOf(a),y=source.indexOf(b,x);assert(x>=0&&y>x,a);return source.slice(x,y);};
const plain=x=>JSON.parse(JSON.stringify(x)),checks=[];
async function check(name,fn){try{await fn();checks.push({name,pass:true});}catch(e){checks.push({name,pass:false,error:e.message});process.exitCode=1;}}
function box(extra){const b={IndexedTalks:I,Remote:R,clone:I.clone,ids:v=>Array.isArray(v)?v.map(Number).filter(Number.isFinite):[],...extra};vm.createContext(b);return b;}
(async()=>{
 await check('rendered unloaded selection loads its body and pins it',async()=>{
  const rows={1:{id:1,content:'first',roleIds:[]},2:{id:2,content:'second',roleIds:[]}},requests=[];
  const talks=R.create({version:1,generation:'review-selection',ids:['1','2'],summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content,hasText:true}]))},async(_,body)=>{requests.push(body.ids);return {generation:'review-selection',revision:'r1',rows:body.ids.map(id=>[id,JSON.stringify(rows[id])]),remaining:[]};},'r1');
  await R.ensure(talks,[1],{pin:true});
  const S={doc:{talks},selected:1,branchFolders:{},folderOpen:{},project:{}},card={classList:{add(){},remove(){}},setAttribute(){}},element={scrollTop:0,scrollTo(){}};let content;
  const b=box({S,Branches:{ownedBy:()=>null},stageAudio:null,scenePlayer:null,externalSession:null,window:{},document:{querySelector:()=>card,querySelectorAll:()=>[]},$:()=>element,storySelection:{render(){}},stopLinePlayback(){},syncFaceFromTalk(){},talk:()=>S.doc.talks[S.selected],currentEventGrade:()=>0,renderChrome(){},renderEvents(){},renderList(){},renderEditor(){content=S.doc.talks[S.selected].content;},renderPreview(){},fail(e){throw e;}});
  vm.runInContext(take('function updateSelectedTalkView','function syncFaceFromTalk')+take('let renderSequence=','function renderEvents'),b);
  b.selectTalk(2);await new Promise(setImmediate);
  assert.equal(content,'second');assert.equal(R.ready(talks,2),true);assert.deepEqual([...R.info(talks).base.pinned],['2']);
  b.selectTalk(1);assert.equal(content,'first');assert.deepEqual([...R.info(talks).base.pinned],['1']);assert.equal(requests.length,2);
 });
 for(const kind of ['plain','indexed'])await check(kind+' new dialogue retains event and external-folder membership',()=>{
  const initial={1:{id:1,content:'existing'}};
  const talks=kind==='plain'?plain(initial):I.create(Object.entries(initial).map(([id,row])=>[id,JSON.stringify(row)]));
  const S={doc:{talks,events:{7:{id:7,talkId:[1]}},options:{},talkOwners:{1:[7]},externalDialogueIds:[],externalDialogueFolders:{folder:{talkIds:[],uses:[]}}},event:7,branchFolders:{}};
  const b=box({S,externalSession:{folder:'folder'},editable:()=>true,history(){},premiseHolders:()=>[],talk:()=>null,linkStamp:()=>null,cleanLostPremises(){},reconcileStoryClaims(){},updateDirty(){},render(){},scheduleRenumber(){},syncOwnership:before=>Ownership.sync(S.doc,S.branchFolders,S.event,before)});
  vm.runInContext(take('function mutate(label','let textDirtyTimer')+take('function syncExternal(','const sharedWorkspace'),b);
  b.mutate('add',()=>{S.doc.talks[9]={id:9,content:'new disconnected line'};});
  assert(S.doc.talkOwners[9],'new disconnected dialogue lost its event owner');assert.deepEqual(plain(S.doc.talkOwners[9]),[7]);assert.deepEqual(plain(S.doc.externalDialogueIds),[9]);assert.deepEqual(plain(S.doc.externalDialogueFolders.folder.talkIds),[9]);
 });
 await check('option text refreshes managed and imported folders with the ID label',()=>{
  const titles=[{innerHTML:'old'},{innerHTML:'old'}],nodes=['1:101','2:101'].map((folder,i)=>({dataset:{folder},querySelector:()=>titles[i]}));
  const labels=box({window:{},document:{documentElement:{classList:{toggle(){}}},querySelector:()=>null},Event:function(){}});labels.window.dispatchEvent=()=>{};
  vm.runInContext(fs.readFileSync(path.join(root,'standalone/record-labels.js'),'utf8'),labels);
  const b=box({S:{branchFolders:{'1:101':{optionId:101}}},document:{querySelectorAll:()=>nodes},StudentAgeRecordLabels:labels.window.StudentAgeRecordLabels});
  vm.runInContext(take('function updateOptionTextCard','function updateOptionContent'),b);
  b.updateOptionTextCard(101,'<new>');
  for(const title of titles){assert.match(title.innerHTML,/record-id-prefix/);assert.match(title.innerHTML,/\[101\]/);assert.match(title.innerHTML,/&lt;new&gt;/);}
 });
 await check('saving PersonCfg leaves unsaved ownership baseline intact',()=>{
  const savedOwners={1:[7]},S={doc:{talks:{1:{id:1}},persons:{2:{id:2,name:'changed'}},talkOwners:{1:[7],9:[7]}},savedOwners,order:[1],localIds:{},saved:JSON.stringify([{talks:{1:{id:1}},persons:{2:{id:2,name:'old'}}},[1]])};
  const b=box({S,window:{},updateDirty(){},renderChrome(){}});
  vm.runInContext(take('const jsonStoryKeys=','function jsonSegment')+take('window.STUDIO_STORY_JSON=','window.STUDIO_CURRENT_REVISION='),b);
  vm.runInContext(take('function signatureFromParts','function currentSignature'),b);
  b.window.STUDIO_STORY_JSON.saved('PersonCfg',S.doc.persons,'r2');
  assert.equal(S.savedOwners,savedOwners,'single-table disk save must not acknowledge unsaved editor-state ownership');
 });
 for(const defer of [false,true])await check('save resumes only deferred structural renumber: '+defer,async()=>{
  const S={project:{id:'synthetic'},revision:'r1',doc:{talks:{1:{id:1,content:'old'}},options:{},events:{7:{id:7,talkId:[1]}},talkOwners:{1:[7]}},order:[1],deleted:[],replacements:{},premises:{},branchFolders:{},pinned:{talks:new Set(),options:new Set(),events:new Set()},idMappings:{},undo:[],redo:[],dirty:true,saving:false};S.savedOwners=S.doc.talkOwners;
  let finish,started,scheduled=0;const pending=new Promise(r=>finish=r),atApi=new Promise(r=>started=r);
  const b=box({S,renumberPending:false,renumberDeferred:false,Timeline:require(path.join(root,'standalone/timeline.js')),Branches:require(path.join(root,'standalone/branches.js')),document:{activeElement:null,querySelector:()=>null},textDirtyTimer:null,editable:()=>true,StudentAgeEventBindings:{syncSocialEffects(){}},renderChrome(){},storySelection:{render(){}},scheduleRenumber(){scheduled++;},storyClaims:new Map(),toast(){},fail(e){throw e;},updateDirty(){},runRenumber:async()=>true,renumberPlan:()=>({}),api:async()=>{started();return pending;}});
  vm.runInContext(take('function signatureFromParts','// Undo keeps')+take('function sameValue','function plainValue')+take('function ownersDiffer','function updateDirty')+take('function composeMappings','function eventTraversal')+take('async function renumberEvent','async function runRenumber')+take('function changedStoryPayload(','function unassignedTalkIds('),b);
  S.saved=b.currentSignature();S.doc.talks[1].content='edited';const saving=b.save();await atApi;
  if(defer)assert.equal(await b.renumberEvent(7),false);finish({revision:'r2'});await saving;assert.equal(scheduled,defer?1:0);
 });
 console.log(JSON.stringify({checks},null,2));
})();
