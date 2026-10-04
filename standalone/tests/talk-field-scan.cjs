'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),I=require('../indexed-talks.js'),R=I.Remote;
const copy=value=>JSON.parse(JSON.stringify(value)),field='studioSocialEffects';
const records={1:{id:1},2:{id:2,[field]:false},3:{id:3,[field]:0},4:{id:4,[field]:null},5:{id:5,[field]:''},6:{id:6,[field]:[]},7:{id:7,[field]:{}},8:{id:8,[field]:true},9:{id:9,[field]:'yes'},10:{id:10,future:{[field]:true}},11:{id:11,content:'文本里的 "studioSocialEffects":true'},12:{id:12,content:'多行\n中文😀'}};
const remote=rows=>R.create({version:1,generation:'field-scan',ids:Object.keys(rows),summaries:Object.fromEntries(Object.entries(rows).map(([id,{content,...record}])=>[id,{record,fields:Object.keys(rows[id]),excerpt:content||'',hasText:!!content}]))},async(_,body)=>({generation:'field-scan',revision:'r',rows:body.ids.map(id=>[id,JSON.stringify(rows[id])]),remaining:[]}),'r');
for(const make of [rows=>I.create(Object.entries(rows).map(([id,row])=>[id,JSON.stringify(row)])),remote,copy]){
 let table=make(records),plain=copy(records),baseline=I.clone(table);
 const check=()=>assert.deepEqual(I.keysWithField(table,field),Object.keys(plain).filter(id=>!!plain[id][field]));
 check();assert.deepEqual(I.keysWithField(table,field),['6','7','8','9']);
 for(const target of [table,plain]){target[1][field]=[];delete target[6][field];target[2][field]={};target[7][field]=false;delete target[8];target[13]={id:13,[field]:{}};target[14]={id:14,[field]:null};}
 check();assert.deepEqual(I.keysWithField(baseline,field),['6','7','8','9']);
 table=I.clone(table);check(); // Restored overlays must use their own field values.
 for(const target of [table,plain]){target[1][field]=false;delete target[2];target[6][field]={};delete target[13][field];target[14][field]=[];}
 check();
 if(R.info(table)){
  const info=R.info(table),held=table[9];table[15]=held;plain[15]=copy(plain[9]);table[15].id=15;plain[15].id=15;delete table[9];delete plain[9];check();assert.equal(R.stats(table).loaded,0);
  // Content uses the same summary/draft semantics without loading any body.
  assert.deepEqual(I.keysWithField(table,'content'),['11','12']);table[12].content='';table[15].content='新文';assert.deepEqual(I.keysWithField(table,'content'),['11','15']);assert.equal(info.base.cache.size,0);
 }
}
// Escaped property names, whitespace and nested lookalikes are legitimate JSON.
const escaped=I.create([['1','{"id":1,"studioSocial\\u0045ffects":[]}'],['2','{"id":2,"future":{"studioSocialEffects":true}}'],['3','{ "id" : 3, "studioSocialEffects" : false }'],['4','{"id":4,"a\\/b":[]}']]);
assert.deepEqual(I.keysWithField(escaped,field),['1']);assert.deepEqual(I.keysWithField(escaped,'a/b'),['4']);assert.deepEqual(I.keysWithField(escaped,'toString'),['1','2','3','4']);

// Exercise the real save-time effect synchronizer against ordinary rows. It
// removes generated effects, preserves manual ones and appends at graph ends.
const socialRows={1:{id:1,content:'旧末句',effect:[[1,2,3],[1,2,4],[9,9]],studioSocialEffects:{10:[[1,2,3],[1,2,4]]}},2:{id:2,content:'入口',nextTalk:[3],effect:[[1,2,3]],studioSocialEffects:{10:[[1,2,3]]}},3:{id:3,content:'新末句',nextTalk:[],effect:[],future:{keep:true}}};
const events={10:{id:10,talkId:[2],effect:[[1,2,4]],studioSocial:{kind:'topic',effects:[[1,2,3]]}}};
const source=fs.readFileSync(path.join(__dirname,'../event-bindings.js'),'utf8'),synchronizer=source.slice(source.indexOf('function syncSocialEffects('),source.indexOf('function syncSocialEntry('));
const oldScan={...I,keysWithField:(table,key)=>Object.keys(table).filter(id=>!!table[id]?.[key])};
const sync=(doc,index=I)=>{const box={StudentAgeIndexedTalks:index,copy:I.clone};vm.createContext(box);vm.runInContext(synchronizer,box);box.syncSocialEffects(doc);};
(async()=>{
 const expected={talks:copy(socialRows),events:copy(events),options:{}};sync(expected);sync(expected);
 assert.deepEqual(expected.talks[1].effect,[[1,2,4],[9,9]]);assert.deepEqual(expected.talks[2].effect,[]);assert.deepEqual(expected.talks[3].effect,[[1,2,3]]);assert.deepEqual(copy(expected.talks[3].studioSocialEffects),{10:[[1,2,3]]});
 for(const make of [rows=>I.create(Object.entries(rows).map(([id,row])=>[id,JSON.stringify(row)])),remote]){
  const doc={talks:make(socialRows),events:copy(events),options:{}},prior={talks:make(socialRows),events:copy(events),options:{}};
  await R.ensure(doc.talks,[1,2,3]);await R.ensure(prior.talks,[1,2,3]);sync(doc);sync(prior,oldScan);sync(doc);sync(prior,oldScan);
  const actual=JSON.parse(JSON.stringify(doc));assert.deepEqual(actual,JSON.parse(JSON.stringify(prior)),'field scan preserves actual synchronizer behavior');
  for(const id of [1,2,3])assert.deepEqual(actual.talks[id].effect,expected.talks[id].effect);
  assert.deepEqual(actual,copy(expected));
  // Moving the ending and changing generated effects must remove the old
  // generated value while preserving hand-written effects and unknown fields.
  const wanted=copy(expected);
  for(const target of [doc,wanted]){target.events[10].studioSocial.effects=[[1,2,5]];target.talks[3].nextTalk=[4];target.talks[4]={id:4,content:'后续末句',effect:[[1,2,4]],nextTalk:[],future:{keep:'new'}};sync(target);sync(target);}
  assert.deepEqual(JSON.parse(JSON.stringify(doc)),copy(wanted));assert.deepEqual(copy(doc.talks[3].effect),[]);assert.deepEqual(copy(doc.talks[4].effect),[[1,2,4],[1,2,5]]);assert.deepEqual(copy(doc.talks[4].studioSocialEffects),{10:[[1,2,5]]});
 }
 // A large immutable baseline with no field stays completely undecoded.
 const large=I.create(Array.from({length:250000},(_,i)=>[String(i+1),JSON.stringify({id:i+1,content:'隔离中文\n'+i})]));
 assert.deepEqual(I.keysWithField(large,field),[]);assert.equal(I.stats(large).decoded,0);assert.equal(I.stats(large).edited,0);
 console.log('TALK_FIELD_SCAN_OK (truthiness, escaped keys, drafts/overlays/deletions, real social sync, 250k undecoded rows)');
})().catch(error=>{console.error(error);process.exitCode=1;});
