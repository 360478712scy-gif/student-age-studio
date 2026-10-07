(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeBranches=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';
const ids=value=>Array.isArray(value)?value.map(Number).filter(Number.isFinite):[];
const key=(parent,option)=>Number(parent)+':'+Number(option);
function optionParents(doc,option){
 const rows=doc.talks||{},remote=globalThis.StudentAgeRemoteTalks?.info?.(rows);
 if(!remote)return Object.values(rows).filter(t=>ids(t.option).includes(Number(option))).map(t=>Number(t.id));
 // Graph fields are already present in the segmented directory. Reading them
 // directly avoids creating a row and array Proxy for every untouched line.
 const parents=[],wanted=Number(option);for(const id of remote.keys()){const options=remote.read(id,'option');if(Array.isArray(options)&&options.length&&ids(options).includes(wanted))parents.push(Number(remote.read(id,'id')));}return parents;
}
const ownedBy=(folders,talkId)=>Object.entries(folders||{}).find(([,f])=>ids(f.talkIds).includes(Number(talkId)))?.[0]||null;
// Callers rendering many cards pass optionParentCounts(doc) so each card does not rescan every talk.
const optionParentCounts=doc=>{
 const rows=doc.talks||{},remote=globalThis.StudentAgeRemoteTalks?.info?.(rows),counts=new Map(),add=options=>{if(!Array.isArray(options)||!options.length)return;for(const o of new Set(ids(options)))counts.set(o,(counts.get(o)||0)+1);};
 if(remote)for(const id of remote.keys())add(remote.read(id,'option'));else for(const t of Object.values(rows))add(t.option);return counts;
};
function describe(doc,folders,parentTalkId,optionId,counts=null){
 const id=key(parentTalkId,optionId),folder=folders?.[id],option=doc.options?.[optionId];
 return {key:id,parentTalkId:Number(parentTalkId),optionId:Number(optionId),folder,option,managed:!!folder,
  talkIds:ids(folder?.talkIds).filter(id=>doc.talks?.[id]),references:folder?[]:[...new Set([...ids(option?.talkId),...ids(option?.talkId2)])],shared:(counts?counts.get(Number(optionId))||0:optionParents(doc,optionId).length)>1};
}
function initialContinuation(option){
 if(ids(option?.talkId).length>1)throw Error('这个选项有多个普通入口。请在选项设置中明确普通入口后，再添加文件夹内的对话。');
 if(option?.nextEvtId&&!ids(option.talkId).length)return {kind:'event',eventId:Number(option.nextEvtId)};
 const target=ids(option?.talkId)[0];return target?{kind:'talk',talkId:target}:{kind:'end'};
}
function create(doc,folders,parentTalkId,optionId){
 const id=key(parentTalkId,optionId);if(folders[id])return folders[id];
 if(!doc.talks?.[parentTalkId]||!ids(doc.talks[parentTalkId].option).includes(Number(optionId))||!doc.options?.[optionId])throw Error('所属对话或选项已变化，请重新选择。');
 if(optionParents(doc,optionId).length>1)throw Error('这个选项被多句共用，请先为当前对话制作独立选项。');
 const folder={parentTalkId:Number(parentTalkId),optionId:Number(optionId),talkIds:[],continuation:initialContinuation(doc.options[optionId]),collapsed:false};folders[id]=folder;return folder;
}
function targets(doc,continuation){
 if(continuation?.kind==='talk'){if(!doc.talks?.[continuation.talkId])throw Error('接续对话不存在。');return [Number(continuation.talkId)];}
 if(continuation?.kind==='event'){const event=doc.events?.[continuation.eventId],starts=ids(event?.talkId);if(!event||starts.length!==1||!doc.talks?.[starts[0]])throw Error('请选择有一个明确起始对话的后续剧情。');return starts;}
 return [];
}
function insert(doc,folders,folder,row,afterId=null){
 if(optionParents(doc,folder.optionId).length>1)throw Error('这个选项被多句共用，请先为当前对话制作独立选项。');
 const members=ids(folder.talkIds),index=afterId!==null?members.indexOf(Number(afterId)):members.length-1;
 if(afterId!==null&&index<0)throw Error('所选对话不属于这个文件夹。');
 if(doc.talks[row.id]||ownedBy(folders,row.id)||Number(row.id)===Number(folder.parentTalkId))throw Error('对话编号已被使用。');
 const previous=index>=0?doc.talks[members[index]]:null,option=doc.options[folder.optionId];
 if(previous&&(ids(previous.nextTalk).length>1||ids(previous.nextTalk2).length||previous.check?.length||ids(previous.option).length||previous.miniGame?.length))throw Error('这句有条件、子选项或小游戏，请先处理这些出口，再添加后续对话。');
 const next=previous?ids(previous.nextTalk):ids(option.talkId);
 row.nextTalk=next.length?next:folder.continuation?.kind==='event'?[]:targets(doc,folder.continuation);
 if(previous)previous.nextTalk=[Number(row.id)];else option.talkId=[Number(row.id)];
 option.nextEvtId=0;
 doc.talks[row.id]=row;members.splice(index+1,0,Number(row.id));folder.talkIds=members;
 return Number(row.id);
}
function setContinuation(doc,folder,continuation){
 if(optionParents(doc,folder.optionId).length>1)throw Error('这个选项被多句共用，请先为当前对话制作独立选项。');
 const event=continuation?.kind==='event'?doc.events?.[continuation.eventId]:null;
 if(continuation?.kind==='event'&&!event)throw Error('后续剧情不存在。');
 const next=continuation?.kind==='event'?[]:targets(doc,continuation),members=ids(folder.talkIds),last=members.length?doc.talks[members[members.length-1]]:null;
 if(next.some(id=>members.includes(id)||id===Number(folder.parentTalkId)))throw Error('文件夹末尾不能接回本文件夹或所属对话。原有循环仍可在原始出口中保留。');
 if(last&&(last.check?.length||ids(last.nextTalk2).length||ids(last.nextTalk).length>1||ids(last.option).length||last.miniGame?.length))throw Error('文件夹末句已有条件、子选项或小游戏，请先处理该句的出口。');
 const option=doc.options[folder.optionId];
 if(last){last.nextTalk=next;if(continuation?.kind==='event')last.nextTalk2=[];option.nextEvtId=0;}
 else {option.talkId=next;option.nextEvtId=continuation?.kind==='event'?Number(continuation.eventId):0;}
 folder.continuation=JSON.parse(JSON.stringify(continuation));
}
const sameIds=(a,b)=>JSON.stringify(ids(a))===JSON.stringify(ids(b));
function conditionIntact(doc,folder){
 if(!doc.talks?.[folder.parentTalkId])return false;
 const hasText=row=>globalThis.StudentAgeRemoteTalks?.hasText?.(row)??!!String(row.content||'').trim();
 const helpers=[folder.routerId,folder.exitId,folder.endId].map(Number);
 if(helpers.some(id=>!Number.isInteger(id)||id<=0||id===Number(folder.parentTalkId))||new Set(helpers).size!==3)return false;
 for(const id of helpers){const row=doc.talks[id];if(!row||hasText(row)||['roleIds','roles','option','effect','effect2','screenEffect','highlights','miniGame'].some(field=>row[field]?.length))return false;}
 const exit=doc.talks[folder.exitId],end=doc.talks[folder.endId];
 if(exit.check?.length||ids(exit.nextTalk2).length||end.check?.length||ids(end.nextTalk).length||ids(end.nextTalk2).length)return false;
 return ids(folder.talkIds).every(id=>doc.talks[id]&&!helpers.includes(id));
}
// Editor ownership is disposable. Native rows and their current edges are the
// authority after another editor changes or deletes a branch.
function conditionKeys(doc,folders){
 const groups=new Map(),kept=new Set();
 for(const [key,f]of Object.entries(folders||{}))if(f?.kind==='condition'&&conditionIntact(doc,f)){const parent=Number(f.parentTalkId);if(!groups.has(parent))groups.set(parent,[]);groups.get(parent).push([key,f]);}
 for(const [parent,group]of groups){
  const row=doc.talks[parent],start=ids(row.nextTalk);if(start.length!==1||ids(row.nextTalk2).length||row.check?.length||ids(row.option).length||row.miniGame?.length)continue;
  group.sort((a,b)=>Number(a[1].branchId)-Number(b[1].branchId));const at=group.findIndex(([,f])=>Number(f.routerId)===start[0]);if(at<0)continue;
  const path=[];
  for(let i=at;i<group.length;i++){
   const [key,f]=group[i],router=doc.talks[f.routerId],exit=doc.talks[f.exitId],members=ids(f.talkIds),base=ids(f.baseNext),c=f.continuation;
   const following=c?.kind==='following'?base:c?.kind==='talk'?[Number(c.talkId)]:c?.kind==='targets'?ids(c.targets):[];
   if(!sameIds(router.nextTalk,[members[0]||Number(f.exitId)])||!sameIds(exit.nextTalk,following))break;
   const custom=Array.isArray(f.failureNext),failure=custom?(ids(f.failureNext).length?f.failureNext:[f.endId]):i+1<group.length?[group[i+1][1].routerId]:base.length?base:[f.endId];
   if(!sameIds(router.nextTalk2,failure))break;
   path.push(key);
   // An explicit failure override can bypass later, still-authored branches.
   // Keep those drafts when their own native connectors remain consistent.
   if(custom||i===group.length-1){for(const id of path)kept.add(id);path.length=0;}
  }
 }
 return kept;
}
function cleanup(doc,folders,replacements={}){
 const deleted=id=>Object.prototype.hasOwnProperty.call(replacements,id);
 const authored=new Set();
 const out={};for(const [id,old]of Object.entries(folders||{})){
  if(!old||typeof old!=='object')continue;
  if(deleted(old.parentTalkId)||(old.kind!=='condition'&&doc.talks?.[old.parentTalkId]&&!ids(doc.talks[old.parentTalkId].option).includes(Number(old.optionId))))continue;
  const f=JSON.parse(JSON.stringify(old));f.talkIds=ids(f.talkIds).filter(t=>!deleted(t));
  if(f.kind==='condition'&&ids(old.talkIds).some(deleted))authored.add(id);
  if(f.continuation?.kind==='talk'&&deleted(f.continuation.talkId)){const next=[...new Set(ids(replacements[f.continuation.talkId]).filter(t=>t>0&&!deleted(t)))];f.continuation=next.length===1?{kind:'talk',talkId:next[0]}:{kind:'end'};}
  if(Array.isArray(f.failureNext))f.failureNext=f.failureNext.flatMap(t=>deleted(t)?ids(replacements[t]):[t]);
  out[id]=f;
 }
 const conditions=conditionKeys(doc,out);
 for(const [id,f]of Object.entries(out))if(f.kind==='condition'&&!conditions.has(id)&&!(authored.has(id)&&conditionIntact(doc,f)))delete out[id];
 return out;
}
return {ids,key,optionParents,optionParentCounts,ownedBy,describe,initialContinuation,create,targets,insert,setContinuation,conditionIntact,conditionKeys,cleanup};
});
