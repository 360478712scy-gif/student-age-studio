'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{performance}=require('node:perf_hooks');
const I=require('../indexed-talks.js'),root=path.join(__dirname,'..');
let proxies=0,requests=0;
function CountedProxy(target,handler){proxies++;return new Proxy(target,handler);}
CountedProxy.revocable=Proxy.revocable;
const remoteBox={module:{exports:{}},Proxy:CountedProxy,TextEncoder};
vm.runInNewContext(fs.readFileSync(path.join(root,'remote-talks.js'),'utf8'),remoteBox);
const R=remoteBox.module.exports,sceneBox={window:{},StudentAgeRemoteTalks:R,setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(path.join(root,'scene.js'),'utf8'),sceneBox);
const Scene=sceneBox.window.StudentAgeScene,plain=value=>JSON.parse(JSON.stringify(value));
function makeRemote(rows){return R.create({version:1,generation:'routing',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content||'',hasText:!!content}]))},async(_,body)=>{requests++;return {generation:'routing',revision:'r',rows:body.ids.map(id=>[id,JSON.stringify(rows[id])]),remaining:[]};},'r');}
const rows={
 1:{id:1,content:'入口',nextTalk:[2],roleIds:[3],roles:[[3,1002,1,1]]},
 2:{id:2,content:'前一幕',nextTalk:[3],roles:[[3,3004,100,0,0]]},3:{id:3,content:'目标正文'},4:{id:4,content:'草稿'},
 10:{id:10,option:[100]},11:{id:11,nextTalk:[13]},12:{id:12,nextTalk:[13]},
 13:{id:13,check:[[7001]],nextTalk:[14,15],nextTalk2:[16,17]},
 14:{id:14,nextTalk:[18]},15:{id:15,nextTalk:[18]},16:{id:16,nextTalk:[18]},17:{id:17,nextTalk:[18]},
 18:{id:18,miniGame:[1],nextTalk:[19]},19:{id:19},
 30:{id:30},31:{id:31,check:[[7001]]},32:{id:32,nextTalk:[33]},33:{id:33,nextTalk:[35]},34:{id:34},35:{id:35},36:{id:36},
 37:{id:37},38:{id:38,nextTalk:[39]},39:{id:39,nextTalk:[35]},40:{id:40},99:{id:99},
};
const options={100:{id:100,content:'通过',check:[[7001]],talkId:[11],talkId2:[12]},101:{id:101,talkId:[4]}};
const branchFolders={first:{kind:'condition',parentTalkId:30,branchId:1,routerId:31,talkIds:[32],exitId:33,endId:34,baseNext:[35],failureNext:[36]},second:{kind:'condition',parentTalkId:30,branchId:2,routerId:37,talkIds:[38],exitId:39,endId:40,baseNext:[35]}};
const doc={talks:rows,options,branchFolders,events:{1:{id:1,talkId:[1]}},persons:{3:{id:3,name:'人物'}},faces:{},backgrounds:{},protagonistGender:1};
const remote=makeRemote(rows),view=R.routingTable(remote),remoteDoc={...doc,talks:remote},viewDoc={...doc,talks:view};
function parity(){
 for(const [target,roots] of [[3,[1]],[3,[99]],[11,[10]],[12,[10]],[16,[10]],[17,[10]],[19,[10]],[35,[30]],[36,[30]],[40,[99]],[999,[1]]]){
  const expected=plain(Scene.pathTo(doc,target,roots));
  assert.deepEqual(plain(Scene.pathTo(viewDoc,target,roots)),expected);
  assert.deepEqual(plain(Scene.pathTo(remoteDoc,target,roots)),expected,'native Remote path parity');
 }
 for(const id of Object.keys(rows))assert.deepEqual(plain(Scene.routes(viewDoc,view[id])),plain(Scene.routes(doc,rows[id])),'all route fields '+id);
}
parity();assert.deepEqual(plain(Scene.pathTo(viewDoc,3,[1])),{path:[1,2,3],found:true});
assert.equal(Scene.pathTo(viewDoc,3,[99]).inferred,true);assert.equal(requests,0);
// The view stays live across nested edits, deleted fields/rows and added drafts.
remote[2].nextTalk=[4];rows[2].nextTalk=[4];remote[4].nextTalk=[3];rows[4].nextTalk=[3];
remote[10].option.push(101);rows[10].option.push(101);delete remote[11];delete rows[11];
delete remote[13].check;delete rows[13].check;delete remote[31].check;delete rows[31].check;
remote[18].miniGame=[];rows[18].miniGame=[];remote[41]={id:41,nextTalk:[3],content:'新增',future:{keep:true}};rows[41]={id:41,nextTalk:[3],content:'新增',future:{keep:true}};
parity();assert.equal(view[11],undefined);assert.deepEqual(plain(view[41].nextTalk),[3]);
assert.deepEqual(Object.keys(view),Object.keys(remote));assert.equal(view[3].content,undefined);assert.equal(requests,0);
assert.strictEqual(R.routingTable(rows),rows,'plain table is unchanged');
const indexed=I.create(Object.entries(rows).map(([id,row])=>[id,JSON.stringify(row)]));
assert.strictEqual(R.routingTable(indexed),indexed,'Indexed table is unchanged');
assert.deepEqual(plain(Scene.pathTo({...doc,talks:indexed},3,[1])),plain(Scene.pathTo(doc,3,[1])));

// Execute currentStage itself: only pathTo receives the routing view. The
// existing ready/unready reconstruction model and authored trace remain intact.
const app=fs.readFileSync(path.join(root,'app.js'),'utf8'),stageSource=app.slice(app.indexOf('function currentStage('),app.indexOf('function presentRoles('));
for(const ready of [false,true]){
 const talkTable=makeRemote(rows);if(ready)talkTable[3].content='选中正文';
 let reconstructionTable,pathCalls=0,reconstructCalls=0;
 const adapter={...R,sceneTable(value,selected){reconstructionTable=R.sceneTable(value,selected);return reconstructionTable;}};
 const stageScene={...Scene,pathTo(model,target,roots){pathCalls++;assert.notStrictEqual(model.talks,talkTable);assert.equal(model.talks[3].content,undefined);return Scene.pathTo(model,target,roots);},reconstruct(model,target,context){reconstructCalls++;assert.strictEqual(model.talks,ready?talkTable:reconstructionTable);assert.deepEqual(Array.from(context.trace),[1,2,4,3]);return {trace:context.trace,roles:{},warnings:[]};}};
 const box={window:{StudentAgeScene:stageScene},StudentAgeScene:stageScene,Remote:adapter,S:{doc:{...doc,talks:talkTable},selected:3,event:1,grade:1,branchFolders},scenePlayer:null,stageMemo:[],stageMemoQueued:false,sceneContext:()=>({roots:[1]}),queueMicrotask:()=>{},invalidateStageMemo:()=>{}};
 vm.runInNewContext(stageSource,box);assert.deepEqual(Array.from(box.currentStage().trace),[1,2,4,3]);assert.equal(pathCalls,1);assert.equal(reconstructCalls,1);
}

// A genuine unloaded 250k directory must reach the fallback without retaining
// 250k row/nested proxies or requesting any dialogue body. Count production
// Proxy constructions in a VM; no production debug API is needed.
const size=250000,large={};for(let id=1;id<=size;id++)large[id]={id,content:'未加载正文 '+id,nextTalk:id===1?[2]:[]};
const largeTable=makeRemote(large);global.gc?.();const before=process.memoryUsage().heapUsed,start=performance.now();proxies=0;
const route=Scene.pathTo({talks:R.routingTable(largeTable),options:{},branchFolders:{}},2,[size]);
assert.deepEqual(plain(route),{path:[1,2],found:true,inferred:true});assert.equal(proxies,1,'only the routing view is a Proxy');
assert.equal(requests,0);assert.equal(R.stats(largeTable).loaded,0);
const report={status:'passed',checks:'Remote native-path parity; normal roots and inferred predecessors; router/exit/option/check/miniGame; live nested overlay/field deletion/row deletion/new rows; plain/Indexed identity; actual currentStage reconstruction model/trace',large:{talks:size,proxyConstructions:proxies,bodyRequests:requests,loadedBodies:R.stats(largeTable).loaded,ms:Number((performance.now()-start).toFixed(2)),heapGrowthWithinSynchronousCallMiB:Number(((process.memoryUsage().heapUsed-before)/1048576).toFixed(2))}};
console.log(JSON.stringify(report,null,2));const at=process.argv.indexOf('--evidence');if(at>=0){const file=path.resolve(process.argv[at+1]);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(report,null,2)+'\n');}
