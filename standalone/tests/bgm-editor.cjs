'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const base=1000001000,rows=Object.fromEntries(Array.from({length:99},(_,i)=>[base+i+1,{id:base+i+1,audio:0}]));
const S={selected:base+1,order:Object.keys(rows).map(Number),doc:{talks:rows,audioCues:{bgm:[],sfx:{}}},audios:[{id:7,type:1},{id:8,type:2}]};
let notices=[],undo=[],scope=S.order;
const c={S,Set,Map,Number,Math,Date,JSON,$:()=>null,ids:v=>(v||[]).map(Number),visibleIds:()=>scope,toast:s=>notices.push(s),mutate:(_,fn)=>{undo.push(JSON.stringify(S.doc));fn();},warnAudioPlugin:()=>{}};
vm.createContext(c);
for(const [start,end] of [['function audioData()','function audioName('],['function bgmDraft()','function audioOptions('],['function bgmRangeLabel(','function renderBgmChoices('],['function preserveLegacyAudio(','async function previewAudio(']])vm.runInContext(source.slice(source.indexOf(start),source.indexOf(end)),c);
assert.equal(c.bgmDraft().ids.length,0);assert.equal(c.bgmDraft().track,null);
c.toggleBgmAll();assert.equal(c.bgmDraft().ids.length,99);c.toggleBgmAll();assert.equal(c.bgmDraft().ids.length,0);assert.equal(undo.length,0);
c.setBgmRange('start','001');c.setBgmRange('end','030');assert.equal(c.bgmDraft().ids.length,30);
c.bgmDraft().track=7;c.applyBgmDraft();assert.equal(S.doc.audioCues.bgm[0].talkIds.length,30);assert(Object.values(rows).every(r=>r.audio===0));
// A legacy unsaved range had written audio on every line. Shrinking clears it.
for(let i=11;i<=30;i++)rows[base+i].audio=7;
c.setBgmRange('end','010');assert.equal(S.doc.audioCues.bgm[0].talkIds.length,10);assert(Object.values(rows).every(r=>r.audio===0));
c.toggleBgmAll();assert.equal(S.doc.audioCues.bgm[0].talkIds.length,99);c.toggleBgmAll();assert.equal(S.doc.audioCues.bgm.length,0);
c.setBgmRange('start','031');c.setBgmRange('end','040');c.bgmDraft().track=0;c.applyBgmDraft();assert.equal(S.doc.audioCues.bgm[0].audioId,0);
const before=JSON.stringify(S.doc);c.setBgmRange('end','bad');c.setBgmRange('end','999');assert.equal(JSON.stringify(S.doc),before);
c.setBgmRange('start','bad',true);c.setBgmRange('end','040',true);c.applyBgmDraft();assert.equal(JSON.stringify(S.doc),before);
S.order.push(1000002001);scope=S.order;c.setBgmRange('start','001');assert(notices.at(-1).includes('完整 ID'));assert.equal(JSON.stringify(S.doc),before);
// Editing a shared range through one event must preserve the other event.
S.doc.audioCues.bgm=[{id:'shared',audioId:7,talkIds:[base+1,1000002001],loop:true,volume:1}];S.bgmDraft=null;scope=[base+1];rows[1000002001]={id:1000002001,audio:7};
assert.equal(c.bgmDraft().ids.length,1);c.bgmDraft().track=0;c.applyBgmDraft();assert.equal(S.doc.audioCues.bgm.find(g=>g.id==='shared').talkIds[0],1000002001);assert.equal(rows[1000002001].audio,7);
console.log('BGM editor: empty/default, toggle, suffix, shrink, zero, invalid/ambiguous input and shared scope passed.');
// Starting a segmented preview must wait for the requested sentence, otherwise
// Player.select loads asynchronously and play() starts the previous scene/music.
(async()=>{
 let ready=false,resolve,started=0;const rows={},pending=new Promise(r=>resolve=r);
 const v={S:{doc:{talks:rows},selected:41,event:1,project:{id:'p'}},Remote:{info:()=>true,ready:()=>ready,ensure:()=>pending},storyPreviewOpenSequence:0,storyPreview:null,largeScene:null,talk:()=>null,toast:()=>started++,fail:e=>{throw e;}};
 vm.createContext(v);vm.runInContext(source.slice(source.indexOf('function openStoryPreview(){'),source.indexOf('let historyImageObserver=')),v);
 const opening=v.openStoryPreview();assert.equal(started,0);ready=true;resolve();await opening;assert.equal(started,1);
 ready=false;const second=v.openStoryPreview();v.S.selected=42;await second;assert.equal(started,1);
 console.log('Preview waits for its selected segmented sentence and ignores a stale opening.');
})().catch(e=>{console.error(e);process.exitCode=1;});
