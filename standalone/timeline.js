(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeTimeline=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';
const ids=v=>Array.isArray(v)?v.map(Number).filter(Number.isFinite):[],copy=v=>JSON.parse(JSON.stringify(v));
const entries=(folders,parent)=>Object.entries(folders||{}).filter(([,f])=>f.kind==='condition'&&Number(f.parentTalkId)===Number(parent)).sort((a,b)=>a[1].branchId-b[1].branchId);
const internals=folders=>new Set(Object.values(folders||{}).filter(f=>f.kind==='condition').flatMap(f=>[f.routerId,f.exitId,f.endId]).map(Number));
const owner=(folders,id)=>Object.entries(folders||{}).find(([,f])=>ids(f.talkIds).includes(Number(id)))?.[0]||null;
const next=(doc,folders,id)=>ids(entries(folders,id)[0]?.[1]?.baseNext??doc.talks[id]?.nextTalk);
function targets(doc,c){
 if(c?.kind==='talk')return [Number(c.talkId)];
 if(c?.kind==='targets')return ids(c.targets);
 return [];
}
function sync(doc,folders,parent){
 const group=entries(folders,parent);if(!group.length)return;
 const first=group[0][1],base=ids(first.baseNext),row=doc.talks[parent];if(!row)return;
 row.nextTalk=[first.routerId];row.nextTalk2=[];row.check=[];
 group.forEach(([,f],i)=>{
  f.baseNext=base.slice();f.endId=first.endId;
  const router=doc.talks[f.routerId],exit=doc.talks[f.exitId];
  if(!router||!exit)throw Error('分支连接不完整，请撤销后重试。');
  router.nextTalk=[ids(f.talkIds)[0]||f.exitId];
  router.nextTalk2=Array.isArray(f.failureNext)?(ids(f.failureNext).length?ids(f.failureNext):[f.endId]):i+1<group.length?[group[i+1][1].routerId]:base.length?base.slice():[f.endId];
  exit.nextTalk=f.continuation?.kind==='following'?base.slice():targets(doc,f.continuation);
 });
}
function setFailure(doc,folders,folder,value){
 if(folder.kind!=='condition')throw Error('请选择条件分支。');
 if(value!==null&&(!Array.isArray(value)||ids(value).some(id=>!doc.talks[id]||id===Number(folder.parentTalkId)||internals(folders).has(id))))throw Error('请选择有效的失败对话。');
 folder.failureNext=value===null?null:ids(value);sync(doc,folders,folder.parentTalkId);
}
function setNext(doc,folders,id,value){
 const group=entries(folders,id);
 if(group.length){for(const [,f]of group)f.baseNext=ids(value);sync(doc,folders,id);}
 else doc.talks[id].nextTalk=ids(value);
}
const blank=id=>({id,content:'',roleIds:[],roles:[],option:[],check:[],effect:[],effect2:[],nextTalk:[],nextTalk2:[],highlights:[],screenEffect:[]});
function addCondition(doc,folders,parent,allocate){
 const row=doc.talks[parent];if(!row)throw Error('请先选择一句对话。');
 if(ids(row.option).length||row.miniGame?.length)throw Error('这句已有玩家选项或小游戏，请在对应对话夹内添加条件分支。');
 let group=entries(folders,parent);
 const make=(check,continuation,base,endId)=>{
  const branchId=Math.max(0,...entries(folders,parent).map(([,f])=>f.branchId))+1;
  const routerId=allocate();doc.talks[routerId]=blank(routerId);doc.talks[routerId].check=copy(check||[]);
  const exitId=allocate();doc.talks[exitId]=blank(exitId);
  const f={kind:'condition',parentTalkId:Number(parent),branchId,routerId,exitId,endId,baseNext:base.slice(),talkIds:[],continuation,collapsed:false};
  const key=parent+':branch:'+branchId;folders[key]=f;return {key,folder:f};
 };
 let endId,base;
 if(group.length){endId=group[0][1].endId;base=ids(group[0][1].baseNext);}
 else {
  base=ids(row.nextTalk);endId=allocate();doc.talks[endId]=blank(endId);
  if(row.check?.length){const success=base.slice();base=ids(row.nextTalk2);if(!base.length||!base[0])base=success.slice();make(row.check,{kind:'targets',targets:success},base,endId);}
 }
 const result=make([],{kind:'following'},base,endId);sync(doc,folders,parent);return result;
}
function insert(doc,folders,folder,row,after=null){
 const members=ids(folder.talkIds),index=after===null?members.length-1:members.indexOf(Number(after));
 if(after!==null&&index<0)throw Error('这句不属于当前对话夹。');
 const previous=doc.talks[members[index]],option=doc.options[folder.optionId];
 if(!folder.kind&&Object.values(doc.talks).filter(t=>ids(t.option).includes(folder.optionId)).length>1)throw Error('这个选项被多句共用，请先制作独立选项。');
 if(previous&&(ids(previous.option).length||previous.miniGame?.length||(!entries(folders,previous.id).length&&(previous.check?.length||ids(previous.nextTalk2).length))))throw Error('请在这句的子分支中添加对话。');
 row.nextTalk=previous?next(doc,folders,previous.id):folder.kind==='condition'?[folder.exitId]:ids(option?.talkId);
 if(!row.nextTalk.length&&folder.continuation?.kind==='talk')row.nextTalk=targets(doc,folder.continuation);
 if(previous)setNext(doc,folders,previous.id,[row.id]);else if(option){option.talkId=[row.id];option.nextEvtId=0;}
 doc.talks[row.id]=row;members.splice(index+1,0,row.id);folder.talkIds=members;
 if(folder.kind==='condition')sync(doc,folders,folder.parentTalkId);
}
function setContinuation(doc,folders,folder,c){
 const members=ids(folder.talkIds),last=members.at(-1),dest=targets(doc,c);
 if(dest.some(id=>members.includes(id)||id===folder.parentTalkId||!doc.talks[id]))throw Error('请选择对话夹以外的有效接续对话。');
 if(c.kind==='event'&&!doc.events[c.eventId])throw Error('后续事件不存在。');
 if(folder.kind==='condition'){folder.continuation=copy(c);sync(doc,folders,folder.parentTalkId);return;}
 if(last){const t=doc.talks[last];if(ids(t.option).length||t.miniGame?.length||(!entries(folders,last).length&&(t.check?.length||ids(t.nextTalk2).length)))throw Error('末句已有子分支，请设置子分支的接续。');setNext(doc,folders,last,c.kind==='following'?next(doc,folders,folder.parentTalkId):dest);}
 else {doc.options[folder.optionId].talkId=c.kind==='following'?next(doc,folders,folder.parentTalkId):dest;doc.options[folder.optionId].nextEvtId=c.kind==='event'?c.eventId:0;}
 folder.continuation=copy(c);
}
function replace(doc,folders,from,to,except=new Set()){
 const repair=v=>ids(v).flatMap(id=>id===from?ids(to):[id]);
 for(const t of Object.values(doc.talks))if(!except.has(Number(t.id))){t.nextTalk=repair(t.nextTalk);t.nextTalk2=repair(t.nextTalk2);}
 for(const table of [doc.options,doc.events])for(const r of Object.values(table||{})){r.talkId=repair(r.talkId);if('talkId2'in r)r.talkId2=repair(r.talkId2);}
 for(const f of Object.values(folders)){if(f.kind==='condition'){f.baseNext=repair(f.baseNext);if(Array.isArray(f.failureNext))f.failureNext=repair(f.failureNext);}if(f.continuation?.kind==='talk'&&Number(f.continuation.talkId)===from)f.continuation=to.length?{kind:'talk',talkId:to[0]}:{kind:'end'};if(f.continuation?.kind==='targets')f.continuation.targets=repair(f.continuation.targets);}
}
function reorder(doc,folders,order,source,target,after=false){
 source=Number(source);target=Number(target);if(source===target)return order.slice();
 const lane=owner(folders,source);if(lane!==owner(folders,target))throw Error('请在同一个对话夹内拖动；分支会跟随所属对话。');
 const hidden=internals(folders),all=order.filter(id=>doc.talks[id]&&!hidden.has(id)&&owner(folders,id)===lane);
 const start=all.indexOf(source),end=all.indexOf(target);if(start<0||end<0)throw Error('对话已变化。');
 let dest=end+(after?1:0);if(dest>start)dest--;if(dest===start)return order.slice();
 const lo=Math.min(start,dest),hi=Math.max(start,dest),segment=all.slice(lo,hi+1),last=segment.at(-1);
 for(let i=0;i<segment.length;i++){
  const t=doc.talks[segment[i]];
  if(!entries(folders,t.id).length&&(t.check?.length||ids(t.nextTalk2).length)||t.miniGame?.length)throw Error('这段有原有条件出口，请先将它整理为左侧条件分支。');
  if(i<segment.length-1&&(next(doc,folders,t.id).length!==1||next(doc,folders,t.id)[0]!==segment[i+1]))throw Error('这些对话属于不同播放路线，不能合并排序。');
 }
 const tail=next(doc,folders,last);if(tail.some(id=>segment.includes(id)))throw Error('这段有循环连接，不能直接排序。');
 const sorted=segment.slice();sorted.splice(sorted.indexOf(source),1);sorted.splice(dest-lo,0,source);
 // Internal links are rebuilt below. Outside entries keep pointing at the first
 // position of this sequence; references to other lines keep their identities.
 replace(doc,folders,segment[0],[sorted[0]],new Set([...segment,...hidden]));
 for(let i=0;i<sorted.length;i++)setNext(doc,folders,sorted[i],i+1<sorted.length?[sorted[i+1]]:tail);
 if(lane){const f=folders[lane],a=f.talkIds.indexOf(segment[0]);f.talkIds.splice(a,segment.length,...sorted);if(f.kind==='condition')sync(doc,folders,f.parentTalkId);else doc.options[f.optionId].talkId=[f.talkIds[0]];}
 const newLane=all.slice(),laneSet=new Set(all);newLane.splice(lo,segment.length,...sorted);let at=0;
 return order.map(id=>laneSet.has(id)?newLane[at++]:id);
}
function removeFolder(doc,folders,key){
 const parentId=Number(key.split(':')[0]),parent=doc.talks[parentId];
 if(!parent)throw Error('所属对话已不存在。');
 if(key.endsWith(':legacy')){parent.nextTalk=ids(parent.nextTalk2).filter(id=>id>0).length?ids(parent.nextTalk2):ids(parent.nextTalk);parent.nextTalk2=[];parent.check=[];return {parentId,deleted:[],replacements:{}};}
 const root=folders[key],conditional=root?.kind==='condition',optionId=Number(key.split(':')[1]);
 if(!root&&!ids(parent.option).includes(optionId))throw Error('这个对话夹已不存在。');
 const base=conditional?ids(root.baseNext):next(doc,folders,parentId),removedKeys=new Set([key]),dead=new Set(),optionIds=new Set();
 if(!conditional){parent.option=ids(parent.option).filter(id=>id!==optionId);optionIds.add(optionId);}
 const sharedOption=id=>Object.values(doc.talks).some(t=>!dead.has(Number(t.id))&&ids(t.option).includes(id))||Object.values(doc.events||{}).some(e=>ids(e.options).includes(id));
 const collect=f=>{for(const id of ids(f.talkIds))dead.add(id);if(f.kind==='condition'){dead.add(Number(f.routerId));dead.add(Number(f.exitId));}else optionIds.add(Number(f.optionId));};
 if(root&&(conditional||!sharedOption(optionId)))collect(root);
 let changed=true;
 while(changed){changed=false;for(const [id,f]of Object.entries(folders))if(!removedKeys.has(id)&&dead.has(Number(f.parentTalkId))){removedKeys.add(id);collect(f);changed=true;}}
 // Sibling conditions share one end marker; retain it until the last branch is removed.
 for(const id of removedKeys){const f=folders[id];if(f?.kind==='condition'&&!Object.entries(folders).some(([other,g])=>!removedKeys.has(other)&&g.kind==='condition'&&g.endId===f.endId))dead.add(Number(f.endId));}
 for(const id of dead)for(const oid of ids(doc.talks[id]?.option))optionIds.add(oid);
 for(const id of removedKeys)delete folders[id];
 const continuation=base.filter(id=>!dead.has(id)),replacements={};
 for(const id of dead){delete doc.talks[id];replacements[id]=continuation.slice();replace(doc,folders,id,continuation);}
 for(const oid of optionIds)if(!sharedOption(oid))delete doc.options[oid];
 if(conditional&&!entries(folders,parentId).length){parent.nextTalk=continuation;parent.nextTalk2=[];parent.check=[];}
 for(const id of new Set(Object.values(folders).filter(f=>f.kind==='condition').map(f=>f.parentTalkId)))sync(doc,folders,id);
 return {parentId,deleted:[...dead],replacements};
}

return {ids,entries,internals,owner,next,setNext,setFailure,sync,blank,addCondition,insert,setContinuation,replace,reorder,removeFolder};
});
