'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{performance}=require('node:perf_hooks');
const I=require('../indexed-talks.js'),root=path.join(__dirname,'..'),app=fs.readFileSync(path.join(root,'app.js'),'utf8');
let proxies=0,requests=0;
function CountedProxy(target,handler){proxies++;return new Proxy(target,handler);}CountedProxy.revocable=Proxy.revocable;
const remoteBox={module:{exports:{}},Proxy:CountedProxy,TextEncoder};vm.runInNewContext(fs.readFileSync(path.join(root,'remote-talks.js'),'utf8'),remoteBox);const R=remoteBox.module.exports;
const ids=value=>Array.isArray(value)?value.map(Number).filter(Number.isFinite):[],take=(a,b)=>app.slice(app.indexOf(a),app.indexOf(b));
const orderExpression=app.match(/const storedOrder=([^;]+);/)[1],graphSource=take('function links(t)', '// One render pass'),referencesSource=take('function talkReferenceView(', 'function folderDescription(');
const plain=value=>JSON.parse(JSON.stringify(value));
function make(rows){return R.create({version:1,generation:'load-order',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,row])=>[id,{record:row,fields:Object.keys(row),excerpt:'摘要 '+id,hasText:true}]))},()=>{requests++;throw Error('order/reference mount must not request bodies');},'r');}
function box(talks){const value={S:{doc:{talks,options:{7:{id:7,talkId:[3],talkId2:[4]}},events:{1:{id:1,talkId:[1]}}}},Remote:R,ids,values:value=>Object.values(value||{}),eventRoots:event=>ids(event.talkId),Proxy:CountedProxy};vm.createContext(value);vm.runInContext(graphSource+referencesSource,value);return value;}
const small={1:{id:1,nextTalk:[2],option:[7]},2:{id:2,nextTalk:[3]},3:{id:3,nextTalk:[1]},4:{id:4,nextTalk:[]}};
for(const talks of [plain(small),I.create(Object.entries(small).map(([id,row])=>[id,JSON.stringify(row)])),make(small)]){
 const b=box(talks);assert.deepEqual(Array.from(b.graphOrder([1,1,999])),[1,2,3,4]);
 b.data={order:[1,999,4,2]};assert.deepEqual(Array.from(vm.runInContext(orderExpression,b)),[1,4,2]);
 if(R.info(talks)){talks[2].nextTalk=[4];delete talks[3];assert.deepEqual(Array.from(b.graphOrder([1])),[1,2,4]);}
}
const b=box({}),base={9:{id:9,name:'原版',future:1},1:{id:1,name:'旧'}},local={1:{id:1,name:'本地',future:{keep:true}},3:{id:3,name:'新增'}};
const reference=b.talkReferenceView(base,local);assert.deepEqual(plain(Object.entries(reference)),Object.entries({...base,...local}));assert.strictEqual(reference[1],local[1]);assert.strictEqual(reference[9],base[9]);assert.equal(reference[999],undefined);assert.equal(Object.hasOwn(reference,'999'),false);assert.equal('toString' in reference,true);assert.equal(reference.toString(),'[object Object]');
const draft=make(small),live=b.talkReferenceView({3:{id:33,name:'保留原版'},10:{id:10}},draft);draft[2].future={keep:true};draft[2].nextTalk=[4];delete draft[3];draft[5]={id:55,nextTalk:[],future:{native:true}};
assert.strictEqual(live[2],draft[2]);assert.deepEqual(plain(live[2].future),{keep:true});assert.equal(live[3].id,33);assert.equal(live[5].id,55);assert.deepEqual(Object.keys(live),['1','2','3','4','5','10']);assert.equal(requests,0);

// Reproduce the old production storedOrder check, then execute the current
// production expression and complete initialOrder traversal on a true 500k
// Remote directory. Counting Proxy constructions observes retained handles
// without adding a production debug API.
const size=500000,fields=['id','nextTalk','content'],keys=[],summaries={};
for(let id=1;id<=size;id++){keys.push(String(id));summaries[id]={record:{id,nextTalk:id<size?[id+1]:[]},fields,excerpt:'摘要',hasText:true};}
const descriptor={version:1,generation:'large-load-order',ids:keys,summaries},makeLarge=()=>R.create(descriptor,()=>{requests++;throw Error('body read');},'r');
let baselineTable=makeLarge(),baseline=box(baselineTable);baseline.data={order:Array.from({length:size},(_,i)=>i+1).concat(size+1)};global.gc?.();proxies=0;
const baselineMemory=process.memoryUsage().heapUsed,startBaseline=performance.now(),oldOrder=vm.runInContext('ids(data.order).filter(id=>S.doc.talks[id])',baseline);
assert.equal(oldOrder.length,size);assert.equal(proxies,size);assert.throws(()=>assert.equal(proxies,0),'the old expression fails the zero-handle regression');
const old={proxyConstructions:proxies,ms:Number((performance.now()-startBaseline).toFixed(2)),heapGrowthWithinSynchronousCallMiB:Number(((process.memoryUsage().heapUsed-baselineMemory)/1048576).toFixed(2))};baseline=null;baselineTable=null;global.gc?.();
const table=makeLarge(),current=box(table);current.data={order:Array.from({length:size},(_,i)=>i+1).concat(size+1)};global.gc?.();proxies=0;
const memory=process.memoryUsage().heapUsed,start=performance.now(),ordered=vm.runInContext(orderExpression,current);assert.equal(ordered.length,size);assert.equal(proxies,0);
const initial=current.initialOrder();assert.equal(initial.length,size);assert.equal(initial[0],1);assert.equal(initial[size-1],size);assert.equal(proxies,1,'only the metadata routing view is allocated');
const newOrder={proxyConstructions:proxies,ms:Number((performance.now()-start).toFixed(2)),heapGrowthWithinSynchronousCallMiB:Number(((process.memoryUsage().heapUsed-memory)/1048576).toFixed(2))};

// Run the actual condition editor mount with empty rows. Complete references
// remain enumerable and selected rows stay intact, but mounting has no table
// enumeration or per-row allocation.
const conditionsBox={module:{exports:{}},window:{},StudentAgeRemoteTalks:R};vm.runInNewContext(fs.readFileSync(path.join(root,'conditions.js'),'utf8'),conditionsBox);const Conditions=conditionsBox.module.exports,captured=[];
Object.assign(current,{Conditions:{mount(node,options){captured.push(options.refs.TalkCfg);return Conditions.mount(node,options);}},allConditionTemplates:()=>[],mutate:()=>{},renderList:()=>{},scenePlayer:null});
Object.assign(current.S,{conditionRefs:{TalkCfg:{700001:{id:700001,name:'原版保留'}}},conditionLocalIds:{},conditionsLoading:false,project:{readOnly:false}});current.S.doc.events[1].condition=[];
const hosts=Array.from({length:2},()=>({dataset:{conditionScope:'events',conditionId:'1',conditionField:'condition',conditionDescription:''},classList:{add(){}},querySelectorAll:()=>[],isConnected:true}));proxies=0;current.mountConditionEditors({querySelectorAll:()=>hosts});assert.equal(proxies,2);assert.equal(captured.length,2);assert.equal(Object.keys(captured[0]).length,size+1);assert.equal(proxies,2,'enumerating IDs must not instantiate rows');assert.equal(captured[0][700001].name,'原版保留');assert.equal(captured[0][size].id,size);assert.equal(proxies,3,'one explicitly read Remote row gets one handle');assert.equal(requests,0);assert.equal(R.stats(table).loaded,0);
(async()=>{
 // Execute the complete production startup catalogue initializer as well as
 // mount: its TalkCfg merge formerly allocated every Remote row a second time.
 const catalogueRow={id:700001,name:'目录原版',future:{keep:true}};
 Object.assign(current,{conditionLoadSequence:0,storyPreview:true,window:{StudentAgeCommandTypes:{otherRelations:()=>({1:{id:1}})}},refreshConditionNotice:()=>{},preloadConditionCatalog:async()=>({data:{commands:{condition:[],effect:[]}},dataRefs:{tables:{TalkCfg:{rows:{700001:catalogueRow},localIds:[700001]},PersonCfg:{rows:{9:{id:9,name:'原版人物'}},localIds:[]}},errors:{}}})});
 Object.assign(current.S,{project:{id:'isolated-catalogue',readOnly:false},revision:'r',localIds:{talks:[1,2],events:[1],options:[7],persons:[3]},goalImageIds:[]});current.S.doc.persons={3:{id:3,name:'本地人物'}};
 vm.runInContext(take('async function loadConditionCatalog(', 'window.STUDIO_RETRY_CONDITIONS='),current);proxies=0;
 assert.equal(await current.loadConditionCatalog(),true);assert.equal(proxies,1,'catalogue initialization allocates only its merged reference view');
 assert.equal(current.S.conditionsLoading,false);assert.equal(Object.keys(current.S.conditionRefs.TalkCfg).length,size+1);assert.equal(proxies,1,'the complete catalogue remains enumerable without reading rows');assert.strictEqual(current.S.conditionRefs.TalkCfg[700001],catalogueRow);assert.equal(current.S.conditionRefs.TalkCfg[size].id,size);assert.equal(proxies,1,'explicitly cached row remains the same Remote handle');assert.deepEqual(Array.from(current.S.conditionLocalIds.TalkCfg),[1,2]);assert.equal(current.S.conditionRefs.PersonCfg[3].name,'本地人物');assert.equal(current.S.conditionRefs.PersonCfg[9].name,'原版人物');assert.equal(requests,0);assert.equal(R.stats(table).loaded,0);
 const report={status:'passed',checks:'Production graph/stored order Remote/plain/Indexed; nested overlay/delete; lazy references local precedence, complete enumeration, native id/unknown fields; actual Conditions.mount and complete loadConditionCatalog initialization without whole-table handles',large:{talks:size,oldStoredOrder:old,currentStoredAndInitialOrder:newOrder,conditionMountProxyConstructions:2,explicitRowProxyConstructions:1,catalogueInitializationProxyConstructions:1,bodyRequests:requests,loadedBodies:R.stats(table).loaded}};
 console.log(JSON.stringify(report,null,2));const at=process.argv.indexOf('--evidence');if(at>=0){const file=path.resolve(process.argv[at+1]);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(report,null,2)+'\n');}
})().catch(error=>{console.error(error);process.exitCode=1;});
