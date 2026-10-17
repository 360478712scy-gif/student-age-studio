const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const c={window:{},console};vm.createContext(c);
for(const file of ['remote-talks.js','indexed-talks.js','event-bindings.js']){
 vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../'+file),'utf8'),c);
 c.StudentAgeIndexedTalks=c.window.StudentAgeIndexedTalks;c.StudentAgeRemoteTalks=c.window.StudentAgeRemoteTalks;
}
const B=c.window.StudentAgeEventBindings,plain=v=>JSON.parse(JSON.stringify(v));
const event={id:7,type:2,npc:3,mapId:12,rate:.5,maxcount:1,condition:[],effect:[],talkId:[71]};
let doc={events:{7:event},talks:{71:{id:71,content:'保留正文',nextTalk:[],effect:[]}},options:{}};
B.applySocial(doc,event,{social:{kind:'favor',favor:30}},{},()=>9000000);
B.syncSocialEffects(doc);
assert.deepEqual(plain(event.condition),[[7,1,3,30],[0,1,.5]],'Selecting an event location must not require the NPC to already be there');
// Only obsolete rows recorded as editor-owned may be removed; manual location checks survive.
event.condition.push([7,101,3,12],[7,101,4,5]);
event.studioSocial.entryConditions.push([7,101,3,12]);
event.mapId=5;B.syncSocialEffects(doc);
assert.deepEqual(plain(event.condition),[[7,1,3,30],[7,101,4,5],[0,1,.5]]);
assert.deepEqual(plain(event.studioSocial.entryConditions),[[0,1,.5]]);
doc=plain(doc);B.syncSocialEffects(doc);B.syncSocialEffects(doc);
assert.equal(doc.events[7].mapId,5);
assert.deepEqual(plain(doc.events[7].condition),[[7,1,3,30],[7,101,4,5],[0,1,.5]]);
// The chat binding still writes InteractCfg.map, without adding an NPC location prerequisite.
const chat={id:8,type:2,npc:3,mapId:12,rate:1,maxcount:1,condition:[],effect:[],talkId:[]};doc.events[8]=chat;
B.applySocial(doc,chat,{social:{kind:'talk',text:'聊天'}},{},()=>9000001);
assert.deepEqual(plain(chat.condition),[]);assert.deepEqual(plain(doc.interactions[9000001].map),[12]);
const schema=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../catalog-schema.json'),'utf8'));
let checked=0;function check(value){if(Array.isArray(value)){value.forEach(check);return;}if(!value||typeof value!=='object')return;
 if(value.template?.[0]===2&&value.template?.[1]===8){assert.equal(value.parameters[0].choices.find(v=>v.label==='非假期').id,-1);checked++;}
 Object.values(value).forEach(check);
}check(schema);assert(checked>0);
console.log('PASS: location selection, owned legacy cleanup, manual preservation, probability, reopen, chat map and holiday encoding');
