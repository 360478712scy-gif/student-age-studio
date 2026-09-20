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
 const event=doc.events?.[eventId],reachable=storyIds(doc,eventId),seen=new Set(reachable),ordered=order.map(Number),orderedSet=new Set(ordered);
 const selected=event?[...ordered.filter(id=>seen.has(id)),...reachable.filter(id=>!orderedSet.has(id))]:[...ordered.filter(id=>doc.talks?.[id]),...Object.keys(doc.talks||{}).map(Number).filter(id=>!orderedSet.has(id))];
 const entries=[];for(const id of [...new Set(selected.map(Number))]){const entry=line(doc,id);if(!entry)continue;const talk=doc.talks[id];entries.push({...entry,nextTalk:ids(talk.nextTalk),nextTalk2:ids(talk.nextTalk2)});for(const optionId of ids(talk.option)){const option=doc.options?.[optionId];entries.push({kind:'option',optionId,content:option?.content||'未载入的选项',targetTalkIds:ids(option?.talkId),alternateTalkIds:ids(option?.talkId2),eventId:Number(option?.nextEvtId)||null});}}
 return {version:1,kind:'full-story',title:event?.title||'当前模组全部对话',policy:'剧情清单包含所有可达分支。它不是实际播放历史；共享或循环节点只列一次，接续的其他事件不递归展开。',sessions:[{id:1,title:event?.title||'当前模组全部对话',entries}]};
}
function storyIds(doc,eventId){
 const event=doc.events?.[eventId],seen=new Set(),stack=ids(event?.talkId).reverse(),reachable=[];
 while(stack.length){const id=stack.pop();if(seen.has(id)||!doc.talks?.[id])continue;seen.add(id);reachable.push(id);const t=doc.talks[id],next=[...ids(t.nextTalk),...ids(t.nextTalk2)];for(const optionId of ids(t.option)){const o=doc.options?.[optionId];next.push(...ids(o?.talkId),...ids(o?.talkId2));}stack.push(...next.reverse());}
 return reachable;
}
function dialogueRows(doc,eventId,order,branchFolders,{Timeline,Branches,encode}){
 const hidden=Timeline.internals(branchFolders),document=fullStory(doc,eventId,order);
 const folders={...branchFolders};
 // Unmanaged native options still export their linear dialogue paths.
 for(const t of Object.values(doc.talks))for(const oid of ids(t.option))if(!folders[Branches.key(t.id,oid)]){
  const members=[],visited=new Set([Number(t.id),...Timeline.next(doc,folders,t.id)]);let id=ids(doc.options[oid]?.talkId)[0];
  while(id&&doc.talks[id]&&!visited.has(id)){visited.add(id);if(!hidden.has(id))members.push(id);id=Timeline.next(doc,folders,id)[0];}
  folders[Branches.key(t.id,oid)]={parentTalkId:Number(t.id),optionId:oid,talkIds:members};
 }
 const rows=document.sessions.flatMap(session=>session.entries).filter(row=>row.kind==='dialogue'&&!hidden.has(row.talkId)),byId=new Map(rows.map(r=>[r.talkId,r])),tokens=[],seen=new Set(),groupsByParent=new Map(),owned=new Set();
 for(const f of Object.values(folders)){const parent=Number(f.parentTalkId);if(!groupsByParent.has(parent))groupsByParent.set(parent,[]);groupsByParent.get(parent).push(f);for(const id of ids(f.talkIds))owned.add(id);}
 for(const groups of groupsByParent.values())groups.sort((a,b)=>(a.branchId||0)-(b.branchId||0));
 function emit(row,depth=0){if(!row||seen.has(row.talkId))return;seen.add(row.talkId);tokens.push(row);
  const groups=groupsByParent.get(row.talkId)||[];
  for(const f of groups){tokens.push({marker:'\t'.repeat(depth)+(f.kind==='condition'?'分支'+f.branchId:'选项 '+encode(doc.options[f.optionId]?.content||'未命名选项'))});for(const id of ids(f.talkIds))emit(byId.get(id),depth+1);if(f.kind==='condition')tokens.push({marker:'\t'.repeat(depth)+'。'});}
  if(groups.some(f=>f.kind!=='condition'))tokens.push({marker:'\t'.repeat(depth)+'。'});
 }
 for(const row of rows)if(!owned.has(row.talkId))emit(row);
 for(const row of rows)emit(row);
 Object.defineProperty(rows,'tokens',{value:tokens});return rows;
}
async function allStories(doc,eventIds,{order=[],branchFolders={},Timeline,Branches,text,load=async()=>{},progress=()=>{}}){
 if(!eventIds.length)throw Error('当前模组没有可导出的事件。');
 const out=['全部剧情',''],rank=new Map(order.map((id,index)=>[Number(id),index]));
 for(let index=0;index<eventIds.length;index++){
  const id=eventIds[index],event=doc.events?.[id];if(!event)throw Error('事件已变化，请重新导出。');
  const keys=storyIds(doc,id),talks={};
  // Copy each page before loading the next; an all-story export never depends on
  // the current event, visible page, text cache residency or a save/reopen cycle.
  for(let offset=0;offset<keys.length;offset+=100){const page=keys.slice(offset,offset+100);await load(page);for(const key of page)talks[key]=clone(doc.talks[key]);}
  const scoped={...doc,talks},selected=new Set(keys),folders=Object.fromEntries(Object.entries(branchFolders).filter(([,f])=>selected.has(Number(f.parentTalkId))));
  const sorted=keys.slice().sort((a,b)=>(rank.get(a)??Infinity)-(rank.get(b)??Infinity));
  out.push(`【${event.title||event.name||'未命名事件'} · ${id}】`);
  if(event.content)out.push(String(event.content));
  out.push(text.serialize(dialogueRows(scoped,id,sorted,folders,{Timeline,Branches,encode:text.encode})).trimEnd());
  const missing=new Set(ids(event.talkId).filter(key=>key>0&&!talks[key]));
  for(const t of Object.values(talks)){const targets=[...ids(t.nextTalk),...ids(t.nextTalk2)];for(const oid of ids(t.option)){const o=doc.options?.[oid];targets.push(...ids(o?.talkId),...ids(o?.talkId2));if(o?.nextEvtId)out.push(`接续事件：${o.nextEvtId}`);}for(const key of targets)if(key>0&&!talks[key])missing.add(key);}
  if(missing.size)out.push('引用外部对话（当前模组未载入）：'+[...missing].join('、'));
  if(!keys.length&&!event.content&&!missing.size)out.push('（暂无对话）');
  out.push('');progress(index+1,eventIds.length);
 }
 return out.join('\n').trimEnd()+'\n';
}
function serialize(document,format='txt'){
 if(format==='json')return JSON.stringify(document,null,2)+'\n';
 const markdown=format==='md',out=[(markdown?'# ':'')+(document.kind==='played-history'?'实际预演历史':'剧情全部对话'),document.policy||'',''];
 for(const session of document.sessions||[]){out.push((markdown?'## ':'')+(document.kind==='played-history'?'第 '+session.id+' 轮 · ':'')+session.title,'');for(const entry of session.entries||[]){if(entry.kind==='dialogue'){out.push(entry.speaker+'：',entry.content,'');}else if(entry.kind==='choice'){out.push('【已选择】'+entry.content);if(entry.route&&entry.route!==entry.content)out.push('路线：'+entry.route);out.push('');}else if(entry.kind==='option'){out.push('【可选项】'+entry.content);if(entry.targetTalkIds?.length)out.push('普通去向：'+entry.targetTalkIds.join(' / '));if(entry.alternateTalkIds?.length)out.push('备用去向：'+entry.alternateTalkIds.join(' / '));out.push('');}}}
 return out.join('\n').replace(/\n+$/,'')+'\n';
}
function filename(title,kind,format){return String(title||'学生时代').replace(/[\\/:*?"<>|\u0000-\u001f]/g,'_').trim().slice(0,80)+'-'+(kind==='played-history'?'预演历史':'全部对话')+'.'+format;}
return {Recorder,line,fullStory,storyIds,dialogueRows,allStories,serialize,filename};
});
