'use strict';
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm'),path=require('path'),R=require('../remote-talks.js'),I=require('../indexed-talks.js');
const source=fs.readFileSync(path.join(__dirname,'../events.js'),'utf8');
const code="const ids=v=>(Array.isArray(v)?v:[]).map(Number).filter(Number.isFinite);\n"+source.slice(source.indexOf('function links('),source.indexOf('function eventRows('))+'\nthis.counter=dialogueCounter;';
const context={window:{StudentAgeRemoteTalks:R,StudentAgeIndexedTalks:I}};vm.runInNewContext(code,context);
const rows={1:{id:1,content:'第一句',nextTalk:[2]},2:{id:2,content:'第二句',option:[5]},3:{id:3,content:'第三句',nextTalk:[1]},4:{id:4,content:'第四句'}};
const descriptor={version:1,generation:'counts',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content,hasText:true}]))};
const talks=R.create(descriptor,()=>{throw Error('count requested body');},'r');const doc={talks,options:{5:{id:5,talkId:[3]}}};
assert.equal(context.counter(doc)([1]),3);assert.equal(context.counter(doc)([4]),1);
// Cached count stays valid on text edits; no body read is needed.
talks[1].content='改过台词';assert.equal(context.counter(doc)([1]),3);assert.equal(R.stats(talks).loaded,0);
// Nested edges/options, removal, roots and undo must invalidate correctly.
talks[1].nextTalk.splice(0,1);assert.equal(context.counter(doc)([1]),1);
talks[1].nextTalk.push(2);doc.options[5].talkId=[4];assert.equal(context.counter(doc)([1]),3);
delete talks[4];assert.equal(context.counter(doc)([1]),2);
const clone=I.clone(talks);clone[1].nextTalk=[];assert.equal(context.counter({...doc,talks:clone})([1]),1);assert.equal(context.counter(doc)([1]),2);
assert.equal(context.counter({talks:rows,options:{5:{id:5,talkId:[3]}}})([1]),3);
globalThis.StudentAgeRemoteTalks=R;const C=require('../conditions.js'),E=require('../effects.js');
const template={label:'对话引用',template:[9,2],match:{0:9},parameters:[{index:1,range:{table:'TalkCfg'}}]};assert(C.summary([[9,2]],[template],{TalkCfg:talks}).includes('第二句'));
assert.equal(R.stats(talks).loaded,0);
console.log('EVENT_LIST_GRAPH_CACHE_AND_UNLOADED_LABELS_OK');
(async()=>{
 let callback,requests=0,batch;
 globalThis.IntersectionObserver=class{constructor(fn){callback=fn;}observe(){}disconnect(){}};
 const nodes=Array.from({length:4},(_,i)=>({id:String(i+1),isConnected:true,dataset:{},textContent:'摘要'}));
 const container={querySelectorAll:()=>nodes};
 const remote=R.create({...descriptor,generation:'labels'},async(_,body)=>{requests++;batch=body.ids;return {generation:'labels',revision:'r',rows:body.ids.map(id=>[id,JSON.stringify(rows[id])]),remaining:[]};},'r');
 R.observeLabels(container,remote,'.label',node=>node.id);callback(nodes.map(target=>({target,isIntersecting:true})));
 await new Promise(r=>setTimeout(r,5));assert.equal(requests,1);assert.deepEqual(batch,['1','2','3','4']);assert.equal(nodes[1].textContent,'第二句');
 callback([{target:nodes[1],isIntersecting:false}]);assert.equal(nodes[1].textContent,'摘要');
 console.log('EVENT_LABEL_BATCH_OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
