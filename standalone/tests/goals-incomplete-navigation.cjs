'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const lines=fs.readFileSync(path.join(__dirname,'../goals.js'),'utf8').split('\n');
(async()=>{
 let invalidDOM=false,calls=0;const notices=[],errors=[];
 const S={data:{goals:{rows:{},schema:{fields:[]},referenceRows:{}},people:{referenceRows:{}}},rows:{1:{id:1,name:'old',weight:2},2:{id:2,name:'second'}},selected:'1',source:'local',tab:'basic',invalid:{},pending:[],refs:{},localIds:{},undo:[],redo:[]};
 const box={S,host:{querySelector:()=>invalidDOM?{}:null},options:{project:{},status:m=>notices.push(m)},clone:structuredClone,rows:()=>S.rows,row:()=>S.rows[S.selected],change:fn=>fn(),render:()=>invalidDOM=false,form:()=>invalidDOM=false,list(){},preview(){},notify(){},alive:true,error:e=>errors.push(e),STUDIO_IDS:{allocate:()=>3},api:async()=>{calls++;return {rows:structuredClone(S.rows),images:{},people:{},revision:'saved'};}};
 vm.createContext(box);vm.runInContext(lines.find(l=>l.includes('const snapshot=()'))+'\n'+['function settleIncomplete(','async function add(','async function save('].map(name=>lines.find(l=>l.trim().startsWith(name))).join('\n')+'\n'+lines.find(l=>l.trim().startsWith('host.onclick='))+'\nglobalThis.testDirty=dirty;globalThis.testSnapshot=snapshot;',box);
 S.saved=box.testSnapshot();
 const invalidate=()=>{S.invalid={weight:true};invalidDOM=true;};
 for(const [key,value,state]of [['goalId','2','selected'],['goalTab','reward','tab'],['goalSource','reference','source']]){
  invalidate();const button={dataset:{[key]:value},hasAttribute:()=>false};box.host.onclick({target:{closest:s=>s==='button'?button:null}});await new Promise(setImmediate);assert.equal(S[state],value);assert.equal(Object.keys(S.invalid).length,0);assert.equal(box.testDirty(),false,'navigation settles invalid flags');assert.equal(S.rows[1].weight,2);
 }
 invalidate();await box.add();assert(S.rows[3]);assert.equal(Object.keys(S.invalid).length,0);assert.equal(S.rows[1].weight,2);
 invalidate();await box.save();assert.equal(calls,1);assert.equal(box.testDirty(),false,'saved draft must not stay dirty and block flush');assert.equal(S.rows[1].weight,2);
 invalidate();box.api=async()=>{throw Error('disk error');};await assert.rejects(box.save(),/disk error/);assert(box.testDirty(),'failed save retains invalid state');assert.equal(S.busy,false);assert.deepEqual(errors,[]);assert(notices.length>=4);
 console.log('PASS: incomplete goals allow add, selection, tabs, source; preserve previous parsed values; save clears dirty/flush blockers; failed I/O remains dirty');
})().catch(e=>{console.error(e);process.exitCode=1;});
