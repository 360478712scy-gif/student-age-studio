'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{performance}=require('node:perf_hooks');
const R=require('../remote-talks.js'),B=require('../branches.js');
const ids=v=>Array.isArray(v)?v.map(Number).filter(Number.isFinite):[];
const expectedParents=(rows,option)=>Object.values(rows).filter(row=>ids(row.option).includes(Number(option))).map(row=>Number(row.id));
const expectedCounts=rows=>{const counts=new Map();for(const row of Object.values(rows))for(const option of new Set(ids(row.option)))counts.set(option,(counts.get(option)||0)+1);return counts;};
const make=rows=>R.create(JSON.parse(JSON.stringify({version:1,generation:'branches',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content,hasText:!!content}]))})),()=>{throw Error('branch ownership must never fetch text');},'r');
globalThis.StudentAgeRemoteTalks=R;
const plain={1:{id:1,content:'甲',option:[10,'10',20,'bad']},2:{id:2,content:'乙',option:[10]},3:{id:3,content:'丙'},4:{id:4,content:'丁',option:[]}};
let talks=make(plain),doc={talks,options:{10:{id:10,talkId:[]},20:{id:20,talkId:[]}},events:{}},folders={};
assert.deepEqual(B.optionParents(doc,'10'),[1,2]);assert.deepEqual(B.optionParentCounts(doc),new Map([[10,2],[20,1]]));
assert.throws(()=>B.create(doc,folders,1,10),/多句共用/);assert(B.describe(doc,folders,1,10).shared);assert(B.describe(doc,folders,1,10,B.optionParentCounts(doc)).shared);
const saved=R.revive(R.pack(talks));talks[2].option=[];
assert.deepEqual(B.optionParents(doc,10),[1]);assert.equal(B.optionParentCounts(doc).get(10),1);assert.equal(B.describe(doc,folders,1,10).shared,false);
const folder=B.create(doc,folders,1,10);B.insert(doc,folders,folder,{id:5,content:'新句',option:[],nextTalk:[]});assert.deepEqual(folder.talkIds,[5]);assert.deepEqual([...doc.options[10].talkId],[5]);
assert.deepEqual(B.optionParents({...doc,talks:saved},10),[1,2]);assert.equal(B.optionParentCounts({...doc,talks:saved}).get(10),2,'an undo snapshot keeps its own option fields');
talks[11]=talks[1];talks[11].id=11;delete talks[1];assert.deepEqual(B.optionParents(doc,10),[11],'renumbered rows retain their current ID');
delete talks[11].option;assert.deepEqual(B.optionParents(doc,10),[]);assert.equal(B.optionParentCounts(doc).has(10),false);assert.equal(R.stats(talks).loaded,0);
assert.deepEqual(B.optionParents({talks:plain},10),[1,2]);assert.deepEqual(B.optionParentCounts({talks:plain}),expectedCounts(plain));

// Compare mutable fields, added/deleted rows and history forks against a regular
// JSON table. Repeated option IDs count once per parent, including string IDs.
let rows=JSON.parse(JSON.stringify(plain)),remote=make(rows),seed=72841;const snapshots=[];
const random=n=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed%n;};
for(let step=0;step<200;step++){
 const id=String(random(12)+1),op=random(7);
 if(!rows[id]){rows[id]={id:Number(id),option:[]};remote[id]={id:Number(id),option:[]};}
 if(op===0){const option=random(4)+10;rows[id].option=[option,String(option),20];remote[id].option=rows[id].option.slice();}
 if(op===1){rows[id].option??=[];remote[id].option??=[];const option=random(4)+10;rows[id].option.push(option);remote[id].option.push(option);}
 if(op===2){if(rows[id].option){rows[id].option.splice(0,1);remote[id].option.splice(0,1);}}
 if(op===3){delete rows[id].option;delete remote[id].option;}
 if(op===4){delete rows[id];delete remote[id];}
 if(op===5)snapshots.push([R.revive(R.pack(remote)),JSON.parse(JSON.stringify(rows))]);
 if(op===6&&snapshots.length){const pair=snapshots[random(snapshots.length)];remote=R.revive(R.pack(pair[0]));rows=JSON.parse(JSON.stringify(pair[1]));}
 for(const option of [10,11,12,13,20])assert.deepEqual(B.optionParents({talks:remote},option),expectedParents(rows,option),'parents at step '+step);
 assert.deepEqual(B.optionParentCounts({talks:remote}),expectedCounts(rows),'counts at step '+step);assert.equal(R.stats(remote).loaded,0);
}

// A large, unloaded directory must use its raw fields: zero whole-table row
// accesses, zero body requests, and the same parents/counts as the old scan.
const large={};for(let id=1;id<=43827;id++)large[id]={id,content:'完整正文 '+id,option:id%17===0?[10,'10',20]:[]};
const table=make(large);let rowReads=0,enumerations=0;
const monitored=new Proxy(table,{get:(target,id)=>{rowReads++;return Reflect.get(target,id);},ownKeys:target=>{enumerations++;return Reflect.ownKeys(target);}});
globalThis.StudentAgeRemoteTalks={...R,info:value=>R.info(value===monitored?table:value)};
let start=performance.now();const oldParents=expectedParents(monitored,10),oldCounts=expectedCounts(monitored),beforeMs=performance.now()-start,beforeReads=rowReads,beforeEnumerations=enumerations;
rowReads=0;enumerations=0;start=performance.now();const parents=B.optionParents({talks:monitored},10),counts=B.optionParentCounts({talks:monitored}),afterMs=performance.now()-start;
assert.deepEqual(parents,oldParents);assert.deepEqual(counts,oldCounts);assert.equal(rowReads,0);assert.equal(enumerations,0);assert.equal(R.stats(table).loaded,0);assert(beforeReads>=43827*2);
globalThis.StudentAgeRemoteTalks=R;
const report={status:'passed',differentialSteps:200,checks:'sharing guards, duplicate/string IDs, nested drafts, deletion, insertion, current renumbered IDs, undo forks, normal-table fallback and unloaded-body boundaries',benchmark:{talks:43827,parents:parents.length,before:{ms:Number(beforeMs.toFixed(2)),rowReads:beforeReads,tableEnumerations:beforeEnumerations},after:{ms:Number(afterMs.toFixed(2)),rowReads,tableEnumerations:enumerations},loadedBodies:R.stats(table).loaded}};
console.log(JSON.stringify(report,null,2));const evidenceIndex=process.argv.indexOf('--evidence');if(evidenceIndex>=0){const target=path.resolve(process.argv[evidenceIndex+1]);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,JSON.stringify(report,null,2)+'\n');}
