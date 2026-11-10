'use strict';
// Structural fields from original event 311001 (installed original-dialogue cache).
// No original dialogue text, art, project copies, player saves or live mods are used.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const B=require('../branches.js'),T=require('../timeline.js'),R=require('../remote-talks.js');
globalThis.StudentAgeRemoteTalks=R;
const root=path.join(__dirname,'..'),box={window:{StudentAgeBranches:B},setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(path.join(root,'scene.js'),'utf8'),box);
const Scene=box.window.StudentAgeScene,plain=v=>JSON.parse(JSON.stringify(v));
const A=311001003,C=311001004,roots=[311001001];
function original(){return {persons:{0:{id:0},111:{id:111}},backgrounds:{113:{id:113}},events:{311001:{id:311001,talkId:roots}},options:{},faces:{},cgs:{},branchFolders:{},talks:{
 311001001:{id:311001001,bg:113,roleIds:[-1],roles:[[0,1002,0,2,0]],nextTalk:[311001002],nextTalk2:[311001016],check:[[100,-10,10501],[7,1,105,50]]},
 311001002:{id:311001002,bg:0,roleIds:[0],roles:[],nextTalk:[A],nextTalk2:[],check:[]},
 311001003:{id:A,bg:0,roleIds:[111],roles:[[111,1002,0,1,0],[111,3007,0]],nextTalk:[C],nextTalk2:[],check:[]},
 311001004:{id:C,bg:0,roleIds:[0],roles:[],nextTalk:[311001005],nextTalk2:[],check:[]}
}};}
let id=900000001;
function branch(d,parent=A){const {folder:f}=T.addCondition(d,d.branchFolders,parent,()=>id++);T.insert(d,d.branchFolders,f,{id:id++,content:'fixture',roleIds:[111],roles:[],bg:0});T.setContinuation(d,d.branchFolders,f,{kind:'end'});return f;}
function edit(d,target=C){const route=Scene.pathTo(d,target,roots,{authoring:true});return Scene.reconstruct(d,target,{roots,trace:route.path,routeInfo:route});}
const cast=s=>Object.values(s.roles).filter(r=>r.visible).map(r=>r.id);
function restored(s){assert.equal(s.background,113);assert.deepEqual(cast(s),[0,111]);assert(s.warnings.some(x=>x.includes('保留的原路线')));}
let checks=0;function test(name,run){run();checks++;console.log('PASS '+name);}
test('original event mainline survives an unconditional ending branch in editor only',()=>{
 const d=original(),before=plain(d.talks[C]);const first=Scene.reconstruct(d,C,{roots});assert.equal(first.background,113);assert.deepEqual(cast(first),[0,111]);branch(d);
 const saved=JSON.stringify(d),native=Scene.pathTo(d,C,roots);assert.equal(native.inferred,true);assert.deepEqual(plain(native.path),[C]);
 restored(edit(d));assert.deepEqual(d.talks[C],before);assert.equal(JSON.stringify(d),saved);restored(edit(JSON.parse(saved)));
 const p=new Scene.Player({getDoc:()=>d,getContext:()=>({roots}),onRender:()=>{}});p.select(C);assert.equal(p.scene.background,0,'default Player route unchanged');
});
test('completed branch condition and normal continuation use real route first',()=>{
 const d=original(),f=branch(d);d.talks[f.routerId].check=[[1,1]];let s=edit(d);assert.equal(s.background,113);assert(!s.routeInfo.authoring);
 d.talks[f.routerId].check=[];T.setContinuation(d,d.branchFolders,f,{kind:'following'});s=edit(d);assert.equal(s.background,113);assert(!s.routeInfo.authoring);
});
test('later hidden and nested branches remain inspectable without offering extra playback choices',()=>{
 const d=original(),first=branch(d),second=branch(d),nested=branch(d,second.talkIds[0]),target=nested.talkIds[0];
 assert.equal(Scene.routes(d,d.talks[A]).length,1);assert.equal(Scene.routes(d,d.talks[A])[0].id,first.talkIds[0]);
 const s=edit(d,target);assert.equal(s.background,113);assert(s.routeInfo.authoring);assert(s.trace.includes(second.talkIds[0]));
});
test('stale sidecar cannot resurrect an old mainline',()=>{
 const d=original(),f=branch(d);d.talks[A].nextTalk=[f.talkIds[0]];
 const route=Scene.pathTo(d,C,roots,{authoring:true});assert(!route.authoring);assert.equal(edit(d).background,0);
});
test('undo and redo snapshots, disconnected drafts and absent targets do not invent neighbours',()=>{
 const d=original(),before=JSON.stringify(d);branch(d);const after=JSON.stringify(d);restored(edit(JSON.parse(after)));assert(!edit(JSON.parse(before)).routeInfo.authoring);
 d.talks[777]={id:777,roleIds:[0],bg:0,roles:[]};const s=edit(d,777);assert.equal(s.background,0);assert(s.warnings.length);assert(!s.routeInfo.authoring);
 assert.deepEqual(plain(Scene.pathTo(d,999,roots,{authoring:true}).path),[]);
});
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
const stageSource=app.slice(app.indexOf('function currentStage('),app.indexOf('function presentRoles('));
const renderSource=app.slice(app.indexOf('function renderPreview('),app.indexOf('function renderMiniScene('));
function editor(d){
 const b={window:{StudentAgeScene:Scene},StudentAgeScene:Scene,Remote:R,S:{doc:d,selected:C,event:311001,grade:1,branchFolders:d.branchFolders},stageMemo:[],stageMemoQueued:false,sceneContext:()=>({roots}),queueMicrotask:()=>{},invalidateStageMemo:()=>{},sceneMode:'edit',sceneSyncing:false,storyPreview:null,talk:()=>d.talks[b.S.selected],prepareSceneExpressions:()=>{},$:()=>({}),renderInspector:()=>{},ensureScene:()=>{}};
 b.scenePlayer=new Scene.Player({getDoc:()=>d,getContext:()=>({roots}),onRender:()=>{}});vm.runInNewContext(stageSource+'\n'+renderSource,b);return b;
}
test('actual currentStage → renderPreview → Player.select → refresh keeps scene and warning',()=>{
 const d=original();branch(d);const b=editor(d);b.renderPreview();restored(b.scenePlayer.scene);b.stageMemo=[];restored(b.currentStage());b.scenePlayer.refresh();restored(b.scenePlayer.scene);
 b.scenePlayer.select(C,[C]);b.stageMemo=[];b.renderPreview();restored(b.scenePlayer.scene); // stale paused selection is rebuilt
});
test('played/paused alternative history retains its scene instead of replacing it with the authoring route',()=>{
 const d=original();branch(d);d.talks[777]={id:777,bg:114,roles:[[0,1002,0,2,0]],nextTalk:[C]};d.backgrounds[114]={id:114};const b=editor(d);
 b.scenePlayer.select(C,[777,C]);b.scenePlayer.recordStart();b.scenePlayer.pause();b.stageMemo=[];b.renderPreview();assert.equal(b.currentStage().background,114);assert.deepEqual(plain(b.scenePlayer.trace),[777,C]);
});
test('event reset clears inherited authoring context',()=>{
 const d=original();branch(d);const s=edit(d),p=new Scene.Player({getDoc:()=>d,getContext:()=>({roots}),onRender:()=>{}});p.select(C,s.trace,s.routeInfo);p.choose({id:311001002,available:true,reset:true});assert.equal(p.scene.background,0);assert(!p.scene.routeInfo.authoring);assert.deepEqual(plain(p.trace),[311001002]);
});
test('unloaded Remote route and actual editor synchronization preserve original staging without body requests',()=>{
 const d=original();branch(d);let requests=0;const descriptor={version:1,generation:'authoring',ids:Object.keys(d.talks),summaries:Object.fromEntries(Object.entries(d.talks).map(([id,row])=>{const {content,...record}=row;return [id,{record,fields:Object.keys(row),hasText:!!content,excerpt:content||''}];}))};
 d.talks=R.create(descriptor,async()=>{requests++;throw Error('unexpected body request');},'r');const b=editor(d);b.renderPreview();restored(b.scenePlayer.scene);assert.equal(requests,0);
});
test('Remote helpers repurposed as prose or actions invalidate stale authoring metadata without loading text',()=>{
 for(const field of ['content','roles','effect','screenEffect','highlights']){
  const d=original(),f=branch(d);d.talks[f.routerId][field]=field==='content'?'repurposed helper':[[111,1002,0,1,0]];let requests=0;
  const descriptor={version:1,generation:'stale-'+field,ids:Object.keys(d.talks),summaries:Object.fromEntries(Object.entries(d.talks).map(([id,row])=>{const {content,...record}=row;return [id,{record,fields:Object.keys(row),hasText:!!content,excerpt:content||''}];}))};
  d.talks=R.create(descriptor,async()=>{requests++;throw Error('unexpected body request');},'r');const b=editor(d);b.renderPreview();assert.equal(b.scenePlayer.scene.background,0,field);assert(!b.scenePlayer.scene.routeInfo.authoring,field);assert.equal(requests,0);
 }
});
console.log('SCENE_AUTHORING_ROUTE_OK '+checks+' groups');
