(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeHistory=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';
const clone=value=>JSON.parse(JSON.stringify(value)),ids=value=>Array.isArray(value)?value.map(Number).filter(Number.isFinite):[];
function speaker(doc,talk){if(talk.roleName)return talk.roleName;return ids(talk.roleIds).filter(id=>id>=0).map(id=>doc.persons?.[id]?.name||(id===0?'主角':'人物 '+id)).join('、')||'旁白';}
function line(doc,id){const talk=doc.talks?.[id];if(!talk)return null;return {kind:'dialogue',talkId:Number(id),speaker:speaker(doc,talk),content:String(talk.content||'')};}
class Recorder{
 constructor(){this.sessions=[];this.current=null;this.serial=0;}
 begin(doc,id,context={}){const first=line(doc,id);if(!first)return;if(context.scene){first.speaker=String(context.scene.speaker||first.speaker);first.content=String(context.scene.content??first.content);first.portraits=clone(context.scene.portraits||[]);first.speakerGender=context.scene.speakerGender;first.narration=!(context.scene.speakerIds||[]).length;}this.current={id:++this.serial,title:String(context.title||'剧情预演'),startedAt:new Date().toISOString(),reason:context.reason||'play',entries:[first]};this.sessions.push(this.current);}
 visit(doc,id,scene=null){const entry=line(doc,id);if(!entry)return;if(scene){entry.speaker=String(scene.speaker||entry.speaker);entry.content=String(scene.content??entry.content);entry.portraits=clone(scene.portraits||[]);entry.speakerGender=scene.speakerGender;entry.narration=!(scene.speakerIds||[]).length;}if(!this.current)this.begin(doc,id,{scene});else this.current.entries.push(entry);}
 choice(route){if(!this.current||!route)return;this.current.entries.push({kind:'choice',optionId:route.optionId??null,content:String(route.optionText||route.label||'继续'),route:String(route.label||''),targetTalkId:route.id??null,eventId:route.eventId??null,end:!!route.end});}
 finish(){if(this.current)this.current.ended=true;}
 clear(){this.sessions=[];this.current=null;this.serial=0;}
 export(){return {version:1,kind:'played-history',policy:'只记录明确播放与继续时实际到达的对白。回退不删除或新增记录；再次向前经过会再次记录。从头重放开始新一轮。',sessions:clone(this.sessions)};}
 count(){return this.sessions.reduce((sum,s)=>sum+s.entries.filter(e=>e.kind==='dialogue').length,0);}
}
function fullStory(doc,eventId,order=[]){
 const event=doc.events?.[eventId],seen=new Set(),stack=ids(event?.talkId).reverse(),reachable=[];
 while(stack.length){const id=stack.pop();if(seen.has(id)||!doc.talks?.[id])continue;seen.add(id);reachable.push(id);const t=doc.talks[id],next=[...ids(t.nextTalk),...ids(t.nextTalk2)];for(const optionId of ids(t.option)){const o=doc.options?.[optionId];next.push(...ids(o?.talkId),...ids(o?.talkId2));}stack.push(...next.reverse());}
 const selected=event?[...order.filter(id=>seen.has(Number(id))),...reachable.filter(id=>!order.map(Number).includes(id))]:[...order.filter(id=>doc.talks?.[id]),...Object.keys(doc.talks||{}).map(Number).filter(id=>!order.map(Number).includes(id))];
 const entries=[];for(const id of [...new Set(selected.map(Number))]){const entry=line(doc,id);if(!entry)continue;const talk=doc.talks[id];entries.push({...entry,nextTalk:ids(talk.nextTalk),nextTalk2:ids(talk.nextTalk2)});for(const optionId of ids(talk.option)){const option=doc.options?.[optionId];entries.push({kind:'option',optionId,content:option?.content||'未载入的选项',targetTalkIds:ids(option?.talkId),alternateTalkIds:ids(option?.talkId2),eventId:Number(option?.nextEvtId)||null});}}
 return {version:1,kind:'full-story',title:event?.title||'当前模组全部对话',policy:'剧情清单包含所有可达分支。它不是实际播放历史；共享或循环节点只列一次，接续的其他事件不递归展开。',sessions:[{id:1,title:event?.title||'当前模组全部对话',entries}]};
}
function serialize(document,format='txt'){
 if(format==='json')return JSON.stringify(document,null,2)+'\n';
 const markdown=format==='md',out=[(markdown?'# ':'')+(document.kind==='played-history'?'实际预演历史':'剧情全部对话'),document.policy||'',''];
 for(const session of document.sessions||[]){out.push((markdown?'## ':'')+(document.kind==='played-history'?'第 '+session.id+' 轮 · ':'')+session.title,'');for(const entry of session.entries||[]){if(entry.kind==='dialogue'){out.push(entry.speaker+'：',entry.content,'');}else if(entry.kind==='choice'){out.push('【已选择】'+entry.content);if(entry.route&&entry.route!==entry.content)out.push('路线：'+entry.route);out.push('');}else if(entry.kind==='option'){out.push('【可选项】'+entry.content);if(entry.targetTalkIds?.length)out.push('普通去向：'+entry.targetTalkIds.join(' / '));if(entry.alternateTalkIds?.length)out.push('备用去向：'+entry.alternateTalkIds.join(' / '));out.push('');}}}
 return out.join('\n').replace(/\n+$/,'')+'\n';
}
function filename(title,kind,format){return String(title||'学生时代').replace(/[\\/:*?"<>|\u0000-\u001f]/g,'_').trim().slice(0,80)+'-'+(kind==='played-history'?'预演历史':'全部对话')+'.'+format;}
return {Recorder,line,fullStory,serialize,filename};
});
