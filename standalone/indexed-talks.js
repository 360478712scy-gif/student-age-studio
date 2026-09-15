/* An immutable JSON base plus copy-on-write rows. Native JSON serialization is
 * deliberately unchanged; only the story editor's history uses packed snapshots. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeIndexedTalks=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';
const tables=new WeakMap(),nodes=new WeakSet(),bases=new Map();let sequence=0;
const copy=v=>v===undefined?undefined:JSON.parse(JSON.stringify(v));
function create(rows){
 if(!Array.isArray(rows))throw Error('对话索引无法读取，请重新打开模组。');
 const seen=new Set();for(const pair of rows){if(!Array.isArray(pair)||pair.length!==2||typeof pair[0]!=='string'||Number(pair[0])>2147483647||!/^(0|[1-9][0-9]*)$/.test(pair[0])||typeof pair[1]!=='string'||seen.has(pair[0]))throw Error('对话索引编号重复或无效，请重新打开模组。');seen.add(pair[0]);}
 const base={id:'talk-base-'+(++sequence),rows:new Map(rows),canonical:new Map()};
 bases.set(base.id,base);return table(base,{});
}
function table(base,changes){
 const overlay=new Map(Object.entries(changes)),edited=new Map(),cache=new Map(),proxies=new Map(),buckets=new Map();
 // Proxy identity is retained while callers hold it; unused handles are expendable.
 // Finalization never owns row data or decides which edits are saved.
 const finalizer=typeof FinalizationRegistry==='function'?new FinalizationRegistry(({id,key,info})=>{
  if(buckets.get(id)?.get(key)!==info)return;
  buckets.get(id).delete(key);if(!buckets.get(id).size)buckets.delete(id);proxies.delete(key);
 }):null;
 function raw(id){return overlay.has(id)?overlay.get(id):base.rows.get(id);}
 function exists(id){return edited.has(id)||raw(id)!=null;}
 function read(id){
  if(edited.has(id))return edited.get(id);
  if(cache.has(id)){const row=cache.get(id);cache.delete(id);cache.set(id,row);return row;}
  const text=raw(id);if(text==null)return undefined;
  const row=JSON.parse(text);if(!row||typeof row!=='object'||Array.isArray(row)||row.id!==Number(id))throw Error('对话索引与记录编号不匹配，请重新打开模组。');cache.set(id,row);if(cache.size>64)cache.delete(cache.keys().next().value);return row;
 }
 function writable(id){if(!edited.has(id))edited.set(id,copy(read(id)));return edited.get(id);}
 const at=(row,path)=>path.reduce((v,k)=>v?.[k],row);
 function detach(id,path){
  const entries=buckets.get(id);if(!entries)return;
  let frozen,ready=false;
  for(const [key,info]of entries)if(path.every((v,i)=>info.path[i]===v)&&info.path.length>=path.length){
   if(!ready){frozen=copy(at(read(id),path));ready=true;}
   info.detached=()=>at(frozen,info.path.slice(path.length));entries.delete(key);proxies.delete(key);
  }
 }
 function node(id,path=[],array=false){
  // Nested proxy references resolve through the same row even after cache eviction.
  const key=JSON.stringify([id,path]),existing=proxies.get(key);if(existing){const live=existing.deref?existing.deref():existing;if(live)return live;}
  const info={path,detached:null},resolve=()=>info.detached?info.detached():at(read(id),path);
  const proxy=new Proxy(array?[]:{},{
   get(_,key){const value=resolve()?.[key];return value&&typeof value==='object'&&!info.detached?node(id,[...path,key],Array.isArray(value)):value;},
   set(_,key,value){
    const row=info.detached?info.detached():at(writable(id),path);if(!row)throw Error('对话记录已删除。');
    value=value&&nodes.has(value)?copy(value):value;
    if(!info.detached){
     if(row[key]&&typeof row[key]==='object')detach(id,[...path,key]);
     if(array&&key==='length'&&value<row.length)for(let i=value;i<row.length;i++)if(row[i]&&typeof row[i]==='object')detach(id,[...path,String(i)]);
    }
    row[key]=value;return true;
   },
   deleteProperty(_,key){const row=info.detached?info.detached():at(writable(id),path);if(row){if(!info.detached&&row[key]&&typeof row[key]==='object')detach(id,[...path,key]);delete row[key];}return true;},
   has(_,key){const row=resolve();return !!row&&key in row;},
   ownKeys(){return Reflect.ownKeys(resolve()||{});},
   getOwnPropertyDescriptor(_,key){const row=resolve(),d=row&&Object.getOwnPropertyDescriptor(row,key);return d?{...d,configurable:key==='length'&&array?false:true}:undefined;}
  });nodes.add(proxy);proxies.set(key,typeof WeakRef==='function'?new WeakRef(proxy):proxy);if(!buckets.has(id))buckets.set(id,new Map());buckets.get(id).set(key,info);finalizer?.register(proxy,{id,key,info});return proxy;
 }
 const proxy=new Proxy({}, {
  get(_,id){return typeof id==='string'&&exists(id)?node(id):undefined;},
  set(_,id,row){if(typeof id!=='string')return false;row=row&&nodes.has(row)?copy(row):row;detach(id,[]);edited.set(id,row);cache.delete(id);return true;},
  deleteProperty(_,id){detach(id,[]);edited.delete(id);cache.delete(id);overlay.set(id,null);return true;},
  has(_,id){return exists(id);},
  ownKeys(){return [...new Set([...base.rows.keys(),...overlay.keys(),...edited.keys()])].filter(exists).sort((a,b)=>Number(a)-Number(b));},
  getOwnPropertyDescriptor(_,id){return exists(id)?{configurable:true,enumerable:true,writable:true,value:undefined}:undefined;}
 });
 function state(){
  const out=new Map(overlay);
  for(const [id,row]of edited)out.set(id,JSON.stringify(row));
  for(const [id,value]of out){
   if(value===null&&!base.rows.has(id)){out.delete(id);continue;}
   if(value!==null&&base.rows.has(id)){
    if(!base.canonical.has(id))base.canonical.set(id,JSON.stringify(JSON.parse(base.rows.get(id))));
    if(value===base.canonical.get(id))out.delete(id);
   }
  }
  return Object.fromEntries([...out].sort(([a],[b])=>Number(a)-Number(b)));
 }
 tables.set(proxy,{base,state,keysWithField:field=>Reflect.ownKeys(proxy).filter(id=>!!read(id)?.[field]),stats:()=>({total:Reflect.ownKeys(proxy).length,decoded:cache.size,edited:edited.size,changes:Object.keys(state()).length}),raw});return proxy;
}
function pack(value){const info=value&&tables.get(value);return info?{__studioIndexedTalks:info.base.id,changes:info.state()}:value;}
function revive(_,value){
 if(value&&typeof value==='object'&&/^talk-base-[0-9]+$/.test(value.__studioIndexedTalks)&&Object.keys(value).length===2&&Object.hasOwn(value,'changes')){
  const base=bases.get(value.__studioIndexedTalks);if(!base)throw Error('对话只读底稿已过期，不能恢复到错误的模组。');
  return table(base,value.changes);
 }
 return value;
}
function stringify(value){return JSON.stringify(value,(_,v)=>pack(v));}
function parse(text){return JSON.parse(text,revive);}
function clone(value){return parse(stringify(value));}
function delta(current,before){
 const a=tables.get(current),b=tables.get(before);if(!a||!b||a.base!==b.base)return null;
 const now=a.state(),old=b.state(),upsert={},deleted=[];
 for(const id of new Set([...Object.keys(now),...Object.keys(old)])){
  const n=Object.hasOwn(now,id)?now[id]:a.base.rows.get(id),o=Object.hasOwn(old,id)?old[id]:a.base.rows.get(id);
  if(n===o)continue;if(n==null)deleted.push(Number(id));else upsert[id]=JSON.parse(n);
 }
 return {version:1,upsert,deleted};
}
function stats(value){return tables.get(value)?.stats();}
// Read-only scans need not allocate a Proxy and finalizer for every untouched row.
function keysWithField(value,field){return tables.get(value)?.keysWithField(field)??Object.keys(value||{}).filter(id=>!!value[id]?.[field]);}
function retain(value){const base=tables.get(value)?.base;for(const id of bases.keys())if(id!==base?.id)bases.delete(id);}
return {create,pack,stringify,parse,clone,delta,stats,keysWithField,retain};
});
