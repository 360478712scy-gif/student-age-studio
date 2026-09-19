/* Explicit disk loading with field drafts. Missing text throws; it is never an
 * empty record. Graph fields are a separate, complete non-text projection.
 * Packed snapshots contain only field changes, not the shared source directory. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeRemoteTalks=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';
const tables=new WeakMap(),nodes=new WeakMap(),bases=new Map();let serial=0;
const own=(v,k)=>Object.prototype.hasOwnProperty.call(v,k),copy=v=>v===undefined?undefined:JSON.parse(JSON.stringify(v)),bytes=s=>new TextEncoder().encode(s).length;
const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function create(descriptor,request,revision){
 if(descriptor?.version!==1||!descriptor.generation||!Array.isArray(descriptor.ids)||!descriptor.summaries)throw Error('对话目录不完整。');
 const base={id:'remote-'+(++serial),token:descriptor.generation,revision,request,ids:new Set(descriptor.ids),summaries:descriptor.summaries,cache:new Map(),kept:new Map(),loading:new Map(),failures:new Map(),size:0,budget:4*1024*1024,pinned:new Set(),closed:false};
 for(const id of base.ids)if(!base.summaries[id]||base.summaries[id].record.id!==Number(id))throw Error('对话目录编号不匹配。');
 bases.set(base.id,base);return table(base,{});
}
function entry(base,id){return {source:base.ids.has(id)?id:null,set:{},remove:[]};}
function text(base,id){const value=base.kept.get(id)??base.cache.get(id);if(value===undefined)throw Error('对话正文尚未读取，请等待载入完成后重试。');if(base.cache.has(id)){base.cache.delete(id);base.cache.set(id,value);}return value;}
function prune(base){if(base.compatibility||base.ensureCount)return;for(const [id,value]of base.cache){if(base.size<=base.budget)break;if(base.pinned.has(id))continue;base.cache.delete(id);base.size-=bytes(value);}}
async function fetchRows(base,ids){
 ids=[...new Set(ids)].filter(id=>base.ids.has(id)&&!base.cache.has(id)&&!base.kept.has(id));
 for(let start=0;start<ids.length;start+=100){let pending=ids.slice(start,start+100);
  while(pending.length){const result=await base.request('/api/talk-segments/page',{generation:base.token,ids:pending});
   if(base.closed||result.generation!==base.token||result.revision!==base.revision)throw Error('对话读取已过期，已有草稿已保留。');
   const seen=new Set();for(const pair of result.rows||[]){const [id,value]=pair;if(!pending.includes(id)||seen.has(id)||typeof value!=='string'||JSON.parse(value)?.id!==Number(id))throw Error('对话页与目录不一致。');seen.add(id);}
   if(!seen.size||!equal(result.remaining,pending.filter(id=>!seen.has(id))))throw Error('对话页不完整。');
   for(const [id,value]of result.rows){if(base.cache.has(id))base.size-=bytes(base.cache.get(id));base.cache.set(id,value);base.size+=bytes(value);base.failures.delete(id);}
   pending=result.remaining;
  }
 }
}
function table(base,initial){
 let graphVersion=0;const changes=new Map(Object.entries(copy(initial))),handles=new Map();
 const exists=id=>changes.has(id)?changes.get(id)!==null:base.ids.has(id);
 const stateFor=id=>changes.get(id)||entry(base,id);
 const keys=()=>[...new Set([...base.ids,...changes.keys()])].filter(exists).sort((a,b)=>Number(a)-Number(b));
 function fields(id){const e=stateFor(id);return [...new Set([...(base.summaries[e.source]?.fields||[]),...Object.keys(e.set)])].filter(k=>!e.remove.includes(k));}
 function read(id,key){const e=stateFor(id);if(e.remove.includes(key))return undefined;if(own(e.set,key))return e.set[key];if(!e.source)return undefined;if(key==='content'&&base.summaries[e.source].fields.includes('content'))return JSON.parse(text(base,e.source)).content;return own(base.summaries[e.source].record,key)?base.summaries[e.source].record[key]:undefined;}
 function put(id,key,value,remove=false){
  if(key!=='content')graphVersion++;
  const e=copy(stateFor(id));
  if(key==='content'&&e.source&&!base.kept.has(e.source)&&base.cache.has(e.source)){base.kept.set(e.source,text(base,e.source));}
  e.remove=e.remove.filter(k=>k!==key);if(remove){delete e.set[key];e.remove.push(key);}else e.set[key]=copy(value);
  changes.set(id,e);
 }
 function detach(id){const handle=handles.get(id);if(handle){handle.detachChildren?.();handle.detached=copy(stateFor(id));handles.delete(id);}}
 function node(id){
  if(handles.has(id))return handles.get(id).proxy;
  const handle={detached:null,proxy:null},nested=new Map(),nestedInfo=new WeakMap();
  const current=()=>handle.detached?table(base,{[id]:handle.detached})[id]:handle.proxy;
  function detachPath(prefix){for(const [key,ref]of nested){const proxy=ref.deref();if(!proxy){nested.delete(key);continue;}const info=nestedInfo.get(proxy);if(prefix.every((v,i)=>info.path[i]===v)){info.frozen=copy(info.resolve());info.detached=true;nested.delete(key);}}}
  const child=(key,path=[],array=false)=>{
   const full=[key,...path],name=JSON.stringify(full),existing=nested.get(name)?.deref();if(existing)return existing;
   const info={path:full,detached:false,frozen:null,resolve:()=>info.detached?info.frozen:path.reduce((v,k)=>v?.[k],read(id,key))};
   const proxy=new Proxy(array?[]:{},{
    get(_,part){const value=info.resolve()?.[part];return value&&typeof value==='object'&&!info.detached?child(key,[...path,part],Array.isArray(value)):value;},
    set(_,part,value){if(info.detached){info.frozen[part]=copy(value);return true;}const whole=copy(read(id,key)),target=path.reduce((v,k)=>v[k],whole);detachPath([...full,part]);if(array&&part==='length'&&value<target.length)for(let i=value;i<target.length;i++)detachPath([...full,String(i)]);target[part]=copy(value);put(id,key,whole);return true;},
    deleteProperty(_,part){if(info.detached){delete info.frozen[part];return true;}const whole=copy(read(id,key)),target=path.reduce((v,k)=>v[k],whole);detachPath([...full,part]);delete target[part];put(id,key,whole);return true;},
    has(_,part){return part in (info.resolve()||{});},ownKeys(){return Reflect.ownKeys(info.resolve()||{});},
    getOwnPropertyDescriptor(_,part){const d=Object.getOwnPropertyDescriptor(info.resolve()||{},part);return d?{...d,configurable:array&&part==='length'?false:true}:undefined;}
   });nestedInfo.set(proxy,info);nested.set(name,new WeakRef(proxy));return proxy;
  };
  handle.detachChildren=()=>detachPath([]);
  handle.proxy=new Proxy({}, {
   get(_,key){if(handle.detached)return current()[key];const value=read(id,key);return value&&typeof value==='object'?child(key,[],Array.isArray(value)):value;},
   set(_,key,value){value=copy(value);if(handle.detached){handle.detached.set[key]=value;handle.detached.remove=handle.detached.remove.filter(k=>k!==key);}else{detachPath([key]);put(id,key,value);}return true;},
   deleteProperty(_,key){if(handle.detached){delete handle.detached.set[key];handle.detached.remove.push(key);}else{detachPath([key]);put(id,key,undefined,true);}return true;},
   has(_,key){return fields(id).includes(key);},ownKeys(){return fields(id);},
   getOwnPropertyDescriptor(_,key){return fields(id).includes(key)?{configurable:true,enumerable:true,writable:true,value:undefined}:undefined;}
  });handles.set(id,handle);nodes.set(handle.proxy,{base,id,state:()=>copy(handle.detached||stateFor(id)),read,fields});return handle.proxy;
 }
 const proxy=new Proxy({}, {
  get(_,id){return typeof id==='string'&&exists(id)?node(id):undefined;},
  set(_,id,row){if(typeof id!=='string')return false;const n=nodes.get(row);const value=n&&n.base===base?n.state():{source:null,set:copy(row),remove:[]};graphVersion++;detach(id);changes.set(id,value);return true;},
  deleteProperty(_,id){graphVersion++;detach(id);changes.set(id,null);return true;},
  has(_,id){return exists(id);},ownKeys:keys,
  getOwnPropertyDescriptor(_,id){return exists(id)?{configurable:true,enumerable:true,writable:true,value:undefined}:undefined;}
 });
 function state(){const out={};for(const [id,value]of [...changes].sort(([a],[b])=>Number(a)-Number(b))){
  if(value===null){if(base.ids.has(id))out[id]=null;continue;}
  const e=copy(value);if(e.source===id){const original=base.summaries[id];for(const key of Object.keys(e.set)){const before=key==='content'?((base.kept.has(id)||base.cache.has(id))?JSON.parse(text(base,id)).content:Symbol()):original.record[key];if(equal(e.set[key],before)&&original.fields.includes(key))delete e.set[key];}e.remove=e.remove.filter(k=>original.fields.includes(k));if(!Object.keys(e.set).length&&!e.remove.length)continue;}
  e.set=Object.fromEntries(Object.entries(e.set).sort(([a],[b])=>a.localeCompare(b)));e.remove.sort();out[id]=e;
 }return out;}
 const info={base,get graphVersion(){return graphVersion;},keys,state,stateFor,read,fields,proxy};tables.set(proxy,info);return proxy;
}
function pack(value){const t=tables.get(value),n=nodes.get(value);if(t)return {__studioRemoteTalks:t.base.id,changes:t.state()};if(n)return {__studioRemoteRow:n.base.id,id:n.id,entry:n.state()};return value;}
function revive(value){if(!value||typeof value!=='object')return value;const id=value.__studioRemoteTalks||value.__studioRemoteRow;if(!id)return value;const base=bases.get(id);if(!base)throw Error('对话底稿已过期，无法恢复草稿。');return value.__studioRemoteTalks?table(base,value.changes):table(base,{[value.id]:value.entry})[value.id];}
async function ensure(value,ids,{pin=false,keep=false}={}){const t=tables.get(value);if(!t)return;const requested=[...new Set((ids||t.keys()).map(String))].filter(id=>id in value),sources=requested.map(id=>t.stateFor(id).source).filter(Boolean);if(pin)t.base.pinned=new Set(sources);t.base.ensureCount=(t.base.ensureCount||0)+1;try{await fetchRows(t.base,sources);if(keep)for(const id of sources)t.base.kept.set(id,text(t.base,id));}catch(e){for(const id of sources)t.base.failures.set(id,e);throw e;}finally{t.base.ensureCount--;}if(pin)prune(t.base);}
function summary(row){const n=nodes.get(row);if(!n)return row?.content||'';const e=n.state();return own(e.set,'content')?e.set.content||'':e.remove.includes('content')?'':n.base.summaries[e.source]?.excerpt||'';}
function hasText(row){const n=nodes.get(row);if(!n)return !!String(row?.content||'').trim();const e=n.state();return own(e.set,'content')?!!String(e.set.content||'').trim():!e.remove.includes('content')&&!!n.base.summaries[e.source]?.hasText;}
const labelObservers=new WeakMap();
function observeLabels(container,value,selector,identify){
 labelObservers.get(container)?.disconnect();const t=tables.get(value);if(!t||typeof IntersectionObserver==='undefined')return;
 const visible=new WeakSet();const observer=new IntersectionObserver(entries=>{
  const pending=[];
  for(const item of entries){const node=item.target,id=identify(node);if(!id||!value[id])continue;
   if(!item.isIntersecting){visible.delete(node);if(node.dataset.segmentFallback!==undefined)node.textContent=node.dataset.segmentFallback;continue;}
   visible.add(node);node.dataset.segmentFallback??=node.textContent;pending.push({node,id});
  }
  if(!pending.length)return;
  // One visible page is one page read, rather than one request per event card.
  ensure(value,pending.map(item=>item.id)).then(()=>{
   setTimeout(()=>prune(t.base),0);if(labelObservers.get(container)!==observer)return;
   for(const {node,id}of pending){if(!node.isConnected||!visible.has(node)||!value[id])continue;const content=value[id]?.content;if(content)node.textContent=content;}
  }).catch(()=>{});
 },{root:null,rootMargin:'0px'});
 labelObservers.set(container,observer);container.querySelectorAll(selector).forEach(node=>observer.observe(node));
}
function projection(row){const n=nodes.get(row);if(!n)return row;return Object.fromEntries(n.fields(n.id).filter(k=>k!=='content').map(k=>[k,row[k]]));}
function sceneRecord(row){const n=nodes.get(row);if(!n)return row;const e=n.state(),loaded=!e.source||own(e.set,'content')||e.remove.includes('content')||n.base.cache.has(e.source)||n.base.kept.has(e.source);return {...projection(row),content:loaded?row.content||'':''};}
function sceneTable(value,selected){if(!tables.has(value))return value;return new Proxy(value,{get(target,id){const row=target[id];return row?{...projection(row),content:Number(id)===Number(selected)?row.content||'':''}:row;}});}
function delta(now,before){const a=tables.get(now),b=tables.get(before);if(!a||!b||a.base!==b.base)return null;const x=a.state(),y=b.state(),upsert={},deleted=[];for(const id of new Set([...Object.keys(x),...Object.keys(y)])){if(equal(x[id],y[id]))continue;if(!(id in now))deleted.push(Number(id));else{const source=a.stateFor(id).source;if(source)safeNumbers(text(a.base,source));const encoded=JSON.stringify(now[id]);safeNumbers(encoded);upsert[id]=JSON.parse(encoded);}}return {version:1,upsert,deleted};}
function changed(value,before){const a=tables.get(value),b=tables.get(before);if(!a||!b)return [];const x=a.state(),y=b.state();return [...new Set([...Object.keys(x),...Object.keys(y)])].filter(id=>!equal(x[id],y[id]));}
async function contentSearch(value,query){
 const t=tables.get(value);if(!t)return new Set(Object.keys(value||{}).filter(id=>globalThis.StudentAgeSearch.matches(query,value[id].content)));
 t.base.searches??=new Map();if(!t.base.searches.has(query)){const promise=(async()=>{const found=new Set();let offset=0;do{const result=await t.base.request('/api/talk-segments/search',{generation:t.base.token,query,offset,bodyOnly:true});if(result.generation!==t.base.token||t.base.closed)throw Error('搜索结果已过期。');for(const id of result.ids)found.add(id);offset=result.nextOffset;}while(offset!==null);return found;})();t.base.searches.set(query,promise);promise.catch(()=>t.base.searches.delete(query));while(t.base.searches.size>8)t.base.searches.delete(t.base.searches.keys().next().value);}
 const original=await t.base.searches.get(query),found=new Set(original);
 for(const [id,e]of Object.entries(t.state())){found.delete(id);if(!e)continue;if(own(e.set,'content')){if(globalThis.StudentAgeSearch.matches(query,e.set.content))found.add(id);}else if(!e.remove.includes('content')&&original.has(e.source))found.add(id);}
 return found;
}
function advance(value,revision){const t=tables.get(value);if(t)t.base.revision=revision;}
function ready(value,id){const t=tables.get(value);if(!t||id==null||!(String(id) in value))return true;const e=t.stateFor(String(id));return !e.source||own(e.set,'content')||e.remove.includes('content')||!t.base.summaries[e.source].fields.includes('content')||t.base.cache.has(e.source)||t.base.kept.has(e.source);}
function pin(value,id){const t=tables.get(value);if(!t)return;t.base.pinned=new Set(id==null?[]:[t.stateFor(String(id)).source]);prune(t.base);}
function retain(value){const active=tables.get(value)?.base;for(const [id,base]of bases)if(base!==active){base.closed=true;base.cache.clear();base.kept.clear();bases.delete(id);}}
function safeNumbers(value){for(const token of value.match(/"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g)||[]){if(token[0]==='"')continue;const v=Number(token),digits=token.split(/[eE]/)[0].replace(/[^0-9]/g,'').replace(/^0+/,'');if(!Number.isFinite(v)||(Number.isInteger(v)&&!Number.isSafeInteger(v))||digits.length>15)throw Error('这句包含超出编辑精度的数值，已保留草稿和原文件，不能直接改写。');}}
function stats(value){const t=tables.get(value);return t?{remote:true,total:t.keys().length,loaded:t.base.cache.size,cacheBytes:t.base.size,draftOriginals:t.base.kept.size,changes:Object.keys(t.state()).length,generation:t.base.token}:null;}
return {create,pack,revive,ensure,summary,hasText,observeLabels,projection,sceneTable,delta,changed,advance,stats,contentSearch,sceneRecord,ready,pin,retain,info:value=>tables.get(value),nodeInfo:value=>nodes.get(value)};
});
