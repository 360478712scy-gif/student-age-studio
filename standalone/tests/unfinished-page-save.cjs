'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
(async()=>{
 for(const file of ['space.js','messages.js','goals.js']){
  const source=fs.readFileSync(path.join(__dirname,'..',file),'utf8'),fn=source.split('\n').find(line=>line.includes('async function save(){'));
  let calls=0,notices=[];const S={busy:false,invalid:{bad:true},pending:[],rows:{},data:{table:{referenceRows:{}},people:{referenceRows:{}},goals:{}},refs:{},localIds:{},saved:'{}'};
  const box={S,host:{querySelector:()=>({})},options:{project:{id:'fixture'},status:m=>notices.push(m)},status:m=>notices.push(m),readonly:()=>false,dirty:()=>true,invalid:()=>true,snapshot:()=> '{}',notify(){},render(){},alive:true,copy:structuredClone,clone:structuredClone,api:async()=>{calls++;return {rows:{},editor:{},people:{},images:{},revision:'saved'}},STUDIO_SAVE_REVIEW:{confirm(){throw Error('unexpected confirmation');}}};
  vm.createContext(box);vm.runInContext(fn,box);await box.save();assert.equal(calls,1,file);assert.equal(S.revision,'saved');assert(notices.some(s=>s.includes('上一次有效值')),file);assert.equal(S.busy,false);
  box.api=async()=>{throw Error('disk write failed');};await assert.rejects(box.save(),/disk write failed/);assert.equal(S.busy,false,file+' clears busy on I/O error');
 }
 const src=fs.readFileSync(path.join(__dirname,'../social.js'),'utf8'),fn=name=>src.split('\n').find(l=>l.trim().startsWith('function '+name+'('));
 let added;const box={S:{pendingComment:{content:'draft',delay:-3,postId:7},target:'8'},post:()=>({id:7}),addComment:(...args)=>added=args,dialog:{close(){}},changed(){},status(){}};
 vm.createContext(box);vm.runInContext(fn('commitPendingComment'),box);box.commitPendingComment();assert.equal(added[4],-3);assert.equal(box.S.pendingComment,null);
 console.log('PASS: three incomplete-page saves without confirmation; I/O errors propagate; negative comment delay commits unchanged');
})().catch(e=>{console.error(e);process.exitCode=1;});
