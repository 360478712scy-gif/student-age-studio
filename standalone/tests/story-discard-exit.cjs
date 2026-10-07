'use strict';
// Production discard/restore functions, including each supported dialogue store.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const I=require('../indexed-talks.js'),R=I.Remote,plain=value=>JSON.parse(JSON.stringify(value));
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const line=name=>{const result=source.split('\n').find(row=>row.startsWith('function '+name+'('));assert(result,name+' missing');return result;};
const start=source.indexOf('window.STUDIO_DISCARD_STORY='),end=source.indexOf('window.STUDIO_BEFORE_WORKSHOP=',start);assert(start>=0&&end>start);
const rows={1:{id:1,content:'已经保存的正文',nextTalk:[],future:{keep:[1,2]}},2:{id:2,content:'保留的未连接对话',nextTalk:[],future:'keep orphan'}};
const factories={
 plain:()=>plain(rows),
 indexed:()=>I.create(Object.entries(rows).map(([id,row])=>[id,JSON.stringify(row)])),
 remote:()=>R.create({version:1,generation:'discard-exit',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,row])=>[id,{record:{...row,content:undefined},fields:Object.keys(row),excerpt:row.content,hasText:true}]))},async(_,body)=>({generation:'discard-exit',revision:'r1',rows:body.ids.map(id=>[id,JSON.stringify(rows[id])]),remaining:[]}),'r1'),
};
const checks=[],blocked=process.argv.includes('--expect-blocked');
const evidence=process.argv.indexOf('--evidence');
const report=value=>{console.log(JSON.stringify(value,null,2));if(evidence>=0)fs.writeFileSync(path.resolve(process.argv[evidence+1]),JSON.stringify(value,null,2)+'\n');};
(async()=>{
 for(const [kind,factory]of Object.entries(factories)){
  const talks=factory();await R.ensure(talks,[1,2]);
  const S={doc:{talks,events:{7:{id:7,title:'保存的事件',talkId:[1]}},options:{},talkOwners:{1:[7],2:[7]}},order:[1,2],deleted:[],replacements:{},premises:{saved:{name:'原有前提',talkId:2}},branchFolders:{residue:{kind:'condition',routerId:90,talkIds:[2],failureNext:[999999],future:{keep:true}}},pinned:{talks:new Set([1,2]),options:new Set(),events:new Set([7])},idMappings:{},selected:1,event:7,localIds:{talks:[1,2],events:[7]},undo:[],redo:[],dirty:false};
  let closed=0,refreshed=0,reconciled=0;
  const box={S,IndexedTalks:I,clone:I.clone,externalSession:null,renumberTimer:null,textDirtyTimer:null,window:{STUDIO_EVENTS:{refresh(){refreshed++;}}},closeModal(){closed++;},clearTimeout(){},invalidateStageMemo(){},reconcileStoryClaims(){reconciled++;},renderChrome(){},render(){}};
  vm.createContext(box);vm.runInContext(['currentSignature','pinnedSnapshot','arrayRestore','restoredDoc','idsRestore','restore','updateDirty'].map(line).join('\n')+'\n'+source.slice(start,end),box);
  S.saved=box.currentSignature();const saved=S.saved;
  S.doc.talks[1].content='明确放弃的正文';S.doc.talks[99]={id:99,content:'未保存的对话',nextTalk:[999999]};S.order.push(99);S.deleted=[2];S.replacements={2:[99]};S.premises.draft={name:'未保存前提'};S.branchFolders.draft={kind:'condition',routerId:99,talkIds:[999999]};S.pinned.talks.add(99);S.idMappings={TalkCfg:{1:7001}};S.selected=99;S.undo=[{}];S.redo=[{}];S.dirty=true;
  if(blocked){
   let error;try{box.window.STUDIO_DISCARD_STORY();}catch(value){error=value;}
   assert(error);assert.match(error.message,/reading 'slice'/);report({status:'reproduced',kind,error:error.message,stack:error.stack.split('\n').slice(0,5),saveCalls:0});return;
  }
  box.window.STUDIO_DISCARD_STORY();
  assert.equal(box.currentSignature(),saved,'discard must restore all saved fields and pinned IDs');assert.equal(S.dirty,false);assert.equal(S.doc.talks[1].content,rows[1].content);assert.equal(S.doc.talks[99],undefined);assert.deepEqual(Array.from(S.order),[1,2]);assert.equal(S.selected,1);assert.deepEqual(plain(S.doc.talks[2]),rows[2]);assert.deepEqual(plain(S.doc.talks[1].future),{keep:[1,2]});assert.deepEqual(plain(S.idMappings),{});assert.equal(S.undo.length,0);assert.equal(S.redo.length,0);assert.equal(refreshed,1);assert.equal(reconciled,1);
  const prior=S.doc;box.window.STUDIO_DISCARD_STORY();assert.equal(S.doc,prior);assert.equal(refreshed,1);assert.equal(closed,2);
  assert.deepEqual(Array.from(box.arrayRestore({base:[1,2],head:1,tail:0,middle:[3]})),[1,3],'delta undo restoration remains supported');
  checks.push({kind,savedSignatureRestored:true,incompleteDraftDiscarded:true,savedUnconnectedDialogueRetained:true,pinnedIdsRetained:true,dirty:false,saveCalls:0});
 }
 report({status:'passed',checks,scope:'Production discard/restore against plain, indexed and segmented rows; no backend save, real Mod or native window access'});
})().catch(error=>{console.error(error);process.exitCode=1;});
