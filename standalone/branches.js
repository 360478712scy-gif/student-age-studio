(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeBranches=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';
const ids=value=>Array.isArray(value)?value.map(Number).filter(Number.isFinite):[];
const key=(parent,option)=>Number(parent)+':'+Number(option);
const optionParents=(doc,option)=>Object.values(doc.talks||{}).filter(t=>ids(t.option).includes(Number(option))).map(t=>Number(t.id));
const ownedBy=(folders,talkId)=>Object.entries(folders||{}).find(([,f])=>ids(f.talkIds).includes(Number(talkId)))?.[0]||null;
function describe(doc,folders,parentTalkId,optionId){
 const id=key(parentTalkId,optionId),folder=folders?.[id],option=doc.options?.[optionId];
 return {key:id,parentTalkId:Number(parentTalkId),optionId:Number(optionId),folder,option,managed:!!folder,
  talkIds:ids(folder?.talkIds).filter(id=>doc.talks?.[id]),references:folder?[]:[...new Set([...ids(option?.talkId),...ids(option?.talkId2)])],shared:optionParents(doc,optionId).length>1};
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
function cleanup(doc,folders,replacements={}){
 const deleted=id=>Object.prototype.hasOwnProperty.call(replacements,id);
 const out={};for(const [id,old]of Object.entries(folders||{})){
  if(deleted(old.parentTalkId)||(old.kind!=='condition'&&doc.talks?.[old.parentTalkId]&&!ids(doc.talks[old.parentTalkId].option).includes(Number(old.optionId))))continue;
  const f=JSON.parse(JSON.stringify(old));f.talkIds=ids(f.talkIds).filter(t=>!deleted(t));
  if(f.continuation?.kind==='talk'&&deleted(f.continuation.talkId)){const next=[...new Set(ids(replacements[f.continuation.talkId]).filter(t=>t>0&&!deleted(t)))];f.continuation=next.length===1?{kind:'talk',talkId:next[0]}:{kind:'end'};}
  if(Array.isArray(f.failureNext))f.failureNext=f.failureNext.flatMap(t=>deleted(t)?ids(replacements[t]):[t]);
  out[id]=f;
 }return out;
}
return {ids,key,optionParents,ownedBy,describe,initialContinuation,create,targets,insert,setContinuation,cleanup};
});
