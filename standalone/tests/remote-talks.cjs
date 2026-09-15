const assert=require('assert/strict'),I=require('../indexed-talks.js'),R=I.Remote;
const originals=Object.fromEntries(Array.from({length:250},(_,i)=>{const id=String(i+1);return [id,{id:i+1,content:'正文中文😀'+id,roles:[[3,1002,1,1,0],[4,3004,5]],nextTalk:i<249?[i+2]:[],future:{nested:[1,{keep:'yes'}]},toJSON:'unknown-field'}];}));
const strings=Object.fromEntries(Object.entries(originals).map(([id,row])=>[id,JSON.stringify(row)]));
const summaries=Object.fromEntries(Object.entries(originals).map(([id,{content,...row}])=>[id,{fields:Object.keys(originals[id]),record:row,excerpt:content.slice(0,80),hasText:true}]));
let requests=0;
const request=async(_,body)=>{requests++;await new Promise(r=>setTimeout(r,1));return {generation:'test',revision:'r1',rows:body.ids.map(id=>[id,strings[id]]),remaining:[]};};
(async()=>{
 const remote=R.create({version:1,generation:'test',ids:Object.keys(originals),summaries},request,'r1'),full=I.create(Object.entries(strings));
 assert.throws(()=>remote[1].content,/尚未读取/);assert.equal(remote[1].nextTalk[0],2);assert.equal(R.summary(remote[250]),originals[250].content);assert.throws(()=>JSON.stringify(remote),/尚未读取/);
 const saved=I.clone(remote);remote[240].roles[0][3]=2;remote[240].future.nested[1].keep='changed';
 assert.equal(requests,0);await R.ensure(remote,[240]);assert.deepEqual(I.delta(remote,saved).upsert[240],{...originals[240],roles:[[3,1002,1,2,0],[4,3004,5]],future:{nested:[1,{keep:'changed'}]}});
 await R.ensure(remote);for(const id of Object.keys(originals))remote[id]=I.clone(saved[id]);
 assert.deepEqual(JSON.parse(JSON.stringify(remote)),originals);
 const operations=[t=>{t[2].roles.push([9,1002,0]);},t=>{t[2].roles.splice(0,1);},t=>{const old=t[2].roles;t[2].roles=[[8,2001]];old.push([999]);assert.deepEqual(JSON.parse(JSON.stringify(t[2].roles)),[[8,2001]]);},t=>{const old=t[1].future.nested[1];t[1].future.nested[1]={new:1};old.keep='detached';},t=>{t[3]=I.clone(t[2]);t[3].id=3;t[3].content='拷贝';},t=>{delete t[4];},t=>{t[251]={id:251,content:'新增',future:{n:1}};}];
 for(const op of operations){op(remote);op(full);assert.deepEqual(JSON.parse(JSON.stringify(remote)),JSON.parse(JSON.stringify(full)));}
 const snapshot=I.stringify(remote),restored=I.parse(snapshot);assert.deepEqual(JSON.parse(JSON.stringify(remote)),JSON.parse(JSON.stringify(restored)));restored[1].content='另一个草稿';assert.notEqual(remote[1].content,restored[1].content);
 const submitted=I.clone(remote);remote[1].content='保存时继续输入';const patch=I.delta(remote,submitted);assert.deepEqual(Object.keys(patch.upsert),['1']);
 assert.equal(R.stats(remote).total,250);console.log('REMOTE_TALKS_OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
