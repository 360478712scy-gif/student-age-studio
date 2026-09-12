(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeEventOwnership=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';const ids=v=>Array.isArray(v)?v.map(Number).filter(Number.isFinite):[];
function ownership(doc,folders,previous=doc.talkOwners||{}){
 const owners={},edges={};for(const [t,v]of Object.entries(previous))if(doc.talks[t])owners[t]=new Set(ids(v).filter(e=>doc.events[e]));
 for(const [t,r]of Object.entries(doc.talks))edges[t]=[...ids(r.nextTalk),...ids(r.nextTalk2),...ids(r.option).flatMap(o=>[...ids(doc.options[o]?.talkId),...ids(doc.options[o]?.talkId2)])];
 for(const f of Object.values(folders||{}))(edges[f.parentTalkId]??=[]).push(...ids(f.talkIds),...[f.routerId,f.exitId,f.endId].filter(v=>v!=null).map(Number));
 const retained={};for(const [t,v]of Object.entries(owners))for(const e of v)(retained[e]??=[]).push(Number(t));
 for(const [key,e]of Object.entries(doc.events)){const id=Number(key),seen=new Set(),todo=[...ids(e.talkId),...ids(e.options).flatMap(o=>[...ids(doc.options[o]?.talkId),...ids(doc.options[o]?.talkId2)]),...(retained[id]||[])];while(todo.length){const t=todo.pop();if(seen.has(t)||!doc.talks[t])continue;seen.add(t);(owners[t]??=new Set()).add(id);todo.push(...(edges[t]||[]));}}
 return Object.fromEntries(Object.entries(owners).filter(([,v])=>v.size).map(([t,v])=>[t,[...v].sort((a,b)=>a-b)]));
}
function sync(doc,folders,currentEvent,beforeIds){
 const previous=doc.talkOwners||{};if(beforeIds&&doc.events[currentEvent])for(const t of Object.keys(doc.talks))if(!beforeIds.has(t))previous[t]=[Number(currentEvent)];
 doc.talkOwners=ownership(doc,folders,previous);
}
function interactionTalks(doc){const found=new Set(),todo=Object.values(doc.interactions||{}).map(r=>Number(r.talkId)).filter(Boolean);while(todo.length){const id=todo.pop(),r=doc.talks[id];if(!r||found.has(id))continue;found.add(id);todo.push(...ids(r.nextTalk),...ids(r.nextTalk2),...ids(r.option).flatMap(o=>[...ids(doc.options?.[o]?.talkId),...ids(doc.options?.[o]?.talkId2)]));}return found;}
function plan(doc,folders,eventIds,localIds){const owners=ownership(doc,folders),removed=new Set(eventIds.map(Number)),local=new Set(localIds.map(Number)),idle=interactionTalks(doc);
 const talks=new Set(Object.keys(doc.talks).map(Number).filter(t=>(owners[t]||[]).some(e=>removed.has(e))));
 const options=new Set([...eventIds.flatMap(e=>ids(doc.events[e]?.options)),...[...talks].flatMap(t=>ids(doc.talks[t]?.option))]);return {talks,options};
}
return {ownership,sync,plan,interactionTalks};});
