'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const lines=fs.readFileSync(path.join(__dirname,'../messages.js'),'utf8').split('\n');
(async()=>{
 let invalidDOM=false,calls=0;const notices=[],errors=[];
 const S={data:{table:{referenceRows:{}}},rows:{1:{id:1,content:'saved',role:3},2:{id:2,content:'second',role:3}},editor:{previewDelays:{1:2}},root:'1',selected:'1',source:'local',choices:{},invalid:{},undo:[],redo:[]};
 const render=()=>invalidDOM=false,box={S,host:{querySelector:()=>invalidDOM?{}:null},options:{project:{},status:m=>notices.push(m)},rows:()=>S.rows,row:()=>S.rows[S.selected],root:()=>S.rows[S.root],change:fn=>fn(),render,renderForm:render,renderPhone(){},renderBranches(){},notify(){},alive:true,error:e=>errors.push(e),G:{roots:()=>[{id:1}],branches:()=>[{id:2,choices:{1:2}}]},api:async()=>{calls++;return {rows:structuredClone(S.rows),editor:structuredClone(S.editor),revision:'saved'};}};
 vm.createContext(box);vm.runInContext(lines.find(l=>l.includes('const snapshot=()'))+'\n'+['function settleIncomplete(','async function save('].map(name=>lines.find(l=>l.trim().startsWith(name))).join('\n')+'\n'+lines.find(l=>l.trim().startsWith('host.onclick='))+'\nglobalThis.testDirty=dirty;globalThis.testSnapshot=snapshot;',box);
 S.saved=box.testSnapshot();const invalidate=()=>{S.invalid={delay:true};invalidDOM=true;};
 for(const [key,value,state,expected]of [['messageRoot','2','root','2'],['messageSelect','1','selected','1'],['messageBranch','0','selected','2'],['messageSource','reference','source','reference']]){
  invalidate();const button={dataset:{[key]:value},hasAttribute:()=>false};box.host.onclick({target:{closest:s=>s==='button'?button:null}});await new Promise(setImmediate);assert.equal(S[state],expected);assert.equal(Object.keys(S.invalid).length,0);assert.equal(box.testDirty(),false);assert.equal(S.editor.previewDelays[1],2);
 }
 invalidate();await box.save();assert.equal(calls,1);assert.equal(box.testDirty(),false,'successful save must allow flush to finish');assert.equal(S.editor.previewDelays[1],2);
 invalidate();box.api=async()=>{throw Error('disk error');};await assert.rejects(box.save(),/disk error/);assert(box.testDirty());assert.equal(S.busy,false);assert.deepEqual(errors,[]);assert(notices.length>=5);
 assert(!lines.some(l=>/if\(invalid\(\)\)throw Error/.test(l)),'no completeness gates remain');
 console.log('PASS: incomplete messages allow root, selection, branch, source navigation; save clears dirty; prior parsed values retained; I/O failure retains draft');
})().catch(e=>{console.error(e);process.exitCode=1;});
