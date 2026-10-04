'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),I=require('../indexed-talks.js'),R=I.Remote;
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8'),take=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b)),copy=value=>JSON.parse(JSON.stringify(value));
const rows={1:{id:1,content:'原文',nextTalk:[2],future:{keep:true}},2:{id:2,content:'后续',nextTalk:[]},3:{id:3,content:'独立句'}};
const factories={plain:()=>copy(rows),indexed:()=>I.create(Object.entries(rows).map(([id,row])=>[id,JSON.stringify(row)])),remote:()=>R.create({version:1,generation:'save-state',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content,hasText:true}]))},async(_,body)=>({generation:'save-state',revision:'r1',rows:body.ids.map(id=>[id,JSON.stringify(rows[id])]),remaining:[]}),'r1')};
async function harness(kind){
 const talks=factories[kind]();await R.ensure(talks,[1,2,3]);
 const S={project:{id:'isolated'},revision:'r1',doc:{talks,events:{1:{id:1,talkId:[1],title:'事件'}},options:{},persons:{},talkOwners:{1:[1],2:[1]}},order:[1,2,3],deleted:[],replacements:{},premises:{},branchFolders:{},pinned:{talks:new Set(),options:new Set(),events:new Set()},idMappings:{TalkCfg:{1:2}},undo:[],redo:[],dirty:true,saving:false};
 let parses=0;const index={...I,parse:text=>{parses++;return I.parse(text);}},box={S,IndexedTalks:index,Remote:R,clone:I.clone,Timeline:require('../timeline.js'),document:{activeElement:null,querySelector:()=>null},textDirtyTimer:null,editable:()=>true,StudentAgeEventBindings:{syncSocialEffects:()=>{}},renderChrome:()=>{},storySelection:{render:()=>{}},scheduleRenumber:()=>{},storyClaims:new Map(),toast:()=>{},fail:()=>{},updateDirty:()=>{}};
 vm.createContext(box);vm.runInContext(take('function currentSignature()', '// Undo keeps')+take('function composeMappings(', 'function eventTraversal(')+take('function changedStoryPayload(', 'function unassignedTalkIds('),box);
 S.saved=box.currentSignature();S.doc.talks[1].content='提交的正文';
 return {S,box,reset:()=>{parses=0;},parses:()=>parses};
}
const report=[];
(async()=>{
 for(const kind of Object.keys(factories)){
  let {S,box,reset,parses}=await harness(kind);
  // Optional baseline reuse produces exactly the default payload, including
  // key order and explicit mappings; the default still reads the current saved state.
  const baseline=I.parse(S.saved),expected=JSON.stringify(box.changedStoryPayload(S.idMappings));
  assert.equal(JSON.stringify(box.changedStoryPayload(S.idMappings,baseline)),expected);assert.equal(JSON.stringify(box.changedStoryPayloadFrom(baseline)),JSON.stringify(box.changedStoryPayloadFrom()));
  box.api=async(_,payload)=>{assert.equal(JSON.stringify(payload),expected);return {ok:true,revision:'r2'};};reset();assert.equal(await box.save(),true);assert.equal(parses(),2);assert.equal(S.dirty,false);

  ({S,box,reset,parses}=await harness(kind));let started,resolve;const atApi=new Promise(r=>started=r),response=new Promise(r=>resolve=r),live=S.doc,priorSaved=S.saved;
  box.api=async(_,payload)=>{assert.equal(payload.talkPatch?.upsert[1].content||payload.talks[1].content,'提交的正文');started();return response;};reset();const pending=box.save();await atApi;
  S.doc.talks[1].content='保存中继续编辑';S.premises={7:{name:'新前提'}};S.idMappings={TalkCfg:{2:3}};resolve({ok:true,revision:'r2',premises:{stale:true},branchFolders:{stale:true}});
  assert.equal(await pending,false);assert.equal(parses(),2);assert.equal(S.doc,live);assert.equal(S.doc.talks[1].content,'保存中继续编辑');assert.equal(S.dirty,true);assert.notEqual(S.saved,priorSaved);assert.equal(I.parse(S.saved)[0].talks[1].content,'提交的正文');assert.deepEqual(S.premises,{7:{name:'新前提'}});assert.equal(S.branchFolders.stale,undefined);assert.deepEqual(S.idMappings,{TalkCfg:{2:3}});

  ({S,box,reset,parses}=await harness(kind));let failed,reject;const atFailure=new Promise(r=>failed=r),failure=new Promise((_,r)=>reject=r),saved=S.saved,original=S.doc;
  box.api=async()=>{failed();return failure;};reset();const errored=box.save();await atFailure;S.idMappings={TalkCfg:{2:3}};reject(new Error('模拟保存失败'));
  await assert.rejects(errored,/模拟保存失败/);assert.equal(parses(),2);assert.equal(S.doc,original);assert.equal(S.saved,saved);assert.equal(S.dirty,true);assert.equal(S.saving,false);assert.deepEqual(copy(S.idMappings),{TalkCfg:{1:3}});

  ({S,box,reset,parses}=await harness(kind));box.Remote={...R,ensure:async()=>{throw Error('模拟正文读取失败');}};box.api=async()=>{throw Error('must not submit after a load failure');};reset();
  await assert.rejects(box.save(),/模拟正文读取失败/);assert.equal(parses(),2);assert.deepEqual(copy(S.idMappings),{TalkCfg:{1:2}});assert.equal(S.saving,false);

  ({S,box,reset,parses}=await harness(kind));box.Remote={...R,ensure:async(...args)=>{await R.ensure(...args);const latest=I.parse(S.saved);latest[1]=[3,2,1];S.saved=I.stringify(latest);}};
  box.api=async(_,payload)=>{assert.deepEqual(Array.from(payload.order),[1,2,3]);return {ok:true,revision:'r2'};};reset();assert.equal(await box.save(),true);assert.equal(parses(),3,'a changed saved baseline must be read again to retain existing semantics');
  report.push({kind,payloadBytesEqual:true,normalParseCalls:2,inflightEditsRemainDirty:true,errorMappingsRestored:true,changedBaselineParseCalls:3});
 }
 console.log(JSON.stringify({status:'passed',checks:report},null,2));
 const index=process.argv.indexOf('--evidence');if(index>=0)fs.writeFileSync(path.resolve(process.argv[index+1]),JSON.stringify({status:'passed',checks:report},null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
