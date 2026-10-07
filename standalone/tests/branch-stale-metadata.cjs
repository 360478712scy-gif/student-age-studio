const assert=require('node:assert/strict'),T=require('../timeline.js'),B=require('../branches.js');
function fixture(){
 const doc={talks:{1:{...T.blank(1),content:'开始',nextTalk:[2]},2:{...T.blank(2),content:'后续正文'},20:{...T.blank(20),content:'保留分支正文',effect:[[1163,5,1]]}},events:{1:{id:1,talkId:[1]}},options:{}},folders={};
 let id=100;const first=T.addCondition(doc,folders,1,()=>id++);T.insert(doc,folders,first.folder,doc.talks[20]);
 doc.talks[first.folder.routerId].check=[[7,1,3,30]];
 return {doc,folders,first,allocate:()=>id++};
}
const cases={
 'missing router':({doc,first})=>{delete doc.talks[first.folder.routerId];doc.talks[1].nextTalk=[2];},
 'missing exit':({doc,first})=>{delete doc.talks[first.folder.exitId];doc.talks[1].nextTalk=[2];},
 'missing end':({doc,first})=>{delete doc.talks[first.folder.endId];doc.talks[1].nextTalk=[2];},
 'missing parent':({doc})=>{delete doc.talks[1];},
 'native parent route':({doc})=>{doc.talks[1].nextTalk=[2];},
 'native success route':({doc,first})=>{doc.talks[first.folder.routerId].nextTalk=[2];},
 'native failure route':({doc,first})=>{doc.talks[first.folder.routerId].nextTalk2=[20];},
 'native exit route':({doc,first})=>{doc.talks[first.folder.exitId].nextTalk=[];},
 'native end route':({doc,first})=>{doc.talks[first.folder.endId].nextTalk=[2];},
 'native exit condition':({doc,first})=>{doc.talks[first.folder.exitId].check=[[7,1,3,30]];},
 'helper becomes dialogue':({doc,first})=>{doc.talks[first.folder.routerId].content='原版编辑器写入正文';},
 'helper gains effect':({doc,first})=>{doc.talks[first.folder.exitId].effect=[[1163,8,1]];}
};
for(const [name,change]of Object.entries(cases)){
 const f=fixture();change(f);const before=JSON.stringify(f.doc);
 const syncDoc=structuredClone(f.doc),syncFolders=structuredClone(f.folders);
 assert.doesNotThrow(()=>T.sync(syncDoc,syncFolders,1),name+': reconciliation does not block');
 assert.equal(JSON.stringify(syncDoc),before,name+': syncing stale metadata never reconstructs native edges');
 assert.deepEqual(B.cleanup(f.doc,f.folders),{},name+': discard stale ownership');
 assert.equal(JSON.stringify(f.doc),before,name+': reconciliation preserves native rows');
 assert.doesNotThrow(()=>T.removeFolder(f.doc,f.folders,f.first.key),name+': old folder remains removable');
 assert.equal(JSON.stringify(f.doc),before,name+': removing stale metadata preserves rows');
 assert.deepEqual(f.folders,{},name+': no stale folder');
 if(f.doc.talks[1]){
  const added=T.addCondition(f.doc,f.folders,1,f.allocate);
  assert.ok(f.doc.talks[added.folder.routerId],name+': can create another branch');
  assert.equal(f.doc.talks[20].content,'保留分支正文');
 }
}
{
 const f=fixture(),before=JSON.stringify(f.doc);assert.deepEqual(B.cleanup(f.doc,f.folders),f.folders);assert.equal(JSON.stringify(f.doc),before);
 const second=T.addCondition(f.doc,f.folders,1,f.allocate);
 // Native editor removes the first empty route but leaves the second branch valid.
 delete f.doc.talks[f.first.folder.routerId];f.doc.talks[1].nextTalk=[second.folder.routerId];
 const kept=B.cleanup(f.doc,f.folders);assert.deepEqual(Object.keys(kept),[second.key]);
 const native=JSON.stringify(f.doc);T.removeFolder(f.doc,f.folders,f.first.key);assert.equal(JSON.stringify(f.doc),native);assert.ok(f.folders[second.key]);
 T.sync(f.doc,f.folders,1);assert.deepEqual(f.doc.talks[1].nextTalk,[second.folder.routerId]);
}
{
 const f=fixture();delete f.doc.talks[f.first.folder.routerId];const before=JSON.stringify(f.doc);
 assert.doesNotThrow(()=>T.sync(f.doc,f.folders,1));assert.equal(JSON.stringify(f.doc),before);assert.deepEqual(f.folders,{});
}
{
 // An explicit Studio deletion still rebuilds the owned exit after removing
 // the last body line. External edits have no deletion replacement ledger.
 const f=fixture();delete f.doc.talks[20];T.replaceMany(f.doc,f.folders,{20:[]});
 f.folders=B.cleanup(f.doc,f.folders,{20:[]});assert.ok(f.folders[f.first.key]);
 T.sync(f.doc,f.folders,1,true);assert.deepEqual(f.doc.talks[f.first.folder.routerId].nextTalk,[f.first.folder.exitId]);
 assert.ok(B.cleanup(f.doc,f.folders)[f.first.key]);
}
{
 const f=fixture(),second=T.addCondition(f.doc,f.folders,1,f.allocate);
 T.setFailure(f.doc,f.folders,f.first.folder,[]);
 assert.deepEqual(Object.keys(B.cleanup(f.doc,f.folders)),[f.first.key,second.key],'an authored failure override keeps later draft branches');
}
{
 const R=require('../remote-talks.js'),f=fixture(),rows=f.doc.talks;globalThis.StudentAgeRemoteTalks=R;
 f.doc.talks=R.create({version:1,generation:'stale-branches',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content,hasText:!!content}]))},()=>{throw Error('reconciliation must not fetch dialogue bodies');},'r');
 assert.deepEqual(B.cleanup(f.doc,f.folders),f.folders);assert.equal(R.stats(f.doc.talks).loaded,0);
 f.doc.talks[f.first.folder.routerId].content='未加载正文中写入的新台词';assert.deepEqual(B.cleanup(f.doc,f.folders),{});assert.equal(R.stats(f.doc.talks).loaded,0);
 delete globalThis.StudentAgeRemoteTalks;
}
console.log('branch-stale-metadata: external deletion, native routes, helper prose/effects, valid sibling and re-creation passed');
