const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const c={window:{},console};vm.createContext(c);
for(const file of ['remote-talks.js','indexed-talks.js','event-bindings.js']){
 vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../'+file),'utf8'),c);
 c.StudentAgeIndexedTalks=c.window.StudentAgeIndexedTalks;c.StudentAgeRemoteTalks=c.window.StudentAgeRemoteTalks;
}
const B=c.window.StudentAgeEventBindings,plain=v=>JSON.parse(JSON.stringify(v));
const event={id:7,type:2,npc:111234,mapId:3,rate:.5,maxcount:1,condition:[],effect:[],talkId:[71],future:{keep:true}};
const doc={events:{7:event},talks:{71:{id:71,content:'保留正文',nextTalk:[],effect:[]}},options:{}};
const apply=social=>B.applySocial(doc,event,{social},{},()=>9000000);
apply({kind:'favor',favor:30});B.syncSocialEffects(doc);
assert.deepEqual(plain(event.condition),[[7,1,111234,30],[7,101,111234,3],[0,1,.5]]);
event.condition=[];B.syncSocialEffects(doc);
// Changing away from a social type and back must not undo the user's deletions.
apply(null);apply({kind:'favor',favor:50});B.syncSocialEffects(doc);
assert.deepEqual(plain(event.condition),[],'Changing event type must preserve deleted auto conditions');
const restored=plain(doc);B.syncSocialEffects(restored);
assert.deepEqual(restored.events[7].condition,[],'Saving/reopening must preserve removals');
assert.deepEqual(restored.events[7].future,{keep:true});
// Manually re-adding a condition still works; suppression only affects automatic additions.
event.condition.push([7,1,111234,10]);apply({kind:'favor',favor:60});B.syncSocialEffects(doc);
assert.deepEqual(plain(event.condition),[[7,1,111234,10]]);
console.log('PASS: delete generated conditions, change type, reapply, save/reopen and manual re-add');

// A generated intimacy effect removed inside a dialogue must also stay removed.
apply({kind:'topic',intimacy:5});B.syncSocialEffects(doc);
assert.deepEqual(plain(doc.talks[71].effect),[[1,520,5]]);
doc.talks[71].effect=[];B.syncSocialEffects(doc);
apply(null);apply({kind:'topic',intimacy:10});B.syncSocialEffects(doc);
assert.deepEqual(plain(doc.talks[71].effect),[]);
assert.deepEqual(plain(event.effect),[]);
console.log('PASS: deleting generated dialogue effects survives type changes');
