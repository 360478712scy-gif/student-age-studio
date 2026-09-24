const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');const c={window:{}};vm.runInNewContext(fs.readFileSync('standalone/scene.js','utf8'),c);const S=c.window.StudentAgeScene;
const make=()=>({persons:{0:{id:0},3:{id:3},4:{id:4}},backgrounds:{},options:{},events:{1:{id:1,talkId:[1]}},talks:{1:{id:1,roleIds:[3,4],roles:[]}}});
for(const command of [[0,3008,-50,0,0],[3,3000,10],[0,5001,1],[3,3006,1]]){
 const doc=make(),before=structuredClone(doc.talks[1]),state=S.reconstruct(doc,1);doc.talks[1].roles=[command];assert(S.preserveImplicitEntries(before,doc.talks[1],state));
 const saved=JSON.parse(JSON.stringify(doc)),after=S.reconstruct(saved,1);
 for(const id of [3,4]){assert(after.roles[id].visible);assert.equal(after.roles[id].axis,state.roles[id].axis);}
 assert.equal(S.preserveImplicitEntries(before,doc.talks[1],state),false);
}
const d=make(),before=structuredClone(d.talks[1]),state=S.reconstruct(d,1);d.talks[1].roles=[[3,2002,0],[4,1002,1,2,0]];assert.equal(S.preserveImplicitEntries(before,d.talks[1],state),false);
d.talks[1].roleIds=[];d.talks[1].roles=[[0,3008,5]];assert.equal(S.preserveImplicitEntries(before,d.talks[1],state),false);
console.log('implicit-entry-edit: movement, expression, paper, clothing, save/reload, idempotence and explicit exits passed');
