'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{performance}=require('node:perf_hooks');
const R=require('../remote-talks.js'),I=require('../indexed-talks.js'),Timeline=require('../timeline.js'),Branches=require('../branches.js'),Ownership=require('../event-ownership.js');
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8'),take=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b));
const ids=value=>Array.isArray(value)?value.map(Number).filter(Number.isFinite):[],copy=value=>JSON.parse(JSON.stringify(value));
globalThis.StudentAgeRemoteTalks=R;
const makeRemote=rows=>R.create(copy({version:1,generation:'delete-event',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content,hasText:!!content}]))}),()=>{throw Error('deleting an event requested dialogue bodies');},'r');
const factories={remote:makeRemote,indexed:rows=>I.create(Object.entries(rows).map(([id,row])=>[id,JSON.stringify(row)])),plain:copy};
// Rows holding a draft. An edited row is compared again by every later history snapshot and
// unsaved-change check, so a whole table of them is what keeps the editor slow after one edit.
const edited={
 remote:table=>{const info=R.info(table);return info.keys().filter(id=>{const e=info.stateFor(id);return Object.keys(e.set).length||e.remove.length;}).map(Number);},
 indexed:(table,expected)=>I.stats(table).edited===expected.length?expected:I.stats(table).edited,
 plain:(table,expected,before)=>Object.keys(table).map(Number).filter(id=>JSON.stringify(table[id])!==JSON.stringify(before[id])),
};
const link=(table,id,key)=>ids(table[id][key]);

// The real deleteEvents body. replaceEdges is deliberately absent: repairing links once per
// deleted line rewrote the whole table each time.
function studio(doc,state={}){
 const notes=[],S={doc,branchFolders:{},catalogTalkIds:new Set(),premises:{},deleted:[],replacements:{},order:Object.keys(doc.talks).map(Number),event:1,selected:1001,activeFolder:null,...state};
 const box={S,ids,values:value=>Object.values(value||{}),Timeline,Branches,StudentAgeEventOwnership:Ownership,StudentAgeEventBindings:{clearSocialBindings(){}},editable:()=>true,toast:text=>notes.push(text),removePremises:()=>{},mutate:(label,change)=>{change();return true;},window:{},notes};
 vm.createContext(box);vm.runInContext(take('function deleteEvents(','function deleteEvent('),box);return box;
}

const talks={
 1001:{id:1001,content:'甲一',nextTalk:[1002]},1002:{id:1002,content:'甲二',nextTalk:[1003],option:[100101,100102]},1003:{id:1003,content:'甲三'},1004:{id:1004,content:'专属选项后',nextTalk:[1003]},
 2001:{id:2001,content:'乙一',nextTalk:[2002],option:[100102]},2002:{id:2002,content:'乙二'},
 9001:{id:9001,content:'未归属',nextTalk:[1002],nextTalk2:[1003,2001]},
};
for(const [kind,make] of Object.entries(factories)){
 const table=make(talks),doc={talks:table,audioCues:{sfx:{1001:[1],2001:[2]},bgm:[{id:1,talkIds:[1001,2001]},{id:2,talkIds:[1002]}]},eventGrades:{1:1},
  options:{100101:{id:100101,content:'专属',talkId:[1004]},100102:{id:100102,content:'共用',talkId:[2002]},900001:{id:900001,content:'孤立',talkId:[1003],talkId2:[1002,2002]},900002:{id:900002,content:'跳转',talkId:[],nextEvtId:1}},
  events:{1:{id:1,title:'甲',talkId:[1001]},2:{id:2,title:'乙',talkId:[2001]}},
  actionEvents:{1:{id:1,evts:[1,2]},2:{id:2,evts:[2]}},actions:{1:{id:1,evtId:1},2:{id:2,evtId:2}},interactions:{5:{id:5,talkId:1001},6:{id:6,talkId:2001}}};
 const keptEvents=doc.actionEvents[2].evts,sharedOption=copy(doc.options[100102]),jump=copy(doc.options[900002]);
 const box=studio(doc,{branchFolders:{'2001:100102':{parentTalkId:2001,optionId:100102,talkIds:[2002],continuation:{kind:'talk',talkId:1003}}}}),S=box.S;
 assert.equal(box.deleteEvents([1]),true);
 assert.deepEqual(Object.keys(table).map(Number),[2001,2002,9001],kind+': only dialogue owned solely by the event is removed');
 assert.deepEqual([link(table,9001,'nextTalk'),link(table,9001,'nextTalk2')],[[],[2001]],kind+': links into removed lines are dropped');
 assert.deepEqual([link(table,2001,'nextTalk'),link(table,2001,'option')],[[2002],[100102]]);
 assert.deepEqual(edited[kind](table,[9001],talks),[9001],kind+': rows that never pointed at a removed line stay unedited');
 assert.deepEqual(Object.keys(doc.options).map(Number),[100102,900001,900002]);assert.deepEqual(copy(doc.options[100102]),sharedOption);assert.deepEqual(copy(doc.options[900002]),jump);
 assert.deepEqual([doc.options[900001].talkId,doc.options[900001].talkId2],[[],[2002]]);
 assert.deepEqual(Object.keys(doc.events),['2']);assert.deepEqual(copy(doc.eventGrades),{});
 assert.deepEqual(doc.actionEvents[1].evts,[2]);assert.equal(doc.actionEvents[2].evts,keptEvents,'unrelated action lists are not rewritten');
 assert.deepEqual([doc.actions[1].evtId,doc.actions[2].evtId],[0,2]);assert.deepEqual(Object.keys(doc.interactions),['6']);
 assert.deepEqual(copy(doc.audioCues),{sfx:{2001:[2]},bgm:[{id:1,talkIds:[2001]}]});
 assert.deepEqual(copy(S.deleted),[1001,1002,1003,1004]);assert.deepEqual(copy(S.replacements),{1001:[],1002:[],1003:[],1004:[]});assert.deepEqual(copy(S.order),[2001,2002,9001]);
 assert.deepEqual(copy(S.branchFolders),{'2001:100102':{parentTalkId:2001,optionId:100102,talkIds:[2002],continuation:{kind:'end'}}});
 assert.deepEqual([S.event,S.selected],[2,null]);assert.equal(box.notes.length,1);assert.match(box.notes[0],/跳转/);
 if(kind==='remote')assert.equal(R.stats(table).loaded,0);
}

// Reordering, moving a line and removing a dialogue folder share the same link repair.
const lane={1:{id:1,content:'一',nextTalk:[2]},2:{id:2,content:'二',nextTalk:[3]},3:{id:3,content:'三'},4:{id:4,content:'四',nextTalk:[5],nextTalk2:['2']},5:{id:5,content:'五'}};
const folderRows={1:{id:1,content:'提问',nextTalk:[5],option:[11]},2:{id:2,content:'夹内一',nextTalk:[3]},3:{id:3,content:'夹内二',nextTalk:[5]},5:{id:5,content:'之后'},6:{id:6,content:'旧跳转',nextTalk:[2]},7:{id:7,content:'无关',nextTalk:[5]},8:{id:8,content:'无关二'}};
const dragRows={1:{id:1,content:'一',nextTalk:[2]},2:{id:2,content:'二',nextTalk:[3]},3:{id:3,content:'三',nextTalk:[4]},4:{id:4,content:'四',nextTalk:[5]},5:{id:5,content:'五'},7:{id:7,content:'无关',nextTalk:[8]},8:{id:8,content:'无关二'}};
const moveRows={1:{id:1,content:'提问',nextTalk:[2],option:[11]},2:{id:2,content:'二',nextTalk:[3]},3:{id:3,content:'三',nextTalk:[4]},4:{id:4,content:'四'},7:{id:7,content:'无关',nextTalk:[8]},8:{id:8,content:'无关二'}};
for(const [kind,make] of Object.entries(factories)){
 let table=make(lane);const options={7:{id:7,talkId:[2]},8:{id:8,talkId:[5]}},untouched=options[8].talkId;
 const folders={a:{kind:'condition',baseNext:[2],failureNext:[4],continuation:{kind:'targets',targets:[2,5]}},b:{continuation:{kind:'talk',talkId:2}},c:{kind:'condition',baseNext:[5],continuation:{kind:'targets',targets:[5]}}},keptBase=folders.c.baseNext,keptTargets=folders.c.continuation.targets;
 Timeline.replace({talks:table,options,events:{}},folders,2,[3],new Set([2]));
 assert.deepEqual([link(table,1,'nextTalk'),link(table,2,'nextTalk'),link(table,4,'nextTalk'),link(table,4,'nextTalk2')],[[3],[3],[5],[3]],kind+': replace repairs every reference outside the exception');
 assert.deepEqual(edited[kind](table,[1,4],lane),[1,4],kind+': replace leaves unrelated rows unedited');
 assert.deepEqual(options[7].talkId,[3]);assert.equal(options[8].talkId,untouched);
 assert.deepEqual(folders.a,{kind:'condition',baseNext:[3],failureNext:[4],continuation:{kind:'targets',targets:[3,5]}});assert.deepEqual(folders.b.continuation,{kind:'talk',talkId:3});
 assert.equal(folders.c.baseNext,keptBase);assert.equal(folders.c.continuation.targets,keptTargets);

 table=make(folderRows);const doc={talks:table,options:{11:{id:11,content:'选项',talkId:[2]}},events:{}},optionFolders={'1:11':{parentTalkId:1,optionId:11,talkIds:[2,3],continuation:{kind:'following'}}};
 assert.deepEqual(Timeline.removeFolder(doc,optionFolders,'1:11'),{parentId:1,deleted:[2,3],replacements:{2:[5],3:[5]}});
 assert.deepEqual(Object.keys(table).map(Number),[1,5,6,7,8]);assert.deepEqual([link(table,1,'option'),link(table,1,'nextTalk'),link(table,6,'nextTalk'),link(table,7,'nextTalk')],[[],[5],[5],[5]]);
 assert.deepEqual(edited[kind](table,[1,6],folderRows),[1,6],kind+': removing a folder leaves unrelated rows unedited');
 assert.deepEqual(doc.options,{});assert.deepEqual(optionFolders,{});

 // Dragging a line: only the moved stretch and the line leading into it change.
 const drafted=(rows,now,allowed)=>kind==='remote'?edited.remote(now).every(id=>allowed.includes(id)):kind==='indexed'?I.stats(now).edited<=allowed.length:Object.keys(now).map(Number).every(id=>allowed.includes(id)||JSON.stringify(now[id])===JSON.stringify(rows[id]));
 table=make(dragRows);const dragged={talks:table,options:{},events:{}};
 assert.deepEqual(Timeline.reorder(dragged,{},[1,2,3,4,5,7,8],2,4,true),[1,3,4,2,5,7,8]);
 assert.deepEqual([1,3,4,2,7].map(id=>link(table,id,'nextTalk')),[[3],[4],[2],[5],[8]]);assert(drafted(dragRows,table,[1,2,3,4]),kind+': dragging leaves unrelated rows unedited');
 // Moving a line into an option's folder.
 table=make(moveRows);const moved={talks:table,options:{11:{id:11,content:'选项',talkId:[]}},events:{}},moveFolders={'1:11':{parentTalkId:1,optionId:11,talkIds:[],continuation:{kind:'following'}}};
 assert.deepEqual(Timeline.moveToFolder(moved,moveFolders,[1,2,3,4,7,8],3,'1:11'),[1,3,2,4,7,8]);
 assert.deepEqual([link(table,2,'nextTalk'),moved.options[11].talkId,moveFolders['1:11'].talkIds,link(table,7,'nextTalk')],[[4],[3],[3],[8]]);assert(drafted(moveRows,table,[2,3]),kind+': moving into a folder leaves unrelated rows unedited');
}

// A large unloaded directory: two 50-line events among 250k lines, with one outside line
// pointing into them. Whole-table passes must not grow with the number of deleted lines.
const size=250000,chain=50,large={};for(let id=1;id<=size;id++)large[id]={id,content:'隔离摘要 '+id,nextTalk:id%chain?[id+1]:[],nextTalk2:[],option:[]};
large[size+1]={id:size+1,content:'外部跳转',nextTalk:[10],nextTalk2:[],option:[]};
const events={};for(let id=1;id<=size/chain;id++)events[id]={id,title:'事件 '+id,talkId:[(id-1)*chain+1]};
const table=makeRemote(large);let passes=0;
const counted=new Proxy(table,{ownKeys:target=>{passes++;return Reflect.ownKeys(target);}});
globalThis.StudentAgeRemoteTalks={...R,info:value=>R.info(value===counted?table:value)};
const box=studio({talks:counted,options:{},events,actionEvents:{},actions:{},interactions:{},audioCues:{sfx:{},bgm:[]}},{order:[]});
global.gc?.();const memory=process.memoryUsage().heapUsed,start=performance.now();
assert.equal(box.deleteEvents([1,2]),true);
const ms=Number((performance.now()-start).toFixed(2)),heap=Number(((process.memoryUsage().heapUsed-memory)/1048576).toFixed(2));
globalThis.StudentAgeRemoteTalks=R;
assert.equal(box.S.deleted.length,chain*2);assert.equal(R.stats(table).total,size+1-chain*2);
assert(passes<10,'deleting '+chain*2+' lines used '+passes+' whole-table passes');
assert.deepEqual(edited.remote(table),[size+1],'one outside reference is one edited row');
assert.deepEqual(ids(table[size+1].nextTalk),[]);assert.equal(R.stats(table).changes,chain*2+1);assert.equal(R.stats(table).loaded,0);
console.log(JSON.stringify({status:'passed',checks:'Remote/Indexed/plain event deletion keeps shared lines and options, repairs outside references and leaves unrelated rows unedited; Timeline.replace, removeFolder, reorder and moveToFolder do the same; 250k unloaded directory',large:{talks:size+1,deletedLines:chain*2,wholeTablePasses:passes,editedRows:1,loadedBodies:0,ms,heapGrowthWithinSynchronousCallMiB:heap}},null,2));
