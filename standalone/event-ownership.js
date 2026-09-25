(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeEventOwnership=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';const ids=v=>Array.isArray(v)?v.map(Number).filter(Number.isFinite):[];
function links(doc,folders){
 const edges={},talks=new Set(Object.keys(doc.talks));for(const t of talks){const r=doc.talks[t];edges[t]=[...ids(r.nextTalk),...ids(r.nextTalk2),...ids(r.option).flatMap(o=>[...ids(doc.options[o]?.talkId),...ids(doc.options[o]?.talkId2)])];}
 for(const f of Object.values(folders||{}))(edges[f.parentTalkId]??=[]).push(...ids(f.talkIds),...[f.routerId,f.exitId,f.endId].filter(v=>v!=null).map(Number));
 const reverse={};for(const [src,dests]of Object.entries(edges))for(const dest of dests)(reverse[dest]??=[]).push(Number(src));
 return {edges,reverse,talks};
}
// `talks` is the set of existing talk keys from links(); lookups through segmented-talk proxies are costly.
function walk(talks,edges,todo,assign,allow){const seen=new Set();while(todo.length){const t=todo.pop();if(seen.has(t)||!talks.has(String(t)))continue;seen.add(t);if(allow&&!allow(t))continue;assign(t);todo.push(...(edges[t]||[]));}}
function forward(talks,doc,edges){
 const reached={};
 for(const [key,e]of Object.entries(doc.events)){const id=Number(key);walk(talks,edges,[...ids(e.talkId),...ids(e.options).flatMap(o=>[...ids(doc.options[o]?.talkId),...ids(doc.options[o]?.talkId2)])],t=>(reached[t]??=new Set()).add(id));}
 return reached;
}
function listed(reached){return Object.fromEntries(Object.entries(reached).filter(([,v])=>v.size).map(([t,v])=>[t,[...v].sort((a,b)=>a-b)]));}
// Shown beside an event. Not membership: external dialogues stay in their own list.
function display(doc,folders){
 const {edges,reverse,talks}=links(doc,folders),reached=forward(talks,doc,edges),entered=new Set(Object.keys(reached).map(Number));
 const byEvent={};for(const [talk,evs]of Object.entries(reached))for(const id of evs)(byEvent[id]??=[]).push(Number(talk));
 for(const [event,members]of Object.entries(byEvent)){const id=Number(event),todo=members.slice(),seen=new Set(members),fresh=[];while(todo.length){const current=todo.pop();for(const prev of reverse[current]||[]){if(entered.has(prev)||seen.has(prev)||!talks.has(String(prev)))continue;seen.add(prev);(reached[prev]??=new Set()).add(id);todo.push(prev);fresh.push(prev);}}walk(talks,edges,fresh,t=>(reached[t]??=new Set()).add(id),t=>!(entered.has(t)&&!(reached[t]&&reached[t].has(id))));}
 // Bucket talks and options by their event-number prefix once; scanning all talks per event is quadratic on large mods.
 const talksByEvent=new Map(),optionsByEvent=new Map();
 for(const key of talks){const t=Number(key),e=Math.floor(t/1000);if(!talksByEvent.has(e))talksByEvent.set(e,[]);talksByEvent.get(e).push(t);}
 for(const [oid,row]of Object.entries(doc.options||{})){const e=Math.floor(Number(oid)/100);if(!optionsByEvent.has(e))optionsByEvent.set(e,[]);optionsByEvent.get(e).push(row);}
 for(const key of Object.keys(doc.events)){const id=Number(key);if(!id)continue;const seeds=(talksByEvent.get(id)||[]).slice();for(const row of optionsByEvent.get(id)||[])seeds.push(...ids(row.talkId),...ids(row.talkId2));walk(talks,edges,seeds,t=>(reached[t]??=new Set()).add(id),t=>{if(reached[t]&&!reached[t].has(id)&&entered.has(t)){reached[t].add(id);return false;}return true;});}
 return listed(reached);
}
function ownership(doc,folders,previous=doc.talkOwners||{},anchor=[]){
 const {edges,talks}=links(doc,folders),reached=forward(talks,doc,edges),anchored=new Set(anchor.map(Number));
 const extra=new Set(Object.keys(display(doc,folders)).map(Number).filter(t=>!reached[t]&&!anchored.has(t)));
 const retained={};for(const [t,v]of Object.entries(previous)){const id=Number(t);if(!doc.talks[t]||extra.has(id))continue;for(const e of ids(v))if(doc.events[e])(retained[e]??=[]).push(id);}
 const result={};for(const [t,v]of Object.entries(reached))result[t]=new Set(v);
 for(const key of Object.keys(doc.events)){const id=Number(key);walk(talks,edges,[...(retained[id]||[])],t=>{if(!reached[t])(result[t]??=new Set()).add(id);});}
 for(const id of anchored){const key=String(id);if(!doc.talks[key])continue;const set=result[key]??=new Set();for(const e of ids(previous[key]||previous[id]))if(doc.events[e])set.add(e);}
 return listed(result);
}
function sync(doc,folders,currentEvent,beforeIds){
 const previous={...(doc.talkOwners||{})},anchor=[];
 if(beforeIds&&doc.events[currentEvent])for(const t of Object.keys(doc.talks))if(!beforeIds.has(t)){previous[t]=[Number(currentEvent)];anchor.push(Number(t));}
 doc.talkOwners=ownership(doc,folders,previous,anchor);
}
function interactionTalks(doc){const found=new Set(),todo=Object.values(doc.interactions||{}).map(r=>Number(r.talkId)).filter(Boolean);while(todo.length){const id=todo.pop(),r=doc.talks[id];if(!r||found.has(id))continue;found.add(id);todo.push(...ids(r.nextTalk),...ids(r.nextTalk2),...ids(r.option).flatMap(o=>[...ids(doc.options?.[o]?.talkId),...ids(doc.options?.[o]?.talkId2)]));}return found;}
function plan(doc,folders,eventIds,localIds){const owners=ownership(doc,folders),removed=new Set(eventIds.map(Number)),local=new Set((localIds||[]).map(Number)),idle=interactionTalks(doc);
 const talks=new Set(Object.keys(doc.talks).map(Number).filter(t=>(owners[t]||[]).length&&(owners[t]||[]).every(e=>removed.has(e))));
 const options=new Set([...eventIds.flatMap(e=>ids(doc.events[e]?.options)),...[...talks].flatMap(t=>ids(doc.talks[t]?.option))]);for(const [id,row]of Object.entries(doc.talks))if(!talks.has(Number(id)))for(const o of ids(row.option))options.delete(o);for(const [id,row]of Object.entries(doc.events))if(!removed.has(Number(id)))for(const o of ids(row.options))options.delete(o);return {talks,options};
}
return {ownership,display,sync,plan,interactionTalks};});
