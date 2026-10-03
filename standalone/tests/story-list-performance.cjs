'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const Ownership=require('../event-ownership.js'),Timeline=require('../timeline.js');
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const take=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b));
// Reuse the exact visibility map computed during synchronization, including
// disconnected prefix matches and shared/event-external references.
const doc={talks:{1001:{id:1001,nextTalk:[1002]},1002:{id:1002},1003:{id:1003},9001:{id:9001,nextTalk:[1001]},2001:{id:2001,nextTalk:[1002]},77:{id:77}},events:{1:{id:1,talkId:[1001]},2:{id:2,talkId:[2001]}},options:{},talkOwners:{77:[1]}};
const shown=Ownership.sync(doc,{},1,new Set(Object.keys(doc.talks)));
assert.deepEqual(shown,Ownership.display(doc,{}));assert.deepEqual(doc.talkOwners[1002],[1,2]);assert.deepEqual(doc.talkOwners[77],[1]);assert(shown[1003].includes(1));assert(shown[9001].includes(1));
let reads=0,displayCalls=0;const data={};for(let i=1;i<=43827;i++)data[i]={id:i,content:'内容'+i,roleIds:[]};
const allowed=new Set(Array.from({length:250},(_,i)=>i+1)),folders={'2:branch:1':{kind:'condition',parentTalkId:2,branchId:1,routerId:3,exitId:4,endId:5,talkIds:[]}},order=Object.keys(data).map(Number);
const S={doc:{talks:new Proxy(data,{get:(t,k)=>{reads++;return t[k];}}),events:{1:{id:1}},talkOwners:Object.fromEntries([...allowed].map(id=>[id,[1]]))},branchFolders:folders,order,event:1,search:''};
const callbacks=[],context={S,Timeline,externalSession:null,queueMicrotask:fn=>callbacks.push(fn),StudentAgeEventOwnership:{display:()=>{displayCalls++;return Object.fromEntries([...allowed].map(id=>[id,[1]]));}},Remote:{info:()=>null},StudentAgeSearch:{matches:(q,...args)=>args.some(x=>String(x).includes(q))},speaker:()=>'',talkText:t=>t.content};
vm.createContext(context);vm.runInContext(take('let displayMemo=null;', 'let searchSequence='),context);
const expected=order.filter(id=>data[id]&&!Timeline.internals(folders).has(id)).filter(id=>allowed.has(id));
assert.deepEqual(Array.from(context.visibleIds()),expected);assert.equal(reads,expected.length);assert.equal(displayCalls,1);
assert.deepEqual(Array.from(context.visibleIds()),expected);assert.equal(displayCalls,1);
// Sync results replace the memo immediately; microtask expiry keeps unrelated
// edits from reusing a stale graph on the next browser task.
context.cacheEventDisplay({251:[1]});S.doc.talkOwners={251:[1]};assert.deepEqual(Array.from(context.visibleIds()),[251]);
callbacks.forEach(fn=>fn());context.visibleIds();assert.equal(displayCalls,2);
S.search='内容24';const result=Array.from(context.visibleIds());assert(result.every(id=>String(data[id].content).includes(S.search)));
console.log('story-list-performance: visibility and ownership reuse passed; '+expected.length+' row reads for 43827 talks');
