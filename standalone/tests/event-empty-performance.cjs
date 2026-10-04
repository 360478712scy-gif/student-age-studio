'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{performance}=require('node:perf_hooks');
const R=require('../remote-talks.js'),I=require('../indexed-talks.js'),Timeline=require('../timeline.js'),Ownership=require('../event-ownership.js');
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8'),take=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b));
const ids=value=>Array.isArray(value)?value.map(Number).filter(Number.isFinite):[];
const records={1:{id:1,content:'主线',option:[]},3:{id:3,content:'内部路由'},4:{id:4,content:'分支正文'},8:{id:8,content:'原版句'},9:{id:9,content:'内部出口'},10:{id:10,content:'分支终点'}};
const makeRemote=rows=>R.create(JSON.parse(JSON.stringify({version:1,generation:'empty-event',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content,hasText:!!content}]))})),()=>{throw Error('empty event requested dialogue bodies');},'r');
const factories={remote:makeRemote,indexed:rows=>I.create(Object.entries(rows).map(([id,row])=>[id,JSON.stringify(row)])),plain:rows=>JSON.parse(JSON.stringify(rows))};

// Execute the actual form expressions: a new event has no existing membership
// to search, while explicit entries and existing-event fallbacks still apply.
const opening=source.match(/\$\{(talkOptions\(ids\(e\.talkId\)\[0\][\s\S]*?)\.replace\('结束这段对话'/);
assert(opening,'event form entry expression is present');
const submission=source.match(/const title=\$\('#event-title'\)[^;]+;/);
assert(submission,'event form submit fields are present');
for(const {creation,entry,selected,expected,calls} of [
 {creation:{type:1},entry:[],selected:'0',expected:0,calls:0},
 {creation:{type:1,entry:8},entry:[8],selected:'0',expected:8,calls:0},
 {creation:{type:1},entry:[],selected:'9',expected:9,calls:0},
 {creation:null,entry:[],selected:'0',expected:4,calls:1},
]){
 let scans=0;const fields={'#event-title':{value:'测试事件'},'#event-first':{value:selected}};
 const form={creation,e:{talkId:entry},ids,talkOptions:value=>value,firstOwnedEventTalk:()=>{scans++;return 4;},$:selector=>selector==='#event-first-female'?null:fields[selector]||{value:'0'}};
 vm.createContext(form);vm.runInContext(submission[0]+'globalThis.first=first;',form);
 assert.equal(form.first,expected);assert.equal(scans,calls,'creating an event must not search existing membership');
 scans=0;const opened=vm.runInContext(opening[1],form);
 assert.equal(opened,entry[0]||(creation?0:4));assert.equal(scans,entry[0]||creation?0:1);
}

for(const [kind,make] of Object.entries(factories)){
 const table=make(records);let reads=0;const talks=new Proxy(table,{get:(target,key)=>{if(typeof key==='string'&&/^\d+$/.test(key))reads++;return Reflect.get(target,key);}});
 const S={doc:{talks,talkOwners:Object.fromEntries(Object.keys(records).map(id=>[id,[1]]))},order:[1,3,7,4,8,9,10],branchFolders:{condition:{kind:'condition',parentTalkId:1,branchId:1,routerId:3,talkIds:[4],exitId:9,endId:10}},catalogTalkIds:new Set([8])};
 let shown=new Set();const box={S,Timeline,ids,values:value=>Object.values(value||{}),shownWith:()=>new Set(shown)};
 vm.createContext(box);vm.runInContext(take('function firstOwnedEventTalk(', 'function eventDetails(')+take('function conditionFolderIndex(', 'function blockEnd(')+take('function eventTraversal(', 'function localStoryIds('),box);
 assert.equal(box.firstOwnedEventTalk({id:1000000}),0);assert.equal(reads,0,kind+' empty entry must not instantiate foreign rows');
 // The first valid visible line follows S.order. Internal routing rows are
 // filtered before accessing the table; deleted candidates still fall through.
 shown=new Set([3,7,4,8]);assert.equal(box.firstOwnedEventTalk({id:1}),4);assert.equal(reads,2);
 delete table[4];reads=0;assert.equal(box.firstOwnedEventTalk({id:1}),8);assert.equal(reads,3);
 table[4]={id:4,content:'恢复的分支正文'};shown=new Set([8,4]);reads=0;assert.equal(box.firstOwnedEventTalk({id:1}),4);assert.equal(reads,1);
 reads=0;assert.deepEqual(Array.from(box.eventTraversal(1000000)),[]);assert.equal(reads,0,kind+' empty renumber traversal must not instantiate foreign rows');
 assert.deepEqual(Array.from(box.eventTraversal(1)),[1,3,4,9,10],'normal router/body/exit/end order and catalog filtering remain intact');
 if(kind==='remote')assert.equal(R.stats(table).loaded,0);if(kind==='indexed')assert.equal(I.stats(table).decoded<=64,true);
}

// The post-create ownership pass already has the set of real talk keys. Use it
// for retained and anchored ownership, including shared routes and missing IDs.
globalThis.StudentAgeRemoteTalks=R;
const rows={1:{id:1,content:'甲',nextTalk:[3]},2:{id:2,content:'乙',nextTalk:[3]},3:{id:3,content:'共用'},4:{id:4,content:'保留',nextTalk:[5]},5:{id:5,content:'后续'},9:{id:9,content:'新归属'}};
const events={1:{id:1,talkId:[1]},2:{id:2,talkId:[2]},1000000:{id:1000000,talkId:[]}},previous={4:[1],5:[1],9:[2],777:[1]},anchor=[9,777];
let table=makeRemote(rows),reads=0;const monitored=new Proxy(table,{get:(target,key)=>{if(typeof key==='string'&&/^\d+$/.test(key))reads++;return Reflect.get(target,key);}});
globalThis.StudentAgeRemoteTalks={...R,info:value=>R.info(value===monitored?table:value)};
const expected=Ownership.ownership({talks:rows,events,options:{}},{},previous,anchor),actual=Ownership.ownership({talks:monitored,events,options:{}},{},previous,anchor);
assert.deepEqual(actual,expected);assert.deepEqual(actual[3],[1,2]);assert.deepEqual(actual[4],[1]);assert.deepEqual(actual[9],[2]);assert.equal(actual[777],undefined);assert.equal(reads,0);assert.equal(R.stats(table).loaded,0);

// A real large, unloaded directory catches the original three cold-table
// allocations together: entry lookup, ownership sync, and scheduled renumber.
const size=250000,large={};for(let id=1;id<=size;id++)large[id]={id,content:'隔离摘要 '+id,nextTalk:[],nextTalk2:[],option:[]};
table=makeRemote(large);reads=0;
const largeProxy=new Proxy(table,{get:(target,key)=>{if(typeof key==='string'&&/^\d+$/.test(key))reads++;return Reflect.get(target,key);}});
const owners=Object.fromEntries(Object.keys(large).map(id=>[id,[1]])),doc={talks:largeProxy,events,options:{},talkOwners:owners};
let orderReads=0;const order=new Proxy(Object.keys(large).map(Number),{get:(target,key)=>{if(typeof key==='string'&&/^\d+$/.test(key))orderReads++;return Reflect.get(target,key);}});
const S={doc,order,event:1000000,search:'',branchFolders:{},catalogTalkIds:new Set()},box={S,Timeline,ids,externalSession:null,values:value=>Object.values(value||{}),shownWith:()=>new Set()};
vm.createContext(box);vm.runInContext(take('function firstOwnedEventTalk(', 'function eventDetails(')+take('function conditionFolderIndex(', 'function blockEnd(')+take('function eventTraversal(', 'function localStoryIds(')+take('function visibleIds(', 'let searchSequence='),box);
globalThis.StudentAgeRemoteTalks={...R,info:value=>R.info(value===largeProxy?table:value)};
const plainExpected=Ownership.ownership({talks:large,events,options:{}},{},owners);
global.gc?.();const memory=process.memoryUsage().heapUsed,start=performance.now();
assert.equal(box.firstOwnedEventTalk(events[1000000]),0);assert.equal(orderReads,0,'empty entry must skip even the order scan');
const display=Ownership.sync(doc,{},1000000,new Set(Object.keys(large)));
let ownerReads=0;doc.talkOwners=new Proxy(doc.talkOwners,{get:(target,key)=>{if(typeof key==='string'&&/^\d+$/.test(key))ownerReads++;return Reflect.get(target,key);}});
assert.deepEqual(Array.from(box.eventTraversal(1000000)),[]);assert.equal(ownerReads,size);assert.equal(orderReads,size,'empty renumber uses one linear ownership scan');
assert.deepEqual(Array.from(box.visibleIds()),[]);assert.equal(orderReads,size*2,'post-create visibility uses one additional linear order scan');
assert.equal(reads,0);assert.equal(R.stats(table).loaded,0);
const report={status:'passed',checks:'Create/edit form entry expressions; Remote/Indexed empty entry and traversal; ordered valid entry, internal/missing filtering; shared, retained and anchored ownership; 250k post-create sync, renumber and visibility',large:{talks:size,rowReads:reads,ownerReads,orderReads,loadedBodies:R.stats(table).loaded,ms:Number((performance.now()-start).toFixed(2)),heapGrowthWithinSynchronousCallMiB:Number(((process.memoryUsage().heapUsed-memory)/1048576).toFixed(2))}};
assert.deepEqual(doc.talkOwners,plainExpected);assert(!Object.values(display).some(owners=>owners.includes(1000000)));
globalThis.StudentAgeRemoteTalks=R;console.log(JSON.stringify(report,null,2));
const index=process.argv.indexOf('--evidence');if(index>=0){const output=path.resolve(process.argv[index+1]);fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');}
