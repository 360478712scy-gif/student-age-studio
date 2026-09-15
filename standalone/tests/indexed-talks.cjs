const assert=require('node:assert/strict'),T=require('../indexed-talks.js');
const rows=Object.fromEntries(Array.from({length:1000},(_,i)=>[String(i+1),{id:i+1,content:'台词'+i,nextTalk:[i+2],roles:[[3,1001,1]],unknown:{values:[1,2,{text:'保留'}]}}]));
const make=()=>T.create(Object.entries(rows).map(([k,v])=>[k,JSON.stringify(v)]));
let a=make(),before=T.clone(a);
assert.equal(T.stats(a).decoded,0);
assert.deepEqual(T.keysWithField(a,'studioSocialEffects'),[]);assert(T.stats(a).decoded<=64);assert.equal(T.stats(a).edited,0);
a[2].studioSocialEffects={7:[[1,2,3]]};a[1001]={id:1001,studioSocialEffects:{}};delete a[3];
assert.deepEqual(T.keysWithField(a,'studioSocialEffects'),['2','1001']);assert.deepEqual(T.keysWithField(before,'studioSocialEffects'),[]);
assert.deepEqual(T.keysWithField(JSON.parse(JSON.stringify(a)),'studioSocialEffects'),['2','1001']);
delete a[2].studioSocialEffects;delete a[1001];a[3]=rows[3];
const held=a[1].unknown.values;for(const row of Object.values(a))assert(row.id>0);
assert(T.stats(a).decoded<=64);held[2].text='修改';held.push(7);a[1].roles[0].splice(1,1,3004);delete a[1].content;
assert.deepEqual(JSON.parse(JSON.stringify(a[1])),{id:1,nextTalk:[2],roles:[[3,3004,1]],unknown:{values:[1,2,{text:'修改'},7]}});
assert.deepEqual(JSON.parse(JSON.stringify(before)),rows);
assert.deepEqual(T.delta(a,before),{version:1,upsert:{1:JSON.parse(JSON.stringify(a[1]))},deleted:[]});
a[1]=rows[1];assert.deepEqual(T.delta(a,before),{version:1,upsert:{},deleted:[]});
a[1001]={id:1001,content:'新增'};delete a[2];const checkpoint=T.clone(a);
a[3].roles=[];delete a[1001];assert.equal(checkpoint[1001].content,'新增');assert.equal(checkpoint[3].roles[0][1],1001);
const packed=T.stringify({talks:a});assert(packed.length<1000);assert.deepEqual(JSON.parse(JSON.stringify(T.parse(packed).talks)),JSON.parse(JSON.stringify(a)));
const all=JSON.parse(JSON.stringify(a));assert.equal(Object.keys(all).length,999);assert.equal(all[2],undefined);
assert.deepEqual(T.delta(checkpoint,before),{version:1,upsert:{1001:{id:1001,content:'新增'}},deleted:[2]});
// A row deleted before save can be restored by an earlier undo snapshot.
assert.deepEqual(T.delta(before,checkpoint),{version:1,upsert:{2:rows[2]},deleted:[1001]});
// Array iteration, in-place sorting, length assignment and unknown fields survive.
a[3].roles.push([4,2001]);a[3].roles[0].length=2;assert.deepEqual([...a[3].roles[0]],[4,2001]);
a[3].unknown.values.reverse();assert.deepEqual(JSON.parse(JSON.stringify(a[3].unknown.values)),[{text:'保留'},2,1]);
const assigned={id:2000,roles:[]};a[2000]=assigned;assigned.roles.push([3,3000]);assert.equal(a[2000].roles[0][1],3000);delete a[2000];assert.equal(T.stats(a).total,999);const oldRow=a[3],oldArray=a[3].roles,oldCommand=oldArray[0];a[3].roles=[];oldCommand.push(999);assert.equal(a[3].roles.length,0);assert.equal(oldArray[0][2],999);
a[3]={id:3,content:'替换'};oldRow.content='旧引用';assert.equal(a[3].content,'替换');
const removed=a[4];delete a[4];removed.content='删除后旧引用';assert.equal(a[4],undefined);
assert.throws(()=>T.create([['1','{}'],['1','{}']]));assert.throws(()=>T.create([['1','{broken']])[1].content);assert.throws(()=>T.create([['1','{"id":2}']])[1].content);
assert.throws(()=>T.create([[1,'{}']]));const expired=T.stringify(a);T.retain(make());assert.throws(()=>T.parse(expired));// Deterministic differential check against ordinary JSON objects, including history forks.
let lazy=make(),plain=JSON.parse(JSON.stringify(rows)),seed=15791;const history=[];
const random=n=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed%n;};
for(let step=0;step<300;step++){
 const id=String(1+random(40));if(!plain[id]){plain[id]={id:Number(id),content:'恢复',roles:[],nextTalk:[]};lazy[id]=JSON.parse(JSON.stringify(plain[id]));}
 const op=random(6);
 if(op===0){plain[id].content='含括号{ }、引号"、换行\n和表情🙂'+step;lazy[id].content=plain[id].content;}
 if(op===1){plain[id].roles.push([3,3004,step]);lazy[id].roles.push([3,3004,step]);}
 if(op===2){plain[id].roles.splice(0,1);lazy[id].roles.splice(0,1);}
 if(op===3){history.push([T.clone(lazy),JSON.parse(JSON.stringify(plain))]);}
 if(op===4){delete plain[id];delete lazy[id];}
 if(op===5&&history.length){const pair=history[random(history.length)];lazy=T.clone(pair[0]);plain=JSON.parse(JSON.stringify(pair[1]));}
 assert.deepEqual(JSON.parse(JSON.stringify(lazy)),plain,'operation '+step);
}
console.log('INDEXED_TALKS_OK (300 differential operations)');
