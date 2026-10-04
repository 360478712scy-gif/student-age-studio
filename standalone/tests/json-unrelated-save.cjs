'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const Indexed=require('../indexed-talks.js'),Remote=Indexed.Remote,Ownership=require('../event-ownership.js');
const source=fs.readFileSync(process.env.STUDIO_TEST_APP_SOURCE||path.join(__dirname,'../app.js'),'utf8');
const keys=source.slice(source.indexOf('const jsonStoryKeys='),source.indexOf('\n',source.indexOf('const jsonStoryKeys=')));
const bridge=source.slice(source.indexOf('window.STUDIO_STORY_JSON={'),source.indexOf('window.STUDIO_CURRENT_REVISION='));
const plain=value=>JSON.parse(JSON.stringify(value));
function harness(talks){
 const counts={ownership:0,cleanup:0,external:0,renumber:0},history=[];
 const S={doc:{talks,options:{},events:{10:{id:10,talkId:[1]}},talkOwners:{1:[10]},giftEvents:{20:{id:20,talkId:[[1,2]],type:[0],future:{keep:true}}},persons:{30:{id:30,name:'人物',future:{keep:true}}}},order:[1,2],branchFolders:{},replacements:{},premises:{},pinned:{talks:new Set(),options:new Set()},localIds:{talks:[1,2],events:[10],giftEvents:[20],persons:[30]},event:10,selected:1,revision:'old',deferredProject:false};
 S.saved=Indexed.stringify([S.doc,S.order]);
 const context={window:{STUDIO_EVENTS:{refresh(){}}},S,IndexedTalks:Indexed,Remote,jsonSegment:()=>null,clone:Indexed.clone,editable:()=>true,
  localStoryIds:key=>new Set(S.localIds[key]||[]),history:()=>history.push(Indexed.clone(S.doc)),Branches:{cleanup:(doc,folders)=>{counts.cleanup++;return folders;}},
  StudentAgeEventOwnership:{sync:(...args)=>{counts.ownership++;return Ownership.sync(...args);}},syncExternal:()=>counts.external++,updateDirty:()=>{S.dirty=Indexed.stringify([S.doc,S.order])!==S.saved;},render(){},renderChrome(){},visibleIds:()=>[1],runRenumber:async()=>{counts.renumber++;return true;}};
 vm.createContext(context);vm.runInContext(keys+'\n'+bridge,context);return {S,counts,history,api:context.window.STUDIO_STORY_JSON};
}
(async()=>{
 // The large table is genuinely unloaded. Non-graph JSON writes must not build
 // an ownership graph or materialize any dialogue body to update another table.
 const n=250000,summaries={};for(let i=1;i<=n;i++)summaries[i]={record:{id:i,nextTalk:[]},fields:['id','nextTalk','content'],excerpt:'已有对话',hasText:true};
 let requests=0;const talks=Remote.create({version:1,generation:'json-save',ids:Object.keys(summaries),summaries},async()=>{requests++;throw Error('unrelated save requested dialogue bodies');},'old');
 const large=harness(talks),owners=large.S.doc.talkOwners;
 const gift=plain(large.api.read('GiftEvtCfg'));gift[20].type=[1];await large.api.write('GiftEvtCfg',gift);large.api.saved('GiftEvtCfg',gift,'gift-saved');
 assert.deepEqual(plain(large.S.doc.giftEvents[20]),{id:20,talkId:[[1,2]],type:[1],future:{keep:true}});assert.equal(large.S.revision,'gift-saved');assert.equal(large.S.dirty,false);
 const people=plain(large.api.read('PersonCfg'));people[30].name='改名';await large.api.write('PersonCfg',people);large.api.saved('PersonCfg',people,'person-saved');
 assert.equal(large.S.doc.persons[30].name,'改名');assert.deepEqual(plain(large.S.doc.persons[30].future),{keep:true});assert.equal(large.S.dirty,false);
 assert.equal(large.S.doc.talkOwners,owners);assert.deepEqual(large.counts,{ownership:0,cleanup:0,external:0,renumber:0});assert.equal(requests,0);assert.equal(Remote.stats(talks).loaded,0);
 assert.equal(large.history[0].giftEvents[20].type[0],0);assert.equal(large.history[1].persons[30].name,'人物');
 // Actual dialogue, branch and event changes still follow the graph path.
 const small=harness({1:{id:1,content:'一',nextTalk:[2]},2:{id:2,content:'二',nextTalk:[]}});
 const rows=plain(small.api.read('TalkCfg'));rows[3]={id:3,content:'新行',nextTalk:[]};await small.api.write('TalkCfg',rows);
 assert.deepEqual(small.counts,{ownership:1,cleanup:1,external:1,renumber:0});assert.equal(small.S.order.includes(3),true);assert.equal(small.S.pinned.talks.has(3),true);assert.deepEqual(plain(small.S.doc.talkOwners[3]),[10]);
 const events=plain(small.api.read('EvtCfg'));events[11]={id:11,talkId:[3]};await small.api.write('EvtCfg',events);assert.equal(small.counts.ownership,2);assert.deepEqual(plain(small.S.doc.talkOwners[3]),[11]);
 console.log('JSON_UNRELATED_SAVE_OK (250k unloaded rows, Gift/Person writes and saved baseline, history, graph changes)');
})().catch(error=>{console.error(error);process.exitCode=1;});
