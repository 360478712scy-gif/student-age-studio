'use strict';
// The ownership and display maps are reused across edits while links agree. Every reuse must equal a fresh
// computation, and edits that leave links alone must not walk the whole mod again.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const R=require('../remote-talks.js'),I=require('../indexed-talks.js'),Ownership=require('../event-ownership.js');
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8'),take=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b));
const copy=value=>JSON.parse(JSON.stringify(value));
globalThis.StudentAgeRemoteTalks=R;
const makeRemote=rows=>R.create(copy({version:1,generation:'ownership-reuse',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content,hasText:!!content}]))}),()=>{throw Error('ownership requested dialogue bodies');},'r');
let seed=20261013;const rnd=n=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed%n;},pick=list=>list[rnd(list.length)];

function studio(talks){
 const rows={};for(let e=1;e<=3;e++)for(let n=1;n<=8;n++){const id=e*1000+n;rows[id]={id,content:'句 '+id,roleIds:[1],nextTalk:n<8&&rnd(5)?[id+1]:[],nextTalk2:[],option:[]};}
 rows[9001]={id:9001,content:'未归属',nextTalk:[1003],nextTalk2:[],option:[]};
 const S={doc:{talks:talks(rows),options:{101:{id:101,content:'选项',talkId:[2003],talkId2:[]}},events:{1:{id:1,title:'甲',talkId:[1001]},2:{id:2,title:'乙',talkId:[2001]},3:{id:3,title:'丙',talkId:[3001],options:[101]}}},branchFolders:{},event:1};
 const calls={sync:0,display:0},tasks=[];
 const box={S,Remote:R,IndexedTalks:I,ids:v=>Array.isArray(v)?v.map(Number).filter(Number.isFinite):[],queueMicrotask:fn=>tasks.push(fn),StudentAgeEventOwnership:{sync:(...args)=>{calls.sync++;return Ownership.sync(...args);},display:(...args)=>{calls.display++;return Ownership.display(...args);}}};
 vm.createContext(box);vm.runInContext(take('let displayMemo=null;','function shownWith('),box);
 // A new browser task: the per-task memo expires, only stamped state survives.
 const nextTask=()=>{tasks.splice(0).forEach(fn=>fn());};
 // What an unconditional sync would have produced from the same starting point.
 const edit=change=>{
  const doc=S.doc,beforeIds=new Set(Object.keys(doc.talks));change();
  const previous={...(S.doc.talkOwners||{})},anchor=[];if(S.doc.events[S.event])for(const id of Object.keys(S.doc.talks))if(!beforeIds.has(id)){previous[id]=[Number(S.event)];anchor.push(Number(id));}
  const expected=Ownership.ownership(S.doc,S.branchFolders,previous,anchor),before={...calls};
  const shown=box.syncOwnership(beforeIds);
  assert.deepEqual(copy(S.doc.talkOwners),expected,'kept ownership equals a fresh sync');assert.deepEqual(shown,Ownership.display(S.doc,S.branchFolders));
  nextTask();const fresh=Ownership.display(S.doc,S.branchFolders);assert.deepEqual(box.eventDisplay(),fresh,'kept display equals a fresh walk');
  return {synced:calls.sync-before.sync,walked:calls.display-before.display};
 };
 return {S,box,calls,edit,nextTask};
}

// Segmented tables: targeted cases first.
{
 const {S,box,calls,edit,nextTask}=studio(makeRemote),row=id=>S.doc.talks[id];
 assert.equal(edit(()=>{}).synced,1,'the first edit computes ownership');
 for(const [name,change] of Object.entries({
  speaker:()=>{row(1002).roleIds=[2,3];},effect:()=>{row(2004).effect=[[1,2,3]];},text:()=>{row(3002).content='改过的正文';},unknown:()=>{row(1005).future={keep:true};},
  nestedNonLink:()=>{row(1002).roleIds.push(9);},collapse:()=>{S.branchFolders={...S.branchFolders};},
  eventTitle:()=>{S.doc.events[1].title='改过的标题';},eventCondition:()=>{S.doc.events[1].condition=[[1,2,3]];},
 }))assert.deepEqual(edit(change),{synced:0,walked:0},name+' leaves links alone and reuses both maps');
 for(const [name,change] of Object.entries({
  next:()=>{row(1002).nextTalk=[2005];},failure:()=>{row(1003).nextTalk2=[3004];},nestedLink:()=>{row(1004).nextTalk.push(3006);},option:()=>{row(2002).option=[101];},
  optionTarget:()=>{S.doc.options[101].talkId=[1007];},entry:()=>{S.doc.events[2].talkId=[2002];},eventOptions:()=>{S.doc.events[1].options=[101];},
  folder:()=>{S.branchFolders['1002:branch:1']={kind:'condition',parentTalkId:1002,talkIds:[3007],routerId:3008,exitId:2008,endId:null};},
  remove:()=>{delete S.doc.talks[2006];},
 })){const done=edit(change);assert.equal(done.synced,1,name+' changes links and recomputes ownership');assert.deepEqual(edit(()=>{row(3003).roleIds=[7];}),{synced:0,walked:0},'the edit after '+name+' reuses the new maps');}
 // A new line is tied to the current event once; the edit after it must recompute rather than keep that tie.
 S.event=2;assert.equal(edit(()=>{S.doc.talks[2050]={id:2050,content:'新句',nextTalk:[],nextTalk2:[],option:[]};}).synced,1);
 assert.deepEqual(S.doc.talkOwners[2050],[2]);assert.equal(edit(()=>{row(1001).roleIds=[4];}).synced,1,'ownership is recomputed once after lines were added');
 assert.equal(edit(()=>{row(1001).roleIds=[5];}).synced,0);
 // Undo and redo restore a different table and ownership object; nothing is carried over.
 S.doc=I.clone(S.doc);assert.equal(edit(()=>{}).synced,1,'a restored document recomputes');assert.equal(edit(()=>{}).synced,0);
 // Ownership replaced or edited by other code (renumbering, JSON editor) is never trusted.
 S.doc.talkOwners={...S.doc.talkOwners};assert.equal(edit(()=>{}).synced,1);
 // Selecting lines or opening another event in later tasks does not walk the graph again.
 const walks=calls.display,syncs=calls.sync;for(let i=0;i<5;i++){nextTask();S.event=1+i%3;box.eventDisplay();}assert.equal(calls.display,walks);assert.equal(calls.sync,syncs);
 // A link edit made outside an undoable edit is still noticed by the next reader.
 nextTask();row(3001).nextTalk=[1008];assert.deepEqual(box.eventDisplay(),Ownership.display(S.doc,S.branchFolders));assert.equal(calls.display,walks+1);
 assert.equal(R.stats(S.doc.talks).loaded,0);
}

// Seeded at project load: the first link-neutral edit must reuse the loaded map.
{
 const {S,box,calls}=studio(makeRemote);
 box.seedOwnershipDisplay(Ownership.display(S.doc,S.branchFolders));
 const before=calls.sync;box.syncOwnership(null);assert.equal(calls.sync,before,'seeded ownership/display caches are reused');
}

// Randomised edits: every step is compared with an unconditional sync and a fresh display walk inside edit().
for(const [kind,talks] of Object.entries({remote:makeRemote,indexed:rows=>I.create(Object.entries(rows).map(([id,row])=>[id,JSON.stringify(row)])),plain:copy})){
 const {S,edit,calls}=studio(talks);let reused=0,steps=0;
 const anyId=()=>Number(pick(Object.keys(S.doc.talks))),target=()=>rnd(6)?anyId():7000+rnd(3);
 const changes=[
  ()=>{S.doc.talks[anyId()].roleIds=[rnd(9)];},()=>{S.doc.talks[anyId()].effect=[[rnd(9)]];},()=>{S.doc.talks[anyId()].content='正文 '+rnd(99);},()=>{},
  ()=>{S.doc.talks[anyId()].nextTalk=rnd(4)?[target()]:[];},()=>{S.doc.talks[anyId()].nextTalk2=rnd(3)?[]:[target()];},()=>{S.doc.talks[anyId()].option=rnd(2)?[101]:[];},
  ()=>{S.doc.options[101].talkId=[target()];},()=>{S.doc.events[1+rnd(3)].talkId=rnd(5)?[target()]:[];},()=>{S.event=1+rnd(4);},
  ()=>{const id=(1+rnd(3))*1000+20+rnd(30);if(!S.doc.talks[id])S.doc.talks[id]={id,content:'新 '+id,nextTalk:rnd(2)?[target()]:[],nextTalk2:[],option:[]};},
  ()=>{const keys=Object.keys(S.doc.talks);if(keys.length>6)delete S.doc.talks[pick(keys)];},
  ()=>{const parent=anyId();S.branchFolders={...S.branchFolders,[parent+':branch:1']:{kind:'condition',parentTalkId:parent,talkIds:[anyId()],routerId:anyId(),exitId:anyId(),endId:null,collapsed:!rnd(2)}};},
  ()=>{const keys=Object.keys(S.branchFolders);if(keys.length){const next={...S.branchFolders};delete next[pick(keys)];S.branchFolders=next;}},
  ()=>{S.doc=I.clone(S.doc);},
 ];
 for(;steps<1500;steps++){const done=edit(pick(changes));if(!done.synced)reused++;}
 if(kind==='remote')assert(reused>200,'segmented tables reuse ownership for edits that leave links alone ('+reused+')');
 else assert.equal(reused,0,kind+' tables have no link version and always recompute');
 assert.equal(calls.sync,steps-reused);
}
console.log('ownership-reuse: kept ownership and display maps match fresh computation across targeted and 4500 random edits');
