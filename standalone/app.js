'use strict';

(() => {
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));
const h = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const IndexedTalks=window.StudentAgeIndexedTalks;
const clone = v => IndexedTalks.clone(v);
const ids = v => Array.isArray(v) ? v.map(Number).filter(Number.isFinite) : [];
const values = map => Object.values(map || {});
const Timeline=window.StudentAgeTimeline;
const Branches=window.StudentAgeBranches,Conditions=window.StudentAgeConditions,Effects=window.StudentAgeEffects,HistoryExport=window.StudentAgeHistory;
const previewHistories=new Map(),eventGradeOverrides=new Map();
let premiseProposalPending=false;
const MAPS = ['talks','events','options','persons','faces','backgrounds','cgs','papers','actions','actionEvents','interactions','giftEvents','minigameActions'];
const FACES = ['默认','高兴','生气','伤心','害羞','喜欢','认真','疑惑','惊讶','得意','微笑','坏笑','担心','害怕','难过','咆哮','窘迫','不满','冷笑','无语','苦笑'];
const ACTIONS = {
  1001:{name:'直接登场',glyph:'↳',args:[1,3,0]},1002:{name:'渐显登场',glyph:'◌',args:[1,3,0]},
  2001:{name:'滑动退场',glyph:'⇥',args:[2,0]},2002:{name:'渐隐退场',glyph:'↗',args:[0]},3000:{name:'切换表情',glyph:'☺',args:[0]},
  3001:{name:'跳跃',glyph:'↟',args:[1,0,1]},3002:{name:'摇晃',glyph:'〰',args:[0.4,0]},
  3004:{name:'水平移动',glyph:'↔',args:[0,0,0]},3005:{name:'转身',glyph:'⇄',args:[0]},
  3006:{name:'更换服装',glyph:'◇',args:[0]},3008:{name:'垂直移动',glyph:'↕',args:[0,0,0]}
};
const PLACE = {1:'左侧',3:'中间',2:'右侧'};
const fragment = decodeURIComponent(location.hash.slice(1));
const injected = window.STUDIO_TOKEN;
const token = injected && injected !== '__STUDIO_TOKEN__' ? injected : (fragment.startsWith('token=') ? fragment.slice(6) : fragment);
const S = {projects:[],project:null,doc:null,revision:null,localIds:{},catalogAvailable:false,selected:null,event:'all',
  order:[],premises:{},pinned:{talks:new Set(),options:new Set(),events:new Set()},catalogAll:{},effectTemplates:[],branchFolders:{},folderOpen:{},activeFolder:null,conditionTemplates:[],conditionRefs:{},conditionLocalIds:{},undo:[],redo:[],coalesce:null,saved:'',dirty:false,saving:false,deleted:[],replacements:{},search:'',listStart:0,listAnchor:null,
  previewRole:null,face:0,cloth:0,grade:0,previewCG:false,connected:false,audios:[],audioLoading:false,bgmDraft:null,catalogIds:{},idMappings:{},autoRenumber:true};
try { localStorage.removeItem('studentAgeStudio.settings'); } catch (_) {}

async function api(path, body) {
  const response = await fetch(path, {method:body === undefined ? 'GET' : 'POST',headers:{'X-Studio-Token':token,...(body === undefined ? {} : {'Content-Type':'application/json'})},body:body === undefined ? undefined : JSON.stringify(body)});
  let data; try {data = await response.json();} catch (_) {throw new Error('本地服务返回了无法读取的结果。');}
if(data.code==='save_warnings'&&window.STUDIO_SAVE_REVIEW)return STUDIO_SAVE_REVIEW.retry(data,path,body,api);  if (!response.ok || data.error) {const error=new Error(typeof data.error === 'string' ? data.error : data.message || '操作没有完成，请重试。');error.code=data.code;error.status=response.status;throw error;}
  return data;
}
function assetName(row,kind){const map={background:'backgrounds',cg:'cgs',portrait:'persons'}[kind];return window.StudentAgeAssetNames.name(row,kind,kind==='audio'?S.audios:S.doc?.[map]);}
function assetUrl(path, projectId = S.project && S.project.id) {
  return '/api/assets?projectId='+encodeURIComponent(projectId || '')+'&path='+encodeURIComponent(path || '')+'&token='+encodeURIComponent(token);
}
function toast(message, type = '') {
  const node = document.createElement('div'); node.className='toast '+type; node.textContent=message;
  const region=$('#toast-region');region.replaceChildren(node);
  // A modal <dialog> sits in the top layer above the page; a popover shown after it lands above the dialog.
  if(region.showPopover){try{if(region.matches(':popover-open'))region.hidePopover();region.showPopover();}catch{}}
  setTimeout(() => {node.remove();if(!region.childElementCount&&region.matches?.(':popover-open'))try{region.hidePopover();}catch{}}, type === 'error' ? 6500 : 2600);
}
function fail(error) {console.error(error); toast(error.message || String(error),'error');}
window.STUDIO_REPORT_ERROR=fail;
window.STUDIO_NOTIFY=(message,error=false)=>toast(message,error?'error':'');
let projectLoadSequence=0;
function projectBusy(value){S.projectOpening=value;document.querySelector('.workspace').inert=value;document.querySelector('.header-actions').inert=value;const main=$('#wk-main');if(main)main.inert=value;}
function projectFeedback(message,error=false,copyId=null){let node=$('#project-load-status');if(!node){node=document.createElement('div');node.id='project-load-status';node.setAttribute('role','status');node.setAttribute('aria-live','polite');document.body.append(node);}node.dataset.state=error?'error':'loading';node.innerHTML=`<span>${h(message)}</span>${error&&copyId?'<button data-load-copy class="primary">创建副本后编辑</button>':''}${error?'<button data-load-close aria-label="关闭载入提示">关闭</button>':''}`;node.querySelector('[data-load-close]')?.addEventListener('click',()=>node.remove());node.querySelector('[data-load-copy]')?.addEventListener('click',()=>newProject(true,copyId));}
window.STUDIO_PROJECT_LOAD_ERROR=error=>projectFeedback(error.message||String(error),true,error.projectId);
function talk() {return S.doc && S.doc.talks[S.selected] || null;}
function personName(id) {const p=S.doc && S.doc.persons[id];return p && p.name || (Number(id) === 0 ? '主角' : '人物 '+id);}
function speaker(t) {const speaking=ids(t.roleIds).filter(id=>id>=0);return t.roleName || (speaking.length ? speaking.map(personName).join('、') : '旁白');}
function talkLabel(id) {const t=S.doc && S.doc.talks[id];return t ? speaker(t)+' · '+(t.content || '空白对话').replace(/\n/g,' ').slice(0,35) : '外部对话 · '+id;}
function faceName(face=S.face) {const cfg=S.doc && S.doc.faces[Number(S.previewRole)*1000+S.cloth*100+face];return cfg && cfg.name || FACES[face] || '自定义表情 '+face;}
window.addEventListener('studio-premise-created',e=>{const v=e.detail;if(S.project?.id!==v.projectId||S.revision!==v.previousRevision)return;S.revision=v.revision;S.premises[v.premise.id]=clone(v.premise);for(const entry of [...S.undo,...S.redo]){entry.premises??={};entry.premises[v.premise.id]=clone(v.premise);}if(S.saved){const saved=IndexedTalks.parse(S.saved);saved[4]??={};saved[4][v.premise.id]=clone(v.premise);S.saved=IndexedTalks.stringify(saved);}updateDirty();});
function currentSignature() {return IndexedTalks.stringify([S.doc,S.order,S.deleted,S.replacements,S.premises,Object.fromEntries(Object.entries(S.branchFolders).map(([key,{collapsed,...folder}])=>[key,folder])),pinnedSnapshot()]);}
function pinnedSnapshot(){return {talks:[...S.pinned.talks].sort((a,b)=>a-b),options:[...S.pinned.options].sort((a,b)=>a-b),events:[...S.pinned.events].sort((a,b)=>a-b)};}
function snapshot(label) {return {label,doc:clone(S.doc),order:S.order.slice(),premises:clone(S.premises),branchFolders:clone(S.branchFolders),activeFolder:S.activeFolder,selected:S.selected,event:S.event,deleted:S.deleted.slice(),replacements:clone(S.replacements),pinnedIds:pinnedSnapshot(),idMappings:clone(S.idMappings||{}),localIds:clone(S.localIds)};}
function history(label, key) {
  invalidateStageMemo();
  stopLinePlayback(false);
  if(scenePlayer?.playing)scenePlayer.pause();if(scenePlayer)scenePlayer.historyStarted=false;
  stageAudio?.stop();
  if (key && key === S.coalesce) return;
  S.undo.push(snapshot(label)); if(S.undo.length>60) S.undo.shift();S.redo=[];S.coalesce=key || null;
}
function editable() {
  if(S.projectOpening){toast('正在打开模组，请稍候。','note');return false;}
  if (!S.project) {toast('先打开或新建一个模组。','note');return false;}
  if (!availableProject(S.project.id)||!isLocalProject(S.project)) {toast('订阅模组可以查看和预演；复制为本地副本后即可编辑。','note');return false;}
  return true;
}
function premisePair(row,writer=false){return Array.isArray(row)&&row.length>=5&&(Number(row[0])===50&&[2,20].includes(Number(row[1]))||!writer&&Number(row[0])===111)?Number(row[2])+':'+Number(row[3]):null;}
function premiseWriters(value,result=new Set()){const pair=premisePair(value,true);if(pair)result.add(pair);else if(value&&typeof value==='object')for(const child of Object.values(value))premiseWriters(child,result);return result;}
// A premise created on a dialogue line is held by that line itself (the game records reached talks natively);
// legacy premises are held by their [50,2,event,slot,1] effect rows.
function premiseHolders(value){const result=premiseWriters(value);const talks=value&&typeof value==='object'?(value.talks?Object.keys(value.talks):value.content!==undefined&&value.id!==undefined?[value.id]:[]):[];if(talks.length){const set=new Set(talks.map(Number));for(const p of values(S.premises))if(Number.isInteger(p?.talkId)&&set.has(Number(p.talkId)))result.add(p.eventId+':'+p.slot);}return result;}
function stripPremise(value,pairs){if(Array.isArray(value)){for(let i=value.length-1;i>=0;i--)if(pairs.has(premisePair(value[i])))value.splice(i,1);else stripPremise(value[i],pairs);}else if(value&&typeof value==='object')for(const child of Object.values(value))stripPremise(child,pairs);return value;}
window.STUDIO_STRIP_PREMISES=stripPremise;
function removePremises(keys){const pairs=new Set();for(const key of keys){const p=S.premises[key];if(p){pairs.add(p.eventId+':'+p.slot);delete S.premises[key];}}stripPremise(S.doc,pairs);S.conditionTemplates=S.conditionTemplates.filter(t=>!pairs.has(premisePair(t.template)));return pairs;}
function cleanLostPremises(before){const after=premiseHolders(S.doc);removePremises(Object.keys(S.premises).filter(key=>{const p=S.premises[key],pair=p.eventId+':'+p.slot;return (!Number.isInteger(p.talkId)&&!S.doc.events[p.eventId])||before.has(pair)&&!after.has(pair);}));}
async function deletePremise(rowOrId){
 if(!editable())return false;const p=Array.isArray(rowOrId)?values(S.premises).find(p=>premisePair(rowOrId)===p.eventId+':'+p.slot):S.premises[rowOrId];if(!p)throw Error('只能删除当前模组创建的前提。');
 const response=await api('/api/premises/references',{projectId:S.project.id,eventId:p.eventId,slot:p.slot,talkId:p.talkId,...Object.fromEntries(MAPS.map(k=>[k,S.doc[k]]))});
 const accepted=await new Promise(resolve=>{const d=document.createElement('dialog');d.className='character-picker';d.innerHTML='<h2>删除前提？</h2><p>'+h(response.references.length?response.references.join('，')+' 引用了 ['+p.name+'] 这个前提，确定要删除吗？':'确定要删除 ['+p.name+'] 这个前提吗？')+'</p><p>对应的条件与达成效果会一起移除。</p><footer><button data-cancel>取消</button><button class="danger-button" data-confirm>删除前提</button></footer>';document.body.append(d);const end=v=>{d.close();d.remove();resolve(v);};d.querySelector('[data-cancel]').onclick=()=>end(false);d.querySelector('[data-confirm]').onclick=()=>end(true);d.oncancel=e=>{e.preventDefault();end(false);};d.showModal();});if(!accepted)return false;
 // Flush other editors first, then atomically save definition and all references.
 if(!await window.STUDIO_NAV.saveAll())return false;
 const key=Object.keys(S.premises).find(k=>S.premises[k].eventId===p.eventId&&S.premises[k].slot===p.slot);if(key===undefined)return true;
 mutate('删除前提',()=>removePremises([key]));if(!await save())return false;
 window.dispatchEvent(new CustomEvent('studio-premises-removed',{detail:{pairs:[p.eventId+':'+p.slot],revision:S.revision,projectId:S.project.id}}));return true;
}
window.STUDIO_DELETE_PREMISE=deletePremise;
function eventRoots(e){return [...ids(e.talkId),...ids(e.options).flatMap(id=>[...ids(S.doc.options[id]?.talkId),...ids(S.doc.options[id]?.talkId2)])];}
function mutate(label, fn, key=null, redraw=true) {if(!editable())return false;history(label,key);const writers=premiseHolders(S.doc);const beforeIds=new Set(Object.keys(S.doc.talks));fn();StudentAgeEventOwnership.sync(S.doc,S.branchFolders,S.event,beforeIds);cleanLostPremises(writers);updateDirty();if(redraw)render();scheduleRenumber();return true;}
let textDirtyTimer=null;
function updateTextDirty(){
 // Input changes the live row immediately. Full-document comparison waits for a pause.
 S.dirty=true;renderChrome();clearTimeout(textDirtyTimer);
 textDirtyTimer=setTimeout(()=>{textDirtyTimer=null;updateDirty();},600);
}
function updateDirty() {clearTimeout(textDirtyTimer);textDirtyTimer=null;invalidateStageMemo();S.dirty=S.doc !== null && (currentSignature() !== S.saved||Object.values(S.idMappings||{}).some(m=>Object.keys(m).length));renderChrome();}
function restore(entry) {S.doc=entry.doc;S.order=entry.order;S.premises=entry.premises||{};S.branchFolders=entry.branchFolders||{};S.activeFolder=entry.activeFolder||null;S.selected=entry.selected;S.event=entry.event;S.deleted=entry.deleted;S.replacements=entry.replacements;S.pinned=Object.fromEntries(['talks','options','events'].map(k=>[k,new Set(entry.pinnedIds?.[k]||[])]));S.idMappings=clone(entry.idMappings||{});if(entry.localIds)S.localIds=clone(entry.localIds);clearTimeout(renumberTimer);S.coalesce=null;updateDirty();render();}
function undo() {if(!S.undo.length)return;const e=S.undo.pop();S.redo.push(snapshot(e.label));restore(e);toast('已撤销：'+e.label);}
function redo() {if(!S.redo.length)return;const e=S.redo.pop();S.undo.push(snapshot(e.label));restore(e);toast('已重做：'+e.label);}
function links(t) {
  const out=[...ids(t.nextTalk),...ids(t.nextTalk2)];
  for(const oid of ids(t.option)){const o=S.doc.options[oid];if(o)out.push(...ids(o.talkId),...ids(o.talkId2));}
  return out;
}
function graphOrder(starts) {
  const seen=new Set(),out=[],stack=starts.slice().reverse();
  while(stack.length){const id=Number(stack.pop());if(seen.has(id)||!S.doc.talks[id])continue;seen.add(id);out.push(id);stack.push(...links(S.doc.talks[id]).reverse());}
  return out;
}
function initialOrder() {
  const roots=values(S.doc.events).flatMap(eventRoots);
  const ordered=graphOrder(roots),set=new Set(ordered);
  for(const id of Object.keys(S.doc.talks).map(Number).sort((a,b)=>a-b))if(!set.has(id))ordered.push(id);
  return ordered;
}
function visibleIds() {
  const hidden=Timeline.internals(S.branchFolders);let list=S.order.filter(id=>S.doc && S.doc.talks[id]&&!hidden.has(id));
  if(S.event!=='all'){const event=S.doc.events[S.event];const allowed=new Set(Object.entries(S.doc.talkOwners||{}).filter(([,owners])=>owners.includes(Number(S.event))).map(([id])=>Number(id)));list=list.filter(id=>allowed.has(id));}
  list=list.filter(id=>(S.doc.talkOwners?.[id]||[]).some(e=>S.doc.events[e]));
  if(S.search){const q=S.search.toLocaleLowerCase();list=list.filter(id=>{const t=S.doc.talks[id];return StudentAgeSearch.matches(q,id,speaker(t),t.content);});}
  return list;
}
function selectTalk(id) {
  stopLinePlayback(false);
  stageAudio?.stop();
  if(scenePlayer)scenePlayer.historyStarted=false;S.selected=Number(id);S.activeFolder=Branches.ownedBy(S.branchFolders,S.selected);if(S.activeFolder)S.folderOpen[S.activeFolder]=true;S.coalesce=null;const t=talk();if(t){const role=ids(t.roleIds).find(x=>x>=0);if(role!==undefined)S.previewRole=role;else if(Array.isArray(t.roles)&&t.roles.length)S.previewRole=Number(t.roles[0][0]);syncFaceFromTalk();}render();$('#editor-scroll').scrollTo({top:0});
}
function syncFaceFromTalk() {const actor=currentStage().roles[S.previewRole];S.face=actor?.face??0;S.cloth=actor?.cloth??0;S.previewCG=false;}

function nextId(map, base) {const table=map===S.doc.events?'EvtCfg':map===S.doc.options?'OptionCfg':'TalkCfg';return STUDIO_IDS.allocate(table,{...map,...Object.fromEntries(S.deleted.map(id=>[id,true]))},table==='EvtCfg'?undefined:Math.floor(base/(table==='TalkCfg'?1000:100)));}
function eventForTalk() {if(S.event!=='all')return Number(S.event);const e=values(S.doc.events).find(x=>graphOrder(ids(x.talkId)).includes(S.selected));return e?e.id:900000;}
function newTalkId() {let base=eventForTalk()*1000+1;if(base>2147483000)base=900000001;return nextId(S.doc.talks,base);}
function normalizeTalk(t) {for(const k of ['nextTalk','nextTalk2','roleIds','roles','option','check','effect','effect2','highlights','replace','screenEffect'])if(!Array.isArray(t[k]))t[k]=[];return t;}
function continuationTalk(id,previous,stage,blank=false) {
  // Actors keep their preceding state in the game; copying actions would move them twice.
  return normalizeTalk({id,content:'',roleIds:blank?[]:ids(previous?.roleIds),roleName:blank?null:previous?.roleName||null,
    bg:blank?0:Number(stage?.background)||0,highlights:[],roles:[],screenEffect:[]});
}
function stageAt(id) {
  return Number(id)===S.selected?currentStage():StudentAgeScene.reconstruct({...S.doc,branchFolders:S.branchFolders},Number(id),sceneContext());
}
function closeCGBeforeFollowing(row,folder=null) {
  const transitions=[],replacements=new Map();
  const internal=Timeline.internals(S.branchFolders);
  for(const id of ids(row.nextTalk)){
    const following=S.doc.talks[id];if(!following||replacements.has(id)||internal.has(Number(id)))continue;
    const code=Number(following.screenEffect?.[0])||0;
    if([4015,4016,4017,4018].includes(code))continue;
    const shared=values(S.doc.talks).some(t=>Number(t.id)!==Number(row.id)&&[...ids(t.nextTalk),...ids(t.nextTalk2)].includes(id))||
      values(S.doc.options).some(o=>[...ids(o.talkId),...ids(o.talkId2)].includes(id))||values(S.doc.events).some(e=>ids(e.talkId).includes(id));
    if(!code&&!shared){following.screenEffect=[4017];continue;}
    // A shared destination belongs to its other routes too. Close this CG on
    // its own edge, retaining any screen effect already set on the destination.
    const transition=normalizeTalk({id:newTalkId(),content:'',roleIds:[],roleName:'',bg:0,screenEffect:[4017],nextTalk:[id]});
    S.doc.talks[transition.id]=transition;transitions.push(transition.id);replacements.set(id,transition.id);
  }
  if(!transitions.length)return;
  row.nextTalk=ids(row.nextTalk).map(id=>replacements.get(id)||id);
  S.order.splice(S.order.indexOf(Number(row.id))+1,0,...transitions);
  if(folder)folder.talkIds.splice(folder.talkIds.indexOf(Number(row.id))+1,0,...transitions);
}
function addTalk(duplicate=false,options={}) {
  if(S.event==='all'||!S.doc?.events[S.event]){createEvent();return;}
  if(!editable())return;if(S.activeFolder)return addFolderTalk(S.activeFolder,duplicate,S.selected,options);const current=talk();if(!duplicate&&ids(current?.option).length){if(current.miniGame?.length){toast('这句带小游戏，请在对应对话夹里添加后续内容。','note');return;}return addAfterBranches(current,options);}
  const previousStage=current?currentStage():null;
  mutate(options.cgId?'添加 CG':options.blank?'添加空白对话':duplicate?'复制对话':'添加对话',()=>{
    const roots=!current?ids(S.doc.events[S.event]?.talkId).filter(id=>id>0):[],entry=roots[0];
    const adopted=entry!==undefined&&!S.deleted.includes(entry)&&!roots.some(id=>S.doc.talks[id])&&STUDIO_IDS.claim('TalkCfg',entry,S.doc.talks);
    const id=adopted?entry:newTalkId(),item=duplicate&&current?normalizeTalk(clone(current)):continuationTalk(id,current,previousStage,options.blank);item.id=id;if(options.cgId){item.screenEffect=[4015,Number(options.cgId)];item.roleIds=[];item.roleName='';item.highlights=[];}
    if(roots.length)S.pinned.talks.add(id);
    if(duplicate && current){item.check=[];item.nextTalk2=[];item.option=[];for(const oid of ids(current.option)){const old=S.doc.options[oid];if(!old)continue;const newId=nextId(S.doc.options,eventForTalk()*100+1);S.doc.options[newId]={...clone(old),id:newId};item.option.push(newId);}}
    item.nextTalk=current?Timeline.next(S.doc,S.branchFolders,current.id):[];
    if(current)Timeline.setNext(S.doc,S.branchFolders,current.id,[id]);
    else if(S.event!=='all'&&S.doc.events[S.event]){const e=S.doc.events[S.event];e.talkId=adopted?[...new Set(roots)]:[id,...ids(e.talkId).filter(old=>old>0&&old!==id)];}
    S.doc.talks[id]=item;if(phoneEvent()&&ids(phoneEvent().talkId)[0]===id)configurePhone(phoneEvent());const index=current?blockEnd(current.id):S.order.indexOf(S.selected);S.order.splice(index<0?S.order.length:index+1,0,id);if(options.cgId)closeCGBeforeFollowing(item);S.selected=id;S.search='';$('#talk-search').value='';
  });
  setTimeout(()=>$('#scene-dialogue-content')?.focus(),0);
}
// Every line reached through a talk's option folders and condition branches (recursively), in reading order.
function branchBlock(parent,seen=new Set()){
  const out=[];const visit=id=>{if(seen.has(id)||!S.doc.talks[id])return;seen.add(id);out.push(id);
    const conditions=Timeline.entries(S.branchFolders,id);
    for(const [,f]of conditions){for(const g of [f.routerId])if(S.doc.talks[g]&&!seen.has(g)){seen.add(g);out.push(g);}for(const t of ids(f.talkIds))visit(t);if(S.doc.talks[f.exitId]&&!seen.has(f.exitId)){seen.add(f.exitId);out.push(f.exitId);}}
    if(conditions.length){const end=conditions[0][1].endId;if(S.doc.talks[end]&&!seen.has(end)){seen.add(end);out.push(end);}}
    for(const oid of ids(S.doc.talks[id].option)){const f=S.branchFolders[id+':'+oid];for(const t of ids(f?.talkIds))visit(t);}};
  seen.add(Number(parent));
  const conditions=Timeline.entries(S.branchFolders,parent);
  for(const [,f]of conditions){if(S.doc.talks[f.routerId]&&!seen.has(f.routerId)){seen.add(f.routerId);out.push(f.routerId);}for(const t of ids(f.talkIds))visit(t);if(S.doc.talks[f.exitId]&&!seen.has(f.exitId)){seen.add(f.exitId);out.push(f.exitId);}}
  if(conditions.length){const end=conditions[0][1].endId;if(S.doc.talks[end]&&!seen.has(end)){seen.add(end);out.push(end);}}
  for(const oid of ids(S.doc.talks[parent]?.option)){const f=S.branchFolders[parent+':'+oid];for(const t of ids(f?.talkIds))visit(t);}
  return out;
}
function blockEnd(parent){let index=S.order.indexOf(Number(parent));for(const id of branchBlock(parent))index=Math.max(index,S.order.indexOf(id));return index;}
// A new line added right after a choice becomes the place every option folder continues to.
function addAfterBranches(current,options={}){
  const previousStage=currentStage();
  let skipped=0;
  mutate(options.cgId?'在分支后添加 CG':options.blank?'在分支后添加空白对话':'在分支后添加对话',()=>{
    const id=newTalkId(),item=continuationTalk(id,current,previousStage,options.blank);item.id=id;
    if(options.cgId){item.screenEffect=[4015,Number(options.cgId)];item.roleIds=[];item.roleName='';item.highlights=[];}
    const folders=[];
    for(const oid of ids(current.option)){
      const key=current.id+':'+oid;let folder=S.branchFolders[key];
      try{if(!folder)folder=takeFolder(key).folder;}catch(error){skipped++;continue;}
      if(folder)folders.push([key,folder]);
    }
    const targets=new Map();
    for(const [,f]of folders)if(f.continuation?.kind==='talk'){const t=Number(f.continuation.talkId);targets.set(t,(targets.get(t)||0)+1);}
    const common=[...targets.entries()].sort((a,b)=>b[1]-a[1])[0]?.[0];
    item.nextTalk=common?[common]:[];
    S.doc.talks[id]=item;
    for(const [key,f]of folders){
      const kind=f.continuation?.kind||'end';if(kind!=='end'&&kind!=='talk')continue;
      try{Branches.setContinuation(S.doc,f,{kind:'talk',talkId:id});}catch(error){skipped++;}
    }
    const index=blockEnd(current.id);S.order.splice(index<0?S.order.length:index+1,0,id);
    if(options.cgId)closeCGBeforeFollowing(item);
    S.activeFolder=null;S.selected=id;S.search='';$('#talk-search').value='';
  });
  if(skipped)toast('有 '+skipped+' 个选项的出口无法自动改到新对话，请在对话夹的“对话夹结束后”里手动选择。','note');
  else toast('已在分支之后添加对话，各选项对话夹结束后都会接到这句。');
  setTimeout(()=>$('#scene-dialogue-content')?.focus(),0);
}
// ---- Automatic dialogue numbering: IDs of a mod event follow reading order
// (a choice's options first, then each option's lines) after every edit. ----
let renumberTimer=null,renumberPending=false,renumberWarned=new Set();
function scheduleRenumber(){if(S.autoRenumber===false||!S.doc||S.event==='all'||S.deferredProject)return;clearTimeout(renumberTimer);renumberTimer=setTimeout(()=>{renumberEvent(Number(S.event)).catch(error=>{console.error(error);toast('对话编号未能自动整理：'+(error.message||error),'error');});},250);}
function composeMappings(base,next){
  const out={};for(const table of new Set([...Object.keys(base||{}),...Object.keys(next||{})])){
    const a=base?.[table]||{},b=next?.[table]||{},m={},covered=new Set();
    for(const [k,v]of Object.entries(a)){const to=b[String(v)];m[k]=to===undefined?v:to;covered.add(String(v));}
    for(const [k,v]of Object.entries(b))if(!covered.has(k)&&m[k]===undefined)m[k]=v;
    for(const k of Object.keys(m))if(String(m[k])===k)delete m[k];
    if(Object.keys(m).length)out[table]=m;
  }return out;
}
function eventTraversal(eventId){
  const owners=S.doc.talkOwners||{},owned=id=>{const o=ids(owners[id]);return o.length===1&&o[0]===eventId&&!S.catalogTalkIds?.has(Number(id));};
  const hidden=Timeline.internals(S.branchFolders),seen=new Set(),out=[];
  for(const id of S.order){if(seen.has(id)||Timeline.owner(S.branchFolders,id)||hidden.has(id)||!S.doc.talks[id])continue;seen.add(id);out.push(id);for(const t of branchBlock(id,seen))out.push(t);}
  for(const id of S.order)if(!seen.has(id)&&S.doc.talks[id]){seen.add(id);out.push(id);}
  return out.filter(owned);
}
function localStoryIds(key){const local=new Set((S.localIds?.[key]||[]).map(Number));return new Set(Object.keys(S.doc?.[key]||{}).filter(id=>local.has(Number(id))||!S.catalogIds?.[key]?.has(id)).map(Number));}
function renumberPlan(eventId){
  if(!S.doc?.events?.[eventId]||S.catalogIds?.events?.has(String(eventId))||S.project?.originalMode||eventId*1000>2147483647)return null;
  const talksInOrder=eventTraversal(eventId);if(!talksInOrder.length)return null;
  const localTalks=localStoryIds('talks'),localOptions=localStoryIds('options');
  // Hand-set IDs are never touched; sequential numbers skip anything a pinned row or another local row holds.
  // An original (catalogue) row with the same number is allowed: the mod row overrides it and the card says so.
  const missingEntries=values(S.doc.events).flatMap(e=>ids(e.talkId)).filter(id=>id>0&&!S.doc.talks[id]);
  const talkMap={},domain=new Set(talksInOrder),takenTalks=new Set([...S.pinned.talks,...missingEntries,...Object.keys(S.doc.talks).map(Number).filter(id=>localTalks.has(id)&&!domain.has(id))]);
  // A pinned line still occupies its position in the sequence, so the lines around it keep their numbers.
  let n=0;for(const id of talksInOrder){if(S.pinned.talks.has(id)){n++;continue;}let fresh;do{n++;fresh=eventId*1000+n;}while(takenTalks.has(fresh)&&fresh!==id);
    if(n>999||fresh>2147483647){if(!renumberWarned.has(eventId)){renumberWarned.add(eventId);toast('本事件对话超过 999 句，无法继续自动编号。','note');}return null;}
    if(fresh!==id)talkMap[id]=fresh;}
  const optionMap={},optionOrder=[];const seenOptions=new Set();
  for(const id of talksInOrder)for(const oid of ids(S.doc.talks[id]?.option)){if(seenOptions.has(oid))continue;seenOptions.add(oid);const row=S.doc.options[oid];if(!row||!localOptions.has(oid)||S.pinned.options.has(oid))continue;
    const parents=values(S.doc.talks).filter(t=>ids(t.option).includes(oid)).map(t=>Number(t.id));if(parents.some(pid=>!domain.has(pid)))continue;optionOrder.push(oid);}
  const optionDomain=new Set(optionOrder),takenOptions=new Set([...S.pinned.options,...Object.keys(S.doc.options).map(Number).filter(id=>localOptions.has(id)&&!optionDomain.has(id))]);
  let j=0;for(const oid of optionOrder){let fresh;do{j++;fresh=eventId*100+j;}while(takenOptions.has(fresh)&&fresh!==oid);if(j>99)break;if(fresh!==oid)optionMap[oid]=fresh;}
  if(!Object.keys(talkMap).length&&!Object.keys(optionMap).length)return null;
  return {TalkCfg:talkMap,OptionCfg:optionMap};
}
async function renameEvent(oldId,newId){
  oldId=Number(oldId);newId=Number(newId);
  if(!editable()||!S.doc?.events?.[oldId]||oldId===newId)return false;
  if(!Number.isInteger(newId)||newId<=0||newId>2147483647)throw Error('事件编号应为 1 到 2147483647 之间的整数。');
  const localEvents=localStoryIds('events'),otherLocal=S.doc.events[newId]&&localEvents.has(newId)?newId:null;
  const plan={EvtCfg:otherLocal?{[oldId]:newId,[newId]:oldId}:{[oldId]:newId},TalkCfg:{},OptionCfg:{}};
  // Each renamed event's automatically numbered lines and options move into its new range together, so a
  // swap between two local events is one simultaneous permutation and nothing collides.
  const ranges=[[oldId,newId],...(otherLocal?[[newId,oldId]]:[])];
  const localTalks=localStoryIds('talks'),localOptions=localStoryIds('options');
  const groups=ranges.map(([from,to])=>{
    const traversal=eventTraversal(from),domain=new Set(traversal);
    const talks=traversal.filter(id=>!S.pinned.talks.has(id));
    const options=[...new Set(traversal.flatMap(id=>ids(S.doc.talks[id]?.option)))].filter(oid=>
      localOptions.has(oid)&&!S.pinned.options.has(oid)&&values(S.doc.talks).every(t=>!ids(t.option).includes(oid)||domain.has(Number(t.id))));
    return {to,talks,options};
  });
  const movingTalks=new Set(groups.flatMap(g=>g.talks)),movingOptions=new Set(groups.flatMap(g=>g.options));
  const sequence=(rows,to,factor,limit,taken,moving,map)=>{
    if(to*factor>=2147483647)return;let index=0;
    for(const id of rows){let fresh;do{fresh=to*factor+(++index);}while(index<=limit&&taken.has(fresh)&&!moving.has(fresh));
      if(index>limit||fresh>2147483647)break;if(fresh!==id)map[id]=fresh;
    }
  };
  for(const group of groups){
    sequence(group.talks,group.to,1000,999,localTalks,movingTalks,plan.TalkCfg);
    sequence(group.options,group.to,100,99,localOptions,movingOptions,plan.OptionCfg);
  }
  const ok=await runRenumber(plan,'修改事件编号');
  if(ok){if(otherLocal)toast('事件编号已与原 ['+newId+'] 事件交换，对话与选项编号已同步。');else toast('事件编号已改为 '+newId+'，对话与选项编号已同步。'+(S.catalogAll.events?.has(String(newId))?' 该编号与原版事件相同，游戏中会覆盖原版。':''));}
  return ok;
}
window.STUDIO_RENAME_EVENT=renameEvent;
async function renumberEvent(eventId){
  if(renumberPending||S.saving||document.querySelector('#record-id-dialog[open]')||!editable())return false;
  const plan=renumberPlan(eventId);if(!plan)return false;
  return runRenumber(plan);
}
async function runRenumber(plan,label=null){
  if(!editable())return false;
  const oldIds=[...Object.keys(plan.TalkCfg||{}),...Object.keys(plan.OptionCfg||{}),...Object.keys(plan.EvtCfg||{})];if(!oldIds.length)return false;
  const pattern=new RegExp('(?<![0-9])('+oldIds.join('|')+')(?![0-9])');
  const tables={};
  for(const [table,key]of Object.entries(jsonStoryKeys)){
    const base=S.catalogIds?.[key],local=localStoryIds(key),domain=table==='TalkCfg'?plan.TalkCfg:table==='OptionCfg'?plan.OptionCfg:table==='EvtCfg'?plan.EvtCfg:null,rows={};
    for(const [id,row]of Object.entries(S.doc[key]||{})){if(base?.has(String(id))&&!local.has(Number(id)))continue;if((domain&&domain[id]!==undefined)||pattern.test(JSON.stringify(row)))rows[id]=row;}
    if(Object.keys(rows).length)tables[table]=rows;
  }
  const stamp=currentSignature();if(renumberPending)return false;renumberPending=true;
  let result;try{result=await api('/api/story/renumber',{projectId:S.project.id,mappings:plan,tables});}finally{renumberPending=false;}
  if(!S.doc||currentSignature()!==stamp){scheduleRenumber();return false;}
  if(label)history(label);
  applyRenumber(result);
  return true;
}
function applyRenumber(result){
  const tm=result.mappings.TalkCfg||{},om=result.mappings.OptionCfg||{},em=result.mappings.EvtCfg||{};
  const mt=id=>{const v=tm[String(id)];return v===undefined?Number(id):Number(v);},mo=id=>{const v=om[String(id)];return v===undefined?Number(id):Number(v);},me=id=>{const v=em[String(id)];return v===undefined?Number(id):Number(v);},mtAll=arr=>ids(arr).map(mt);
  const mapKey=key=>{if(!key)return key;const parts=String(key).split(':');parts[0]=String(mt(parts[0]));if(parts.length===2&&/^\d+$/.test(parts[1]))parts[1]=String(mo(parts[1]));return parts.join(':');};
  const previousLocal=Object.fromEntries(['talks','options','events'].map(k=>[k,[...localStoryIds(k)]]));
  for(const [table,rows]of Object.entries(result.tables||{})){const key=jsonStoryKeys[table];if(!key||!S.doc[key])continue;const map=table==='TalkCfg'?tm:table==='OptionCfg'?om:table==='EvtCfg'?em:null;if(map)for(const old of Object.keys(map))delete S.doc[key][old];Object.assign(S.doc[key],rows);}
  if(Object.keys(tm).length)for(const p of Object.values(S.premises||{}))if(Number.isInteger(p.talkId))p.talkId=mt(p.talkId);
  if(Object.keys(em).length){if(S.event!=='all')S.event=me(S.event);if(S.doc.eventGrades)S.doc.eventGrades=Object.fromEntries(Object.entries(S.doc.eventGrades).map(([k,v])=>[String(me(k)),v]));for(const p of Object.values(S.premises||{})){if(p.eventId!==undefined)p.eventId=me(p.eventId);if(p.event!==undefined)p.event=me(p.event);}renumberWarned.clear();setTimeout(()=>window.STUDIO_EVENTS?.refresh?.(),0);}
  S.order=S.order.map(mt);
  const folders={};for(const [key,f]of Object.entries(S.branchFolders)){const g=clone(f);for(const field of ['parentTalkId','routerId','exitId','endId'])if(g[field]!==undefined)g[field]=mt(g[field]);for(const field of ['talkIds','baseNext'])if(Array.isArray(g[field]))g[field]=mtAll(g[field]);if(Array.isArray(g.failureNext))g.failureNext=mtAll(g.failureNext);if(g.optionId!==undefined)g.optionId=mo(g.optionId);if(g.continuation?.kind==='talk')g.continuation.talkId=mt(g.continuation.talkId);if(g.continuation?.kind==='event')g.continuation.eventId=me(g.continuation.eventId);if(g.continuation?.kind==='targets')g.continuation.targets=mtAll(g.continuation.targets);folders[mapKey(key)]=g;}
  S.branchFolders=folders;
  const cues=S.doc.audioCues||{};for(const field of ['sfx','nativeAudio','nativeSnapshot'])if(cues[field]&&typeof cues[field]==='object')cues[field]=Object.fromEntries(Object.entries(cues[field]).map(([id,v])=>[String(mt(id)),v]));if(Array.isArray(cues.bgm))cues.bgm=cues.bgm.map(g=>({...g,talkIds:mtAll(g.talkIds)}));
  if(S.doc.talkOwners)S.doc.talkOwners=Object.fromEntries(Object.entries(S.doc.talkOwners).map(([id,v])=>[String(mt(id)),Array.isArray(v)?v.map(me):v]));
  S.localIds.talks=previousLocal.talks.map(mt);S.localIds.options=previousLocal.options.map(mo);S.localIds.events=previousLocal.events.map(me);
  S.pinned={talks:new Set([...S.pinned.talks].map(mt)),options:new Set([...S.pinned.options].map(mo)),events:new Set([...S.pinned.events].map(me))};
  const reused=new Set(Object.values(tm).map(Number));
  S.deleted=S.deleted.filter(id=>!reused.has(Number(id)));
  S.replacements=Object.fromEntries(Object.entries(S.replacements).filter(([id])=>!reused.has(Number(id))).map(([id,v])=>[id,mtAll(v)]));
  S.selected=S.selected==null?null:mt(S.selected);S.activeFolder=mapKey(S.activeFolder);S.folderOpen=Object.fromEntries(Object.entries(S.folderOpen).map(([k,v])=>[mapKey(k),v]));
  S.idMappings=composeMappings(S.idMappings,result.mappings);S.coalesce=null;
  invalidateStageMemo();updateDirty();render();
}
// ---- Double-click an ID to open the shared draft-aware number editor. ----
function inlineIdEdit(prefix,commit){
  const oldId=prefix.textContent.replace(/[\[\]\s]/g,'');
  window.STUDIO_IDS.inline(prefix,{oldId,commit});
}
// A hand-typed number is taken literally and pinned: it is never renumbered automatically. Another local row
// already holding that number swaps IDs with this one; an original row's number may be taken (override).
function idInput(raw){const n=Number(String(raw).trim());if(!Number.isInteger(n)||n<=0||n>2147483647)throw Error('请输入 1 到 2147483647 之间的整数编号。');return n;}
async function setTalkId(id,raw){
  id=Number(id);const n=idInput(raw);if(n===id)return;if(!editable())return;if(!S.doc.talks[id])throw Error('这句对话已变化，请关闭窗口后重新选择。');
  const other=S.doc.talks[n]&&localStoryIds('talks').has(n)?n:null;
  const ok=await runRenumber({TalkCfg:other?{[id]:n,[n]:id}:{[id]:n}},'修改对话编号');
  if(!ok)throw Error('内容正在变化，编号尚未修改，请再次应用。');
  S.pinned.talks.add(n);updateDirty();renderList();
  toast(other?'对话编号已与原 ['+n+'] 交换，两句的前后连接保持不变。':S.catalogAll.talks?.has(String(n))?'对话编号已改为 '+n+'，与原版对话相同，游戏中会覆盖原版。':'对话编号已改为 '+n+'，不会再被自动整理。','note');
  return true;
}
async function setOptionId(parent,oid,raw){
  oid=Number(oid);const n=idInput(raw);if(n===oid)return;if(!editable())return;if(!S.doc.options[oid])throw Error('这个选项已变化，请关闭窗口后重新选择。');
  const other=S.doc.options[n]&&localStoryIds('options').has(n)?n:null;
  const ok=await runRenumber({OptionCfg:other?{[oid]:n,[n]:oid}:{[oid]:n}},'修改选项编号');
  if(!ok)throw Error('内容正在变化，编号尚未修改，请再次应用。');
  S.pinned.options.add(n);updateDirty();renderList();renderEditor();
  toast(other?'选项编号已与原 ['+n+'] 交换。':'选项编号已改为 '+n+'，不会再被自动整理。','note');
  return true;
}
// Conflict/pin notes shown under a record: an ID shared with an original row (the mod overrides it in
// the game) and a hand-set ID that automatic numbering leaves alone.
function idConflict(kind,id){const table={talks:'TalkCfg',options:'OptionCfg',events:'EvtCfg'}[kind];if(!S.catalogAll?.[kind]?.has(String(id))||!(S.localIds?.[kind]||[]).map(String).includes(String(id)))return '';const label={talks:'对话',options:'选项',events:'事件'}[kind];const row=S.conditionRefs?.[table]?.[id];const name=row?String(row.title||row.content||row.name||'').slice(0,20):'';return `<span class="id-conflict" title="游戏中本模组的这条会覆盖原版的同编号内容">⚠ 与原版${label} [${id}]${name?' '+h(name):''} 冲突</span>`;}
function idPinNote(kind,id){return kind!=='events'&&S.pinned?.[kind]?.has(Number(id))?'<span class="id-pinned" title="手动指定的编号，不会自动整理；右键可恢复自动编号">固定编号</span>':'';}
window.STUDIO_ID_NOTES=(kind,id)=>idConflict(kind,id)+idPinNote(kind,id);
function unpinId(kind,id){if(S.pinned[kind].has(Number(id)))history('恢复自动编号');if(S.pinned[kind].delete(Number(id))){updateDirty();renderList();scheduleRenumber();toast('已恢复自动编号。','note');}}
// The second click of a double-click is caught in the capture phase: the first click may
// already have re-rendered the list (select / toggle), so the native dblclick never fires.
document.addEventListener('click',e=>{
  const prefix=e.target.closest('.record-id-prefix');if(!prefix||prefix.querySelector('input'))return;
  // The number itself is not a button: a single click on it must not open the event, select the line or
  // toggle the folder — otherwise the first half of a double-click would already navigate away.
  if(prefix.closest('button,a,summary,label,[role="button"],[data-action]')){e.preventDefault();e.stopPropagation();}
  if(e.detail<2||!S.doc||S.project?.readOnly)return;
  const card=prefix.closest('#talk-list .talk-card');if(card){inlineIdEdit(prefix,v=>setTalkId(Number(card.dataset.id),v));return;}
  const eventCard=prefix.closest('#story-events .event-card-open');if(eventCard){inlineIdEdit(prefix,v=>renameEvent(Number(eventCard.dataset.enterEvent),idInput(v)));return;}
  const title=prefix.closest('#talk-list .branch-folder-title');
  if(title){if(title.closest('.conditional-folder'))return;const key=title.dataset.folderKey;inlineIdEdit(prefix,v=>{const [parent,oid]=String(key).split(':');return setOptionId(Number(parent),Number(oid),v);});return;}
  const scope=prefix.closest('.wk-record-heading,.character-record-heading,.character-record-title,article,section,form,header');const button=prefix.closest('[data-record-table][data-record-id]')||scope?.querySelector('[data-record-table][data-record-id]');
  if(button&&!button.disabled)window.STUDIO_IDS.open(button.dataset.recordTable,button.dataset.recordId,prefix);
},true);
function renumberableEvent(){return S.event!=='all'&&S.doc?.events?.[S.event]&&!S.catalogIds?.events?.has(String(S.event))&&!S.project?.originalMode?Number(S.event):null;}
// ---- Speakers: several people may speak one line; a custom name replaces the joined names. ----
function renderSpeakers(state){
  const box=$('#scene-speakers');if(!box)return;const t=talk();if(!t){box.innerHTML='';return;}
  const speaking=ids(t.roleIds).filter(id=>id>=0),readOnly=!!S.project?.readOnly;
  box.innerHTML=`<span class="scene-speakers-label">说话人</span>${speaking.length?speaking.map(id=>`<span class="speaker-chip"><span class="speaker-name" title="${h(personName(id))}">${h(personName(id))}</span><button type="button" data-action="speaker-remove" data-id="${id}" aria-label="移除说话人 ${h(personName(id))}" ${readOnly?'disabled':''}>×</button></span>`).join(''):'<span class="speaker-chip speaker-narrator">旁白</span>'}<button type="button" class="speaker-add" data-action="speaker-add" ${readOnly?'disabled':''}>＋ 说话人</button><label class="speaker-custom"><span>显示名称</span><input data-speaker-name value="${h(t.roleName||'')}" placeholder="${h(speaking.map(personName).join('、')||'旁白')}" ${readOnly?'disabled':''}></label>`;
}
function addSpeaker(id){if(!editable()||!talk())return;mutate('添加说话人',()=>{const t=talk();const list=ids(t.roleIds).filter(v=>v>=0);if(!list.includes(Number(id)))list.push(Number(id));t.roleIds=list;S.previewRole=Number(id);});}
function removeSpeaker(id){if(!editable()||!talk())return;mutate('移除说话人',()=>{const t=talk();t.roleIds=ids(t.roleIds).filter(v=>v!==Number(id));});}
function setSpeakerName(value){if(!editable()||!talk())return;mutate('设置说话人名称',()=>{talk().roleName=value.trim();},'speaker-name:'+S.selected,false);}
async function openSpeakerPicker(anchor){
 const t=talk(),project=S.project?.id;if(!t||!editable())return;
 const picked=await STUDIO_ASSET_PICKER.pickRecords('portrait',{title:'选择说话人',projectId:project,rows:[{id:-1,name:'旁白',selectionOnly:true,exclusive:true},...values(S.doc.persons).filter(r=>!S.goalImageIds?.includes(String(r.id)))],multiple:true,selected:t.roleIds?.length?t.roleIds:[-1]});
 if(picked&&S.project?.id===project&&talk()===t)mutate('设置说话人',()=>{t.roleIds=picked.some(r=>r.id===-1)?[]:picked.map(r=>Number(r.id));});
}

function popupMenu(anchor,items){
  closeTalkMenu();const menu=document.createElement('div');menu.id='talk-context-menu';menu.className='talk-context-menu';menu.setAttribute('role','menu');
  menu.innerHTML=items.map((it,i)=>`<button role="menuitem" data-popup-item="${i}" class="${it.danger?'danger-text':''}" ${it.disabled?'disabled':''}>${h(it.label)}</button>`).join('');document.body.append(menu);
  const r=anchor.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(r.left,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(r.top-menu.offsetHeight-6,innerHeight-menu.offsetHeight-8))+'px';
  menu.addEventListener('click',e=>{const b=e.target.closest('[data-popup-item]');if(!b||b.disabled)return;closeTalkMenu();try{items[Number(b.dataset.popupItem)].run();}catch(error){fail(error);}});
}
function openScreenEffectMenu(anchor){
  const t=talk();if(!t)return;const effect=StudentAgeScreenEffects.entries.find(e=>e.id===Number(t.screenEffect?.[0])),hasPaper=(t.roles||[]).some(r=>Number(r[1])===5001);
  popupMenu(anchor,[{label:effect?'屏幕效果：'+effect.name+'（更换）':'添加屏幕效果…',run:editScreenEffect},{label:hasPaper?'编辑纸条…':'添加纸条…',run:editPaper},...(t.screenEffect?.length?[{label:'移除屏幕效果',danger:true,run:()=>mutate('移除屏幕效果',()=>talk().screenEffect=[])}]:[])]);
}
function openCGMenu(x,y){
  const t=talk();if(!t||!editable())return;const state=currentStage();if(!state.cg)return;
  closeTalkMenu();const menu=document.createElement('div');menu.id='talk-context-menu';menu.className='talk-context-menu';menu.setAttribute('role','menu');
  const own=Number(t.screenEffect?.[0])===4015;
  menu.innerHTML=`<strong>CG</strong>${own?'<button role="menuitem" data-cg-menu="replace">更换此 CG</button>':''}<button role="menuitem" class="danger-text" data-cg-menu="delete">${own?'删除此 CG':'从这句起关闭 CG'}</button>`;document.body.append(menu);
  menu.style.left=Math.max(8,Math.min(x,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(y,innerHeight-menu.offsetHeight-8))+'px';
  menu.addEventListener('click',e=>{const op=e.target.closest('[data-cg-menu]')?.dataset.cgMenu;if(!op)return;closeTalkMenu();if(op==='replace')openAssetPicker('cg',{intent:'replace-cg'});else mutate(own?'删除 CG':'关闭 CG',()=>{talk().screenEffect=own?[]:[4017];});});
}
// ---- Jump picker: any real line, searchable by ID or text, with its folder path. ----
function talkPath(id){const parts=[];let key=Timeline.owner(S.branchFolders,id);const seen=new Set();while(key&&!seen.has(key)){seen.add(key);const f=S.branchFolders[key];if(!f)break;parts.unshift(f.kind==='condition'?'分支'+f.branchId:'选项 '+(S.doc.options[f.optionId]?.content||f.optionId));key=Timeline.owner(S.branchFolders,f.parentTalkId);}return parts.join(' › ');}
function openJumpPicker(fromId){
  const t=S.doc.talks[fromId];if(!t||!editable())return;
  const hidden=Timeline.internals(S.branchFolders),list=S.order.filter(id=>S.doc.talks[id]&&!hidden.has(id)&&id!==Number(fromId));
  const current=ids(Timeline.next(S.doc,S.branchFolders,fromId))[0]||0;
  const row=id=>`<button type="button" class="jump-row ${id===current?'active':''}" data-jump="${id}"><span class="jump-id">${h(String(id))}</span><span class="jump-text"><strong>${h(speaker(S.doc.talks[id]))}</strong> ${h((S.doc.talks[id].content||'空白对话').slice(0,40))}</span>${talkPath(id)?`<small>${h(talkPath(id))}</small>`:''}</button>`;
  modal('跳转到…',`<p class="helper">选择这句播放完后接到哪一句；分支和选项里的对话也可以选。</p><input id="jump-search" placeholder="按编号或内容搜索"><div id="jump-list" class="jump-list">${list.slice(0,200).map(row).join('')}</div>`,[{label:'结束这段对话',run:()=>{closeModal();mutate('设置下一句',()=>Timeline.setNext(S.doc,S.branchFolders,fromId,[]));}},{label:'取消',run:closeModal}]);
  const search=$('#jump-search');search.oninput=()=>{const q=search.value.trim().toLowerCase();$('#jump-list').innerHTML=list.filter(id=>!q||String(id).includes(q)||(S.doc.talks[id].content||'').toLowerCase().includes(q)||speaker(S.doc.talks[id]).toLowerCase().includes(q)).slice(0,200).map(row).join('');};
  $('#jump-list').onclick=e=>{const b=e.target.closest('[data-jump]');if(!b)return;const target=Number(b.dataset.jump);closeModal();mutate('设置下一句',()=>Timeline.setNext(S.doc,S.branchFolders,fromId,[target]));toast('已接到 '+target+'。');};
  search.focus();
}
// ---- Option with its settings in one dialog ----
function addOptionWithSettings(){
  const t=talk();if(!t||!editable())return;
  if(Timeline.entries(S.branchFolders,t.id).length){toast('这句已有条件分支，请在分支内的对话上添加玩家选项。','note');return;}
  modal('添加选项',`<label class="field-label">选项文字</label><input id="new-option-content" value="新的选择"><p class="helper">创建后可继续设置可用条件与成功判定；左侧会出现该选项的对话夹。</p>`,[{label:'取消',run:closeModal},{label:'创建并设置条件',run:()=>{const content=$('#new-option-content').value;closeModal();addOption();const oid=ids(talk()?.option).at(-1);if(oid&&S.doc.options[oid]){mutate('设置选项文字',()=>{S.doc.options[oid].content=content;},null,false);render();openConditionSettings('options',oid,'precondition','选项「'+content+'」· 可用条件');}}},{label:'创建',primary:true,run:()=>{const content=$('#new-option-content').value;closeModal();addOption();const oid=ids(talk()?.option).at(-1);if(oid&&S.doc.options[oid])mutate('设置选项文字',()=>{S.doc.options[oid].content=content;});}}]);
  setTimeout(()=>$('#new-option-content')?.select(),0);
}
function replaceEdges(target,replacements,except=null) {Timeline.replace(S.doc,S.branchFolders,target,replacements,new Set(except===null?[]:[except]));}
function deleteTalk(){return deleteTalkChecked().catch(error=>{fail(error);return false;});}
async function deleteTalkChecked() {
  const t=talk();if(!t||!editable())return;
  const hidden=Timeline.internals(S.branchFolders),group=Timeline.entries(S.branchFolders,t.id),candidates=Array.from(new Set(group.length?[...Timeline.next(S.doc,S.branchFolders,t.id),...group.flatMap(([,f])=>ids(f.talkIds).slice(0,1))]:links(t))).filter(id=>id!==t.id&&!hidden.has(id));
  const signature=currentSignature(),project=S.project.id,created=premiseHolders(t),remaining=premiseHolders({...S.doc,talks:Object.fromEntries(Object.entries(S.doc.talks).filter(([id])=>Number(id)!==t.id))});
  const removedPremises=Object.entries(S.premises).filter(([,p])=>created.has(p.eventId+':'+p.slot)&&!remaining.has(p.eventId+':'+p.slot));
  if(removedPremises.length){
    const references=await Promise.all(removedPremises.map(async([key,p])=>({key,p,...await api('/api/premises/references',{projectId:project,eventId:p.eventId,slot:p.slot,talkId:p.talkId,...Object.fromEntries(MAPS.map(k=>[k,S.doc[k]]))})})));
    const used=references.filter(r=>r.references.length);
    if(used.length&&!await new Promise(resolve=>{const d=document.createElement('dialog');d.className='save-review-dialog';d.innerHTML='<h2>删除对话及其前提？</h2>'+used.map(r=>'<p>'+h(r.references.join('、'))+' 引用了该对话创造的前提「'+h(r.p.name)+'」。</p>').join('')+'<p>确定删除后，会一并移除这些前提和对应的前提条件；其他条件保留。</p><footer><button data-delete-premise-cancel>取消</button><button data-delete-premise-confirm class="danger-button">确定删除</button></footer>';document.body.append(d);const end=v=>{d.close();d.remove();resolve(v);};d.querySelector('[data-delete-premise-cancel]').onclick=()=>end(false);d.querySelector('[data-delete-premise-confirm]').onclick=()=>end(true);d.oncancel=e=>{e.preventDefault();end(false);};d.showModal();}))return false;
    if(project!==S.project.id||signature!==currentSignature())throw Error('对话内容已变化，未执行删除，请重新点击。');
  }
  const execute=replacements=>mutate('删除对话',()=>{
    removePremises(removedPremises.map(([key])=>key));
    const id=t.id,index=S.order.indexOf(id);delete S.doc.talks[id];S.order=S.order.filter(x=>x!==id);S.deleted.push(id);S.replacements[id]=replacements;
    delete S.doc.audioCues.sfx[id];if(S.doc.audioCues.nativeAudio)delete S.doc.audioCues.nativeAudio[id];S.doc.audioCues.bgm=S.doc.audioCues.bgm.map(g=>({...g,talkIds:ids(g.talkIds).filter(x=>x!==id)})).filter(g=>g.talkIds.length);
    replaceEdges(id,replacements);
    for(const [key,f]of Timeline.entries(S.branchFolders,id)){
      for(const generated of new Set([f.routerId,f.exitId,f.endId]))if(S.doc.talks[generated]){delete S.doc.talks[generated];S.deleted.push(generated);S.replacements[generated]=replacements;replaceEdges(generated,replacements);S.order=S.order.filter(x=>x!==generated);}
      delete S.branchFolders[key];
    }
    for(const oid of ids(t.option)){const shared=values(S.doc.talks).some(x=>ids(x.option).includes(oid))||values(S.doc.events).some(x=>ids(x.options).includes(oid));if(!shared)delete S.doc.options[oid];}
    S.branchFolders=Branches.cleanup(S.doc,S.branchFolders,S.replacements);for(const parent of new Set(values(S.branchFolders).filter(f=>f.kind==='condition').map(f=>f.parentTalkId)))Timeline.sync(S.doc,S.branchFolders,parent);S.selected=S.order[Math.min(index,S.order.length-1)]||null;S.activeFolder=Branches.ownedBy(S.branchFolders,S.selected);
  });
  execute(candidates.slice(0,1));

}
function deleteFolder(key){
 if(!editable())return;
 const doc=clone(S.doc),folders=clone(S.branchFolders),result=Timeline.removeFolder(doc,folders,key),removed=new Set(result.deleted);
 mutate('删除分支或对话夹',()=>{
  S.doc=doc;S.branchFolders=folders;S.order=S.order.filter(id=>!removed.has(id));S.deleted=[...new Set([...S.deleted,...result.deleted])];Object.assign(S.replacements,result.replacements);
  for(const id of removed){delete S.doc.audioCues.sfx[id];if(S.doc.audioCues.nativeAudio)delete S.doc.audioCues.nativeAudio[id];}
  S.doc.audioCues.bgm=S.doc.audioCues.bgm.map(g=>({...g,talkIds:ids(g.talkIds).filter(id=>!removed.has(id))})).filter(g=>g.talkIds.length);
  for(const id of Object.keys(S.folderOpen))if(!folders[id])delete S.folderOpen[id];
  S.selected=result.parentId;S.activeFolder=Timeline.owner(folders,S.selected);
 });
 toast('已删除分支或对话夹，可以撤销。');
}

function reorderTalk(source,target,after=false){
  if(!editable())return;
  // Validate on copies before adding an undo entry or touching the document.
  const doc=clone(S.doc),folders=clone(S.branchFolders),order=Timeline.reorder(doc,folders,S.order,source,target,after);
  if(JSON.stringify(order)===JSON.stringify(S.order))return;
  mutate('调整对话顺序',()=>{S.doc=doc;S.branchFolders=folders;S.order=order;S.selected=Number(source);S.activeFolder=Timeline.owner(folders,source);});
  toast('对话顺序与播放顺序已更新。');
}
function moveTalk(direction){const list=visibleIds().filter(id=>Timeline.owner(S.branchFolders,id)===S.activeFolder),at=list.indexOf(S.selected),other=list[at+direction];if(other!==undefined)reorderTalk(S.selected,other,direction>0);}
function addConditionalBranch(){
 if(!editable()||!talk())return;
 mutate('添加条件分支',()=>{const d=Timeline.addCondition(S.doc,S.branchFolders,S.selected,newTalkId);S.folderOpen[d.key]=true;S.activeFolder=d.key;});
 const d=Timeline.entries(S.branchFolders,S.selected).at(-1);if(d)openConditionSettings('talks',d[1].routerId,'check','分支'+d[1].branchId+' · 触发条件');
}
function openConditionSettings(scope,id,field,title){
 const row=S.doc?.[scope]?.[id];if(!row)return;
 modal(title,`<div id="route-condition-editor"></div>`,[{label:'完成',primary:true,run:closeModal}]);
 Conditions.mount($('#route-condition-editor'),{rows:row[field]||[],templates:allConditionTemplates(),refs:{...S.conditionRefs,PersonCfg:S.doc.persons,EvtCfg:{...S.conditionRefs.EvtCfg,...S.doc.events}},localIds:S.conditionLocalIds,readOnly:S.project?.readOnly||S.conditionsLoading,description:field==='precondition'?'必须满足全部限制，玩家才能点击这个选项。':scope==='options'?'全部满足时走成功去向，否则走失败去向。未设置判定时直接成功。':'按左侧顺序判断，进入首个满足条件的分支；判定失败时按分支的失败去向继续，默认判断后续分支或继续下面的对话。未设置条件时直接进入。',onChange:rows=>{mutate('修改分支限制',()=>row[field]=rows,null,false);renderList();renderEditor();scenePlayer?.refresh();}});
}
function addOption() {
  const t=talk();if(!t)return;if(Timeline.entries(S.branchFolders,t.id).length){toast('这句已有条件分支，请在分支内的对话上添加玩家选项。','note');return;}mutate('添加对话选项',()=>{const id=nextId(S.doc.options,eventForTalk()*100+1);S.doc.options[id]={id,content:'新的选择',talkId:[],talkId2:[],effect:[],effect2:[],check:[],precondition:[]};t.option=[...ids(t.option),id];Branches.create(S.doc,S.branchFolders,t.id,id);S.folderOpen[Branches.key(t.id,id)]=true;});
}
function deleteOption(oid) {
  const t=talk();if(!t)return;mutate('删除对话选项',()=>{t.option=ids(t.option).filter(x=>x!==oid);if(!values(S.doc.talks).some(x=>ids(x.option).includes(oid))&&!values(S.doc.events).some(x=>ids(x.options).includes(oid)))delete S.doc.options[oid];S.branchFolders=Branches.cleanup(S.doc,S.branchFolders);if(S.activeFolder&&!S.branchFolders[S.activeFolder])S.activeFolder=null;});
}

function allConditionTemplates(){return [...Effects.conditionTemplates(S.premises),...S.conditionTemplates];}
function effectMarkup(scope,id,field,title,description,folded=false){const count=S.doc?.[scope]?.[id]?.[field]?.length||0,body=`<div data-effect-scope="${scope}" data-effect-id="${id}" data-effect-field="${field}" data-effect-description="${h(description)}"></div>`;return folded?`<details class="effect-section" ${count?'open':''}><summary>${h(title)} <span>${count} 项</span></summary>${body}</details>`:`<section class="effect-section effect-section-visible"><div class="section-title"><h3>${h(title)}</h3><span>${count} 项</span></div>${body}</section>`;}
function mountEffectEditors(root){
 root.querySelectorAll('[data-effect-scope]').forEach(node=>{const scope=node.dataset.effectScope,id=Number(node.dataset.effectId),field=node.dataset.effectField,row=S.doc?.[scope]?.[id];if(!row)return;
  Effects.mount(node,{rows:row[field]||[],templates:S.effectTemplates,refs:S.conditionRefs,getPremises:()=>S.premises,talkId:scope==='talks'?id:undefined,readOnly:S.project?.readOnly||S.conditionsLoading,description:node.dataset.effectDescription,onError:fail,
   onChange:rows=>{mutate('修改剧情效果',()=>row[field]=rows,null,false);node.closest('.effect-section')?.querySelector('.section-title span,summary span')?.replaceChildren(document.createTextNode(rows.length+' 项'));},
   onCreatePremise:()=>createPremise(scope,id,field,true),
   onRenamePremise:(premiseId,name)=>{const p=S.premises[premiseId];if(!p)return;const normalized=name.trim()||'前提'+p.id;if(values(S.premises).some(other=>String(other.id)!==String(p.id)&&other.name===normalized))throw Error('已有同名的前提，请使用不同名称。');mutate('重命名前提',()=>p.name=normalized,null,false);}
  });
 });
}
async function createPremise(scope,id,field,catalogue=false){
 if(!editable())return;const row=S.doc?.[scope]?.[id];if(!row)return;
 // A premise is editor data only ({id,name,talkId} in editor-state.json): "this line has been reached".
 // Nothing is written into the game's tables until the premise is picked as a condition, which then
 // saves as the native 3,3,<talk> check (未达成 = 3,-3,<talk>). No server round trip, no slot bookkeeping.
 const talkId=scope==='talks'?Number(id):(S.doc.talks?.[S.selected]?Number(S.selected):null);
 if(!talkId)throw Error('前提以“到达某句对话”为达成条件，请先选中一句对话再创建。');
 const projectId=S.project.id,used=new Set(values(S.premises).map(p=>p.name));let nextId=Math.max(0,...Object.keys(S.premises).map(Number).filter(Number.isInteger))+1,suggested='前提'+nextId;while(used.has(suggested))suggested='前提'+(++nextId);
 const name=await new Promise(resolve=>{
  const d=document.createElement('dialog');d.className='character-picker premise-create-dialog premise-talk-dialog';d.setAttribute('aria-labelledby','premise-create-title');
  d.innerHTML=`<header><h2 id="premise-create-title">创建前提</h2><p>为这句对话设置一个可供后续判断的标记。</p></header><label>前提名称<input data-name autofocus maxlength="120" value="${h(suggested)}" placeholder="例如：得知约定" aria-describedby="premise-create-error"></label><section class="premise-target" aria-label="达成位置"><strong>到达这句对话时达成</strong><blockquote>${h(S.doc.talks[talkId]?.content||'（空白对话）')}</blockquote><small>对话编号 ${talkId}</small></section><p>创建后，可在条件目录中选择这个前提的“已达成”或“未达成”。</p><p id="premise-create-error" data-error role="status"></p><footer><button data-cancel>取消</button><button data-confirm class="primary">创建前提</button></footer>`;
  document.body.append(d);
  const input=d.querySelector('[data-name]'),error=d.querySelector('[data-error]');
  const end=v=>{d.close();d.remove();resolve(v);},submit=()=>{const value=input.value.trim();if(!value){error.textContent='请输入前提名称。';input.setAttribute('aria-invalid','true');input.focus();return;}end(value);};
  d.querySelector('[data-cancel]').onclick=()=>end(null);d.oncancel=e=>{e.preventDefault();end(null);};d.querySelector('[data-confirm]').onclick=submit;
  input.oninput=()=>{error.textContent='';input.removeAttribute('aria-invalid');};input.onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing&&e.keyCode!==229){e.preventDefault();submit();}};
  d.showModal();input.select();
 });
 if(!name)return;
 if(S.project?.id!==projectId||S.doc?.[scope]?.[id]!==row)throw Error('当前对话已变化，请重新添加前提。');
 const premise={id:nextId,name,talkId,eventId:Number.isInteger(Number(eventForTalk()))&&S.doc.events[eventForTalk()]?Number(eventForTalk()):0,slot:nextId};
 mutate('添加命名前提',()=>{S.premises[String(premise.id)]=premise;},null,true);
 toast('前提「'+name+'」已创建：到达对话 ['+talkId+'] 即达成，可在条件目录里选用。','note');
 return premise;
}
function previewHistory(){const id=S.project?.id;if(!previewHistories.has(id))previewHistories.set(id,new HistoryExport.Recorder());return previewHistories.get(id);}
function historyScene(scene){
 if(!scene)return scene;
 const portraits=(scene.speakerIds||[]).flatMap(id=>{
  const role=scene.roles?.[id],person=S.doc.persons?.[id];if(!role||!person)return [];
  const face=S.doc.faces?.[id*1000+role.cloth*100+role.face],young=(role.grade===0&&person.url?.length)||(role.grade===1&&!person.url2?.length),exact=face&&(young?face.icon_xx:face.icon);
  const model=!!(role.grade===0?person.l2d:person.l2d2)?.length;
  let paths=StudentAgeScene.portraitCandidates(S.doc,role);
  if(role.face&&model)paths=paths.filter(path=>path===exact||path===`portrait-cache/${portraitIdentity(id)}-${role.grade}-${role.cloth}-${role.face}.png`);
  return [{id,name:person.name||scene.speaker,face:role.face,cloth:role.cloth,grade:role.grade,flip:role.flip,gender:id===0?protagonistGender():1,model,paths,projectId:S.project.id}];
 });return {...scene,portraits};
}
function recordPreviewHistory(event){if(!S.project)return;const recorder=previewHistory();if(event.kind==='start')recorder.begin(S.doc,event.talkId,{title:S.doc.events[S.event]?.title||S.project.name,reason:event.reason,scene:historyScene(event.scene)});else if(event.kind==='line')recorder.visit(S.doc,event.talkId,historyScene(event.scene));else if(event.kind==='choice')recorder.choice(event.route);else if(event.kind==='end')recorder.finish();const count=$('#preview-history-count');if(count)count.textContent='已预演 '+recorder.count()+' 句';}
function exportDialogueRows(){
 const hidden=Timeline.internals(S.branchFolders),document=HistoryExport.fullStory(S.doc,S.event,S.order);
 return document.sessions.flatMap(session=>session.entries).filter(row=>row.kind==='dialogue'&&!hidden.has(row.talkId));
}
function showHistoryExport(){
 if(!S.project)return;stopLinePlayback();scenePlayer?.pause();
 const rows=exportDialogueRows();let content=StudentAgeDialogueText.serialize(rows);
 modal('导出对话',`<p>共 ${rows.length} 句，每句一行。</p><label>分隔格式<select id="dialogue-export-separator"><option value=" ">人物 对话内容</option><option value="：">人物：对话内容</option><option value=":">人物:对话内容</option></select></label><p></p><p class="helper">正文中的换行写为 \\n。此格式可直接导入；分支条件、动作与素材不包含在文本中。</p><textarea id="dialogue-export-text" readonly rows="10">${h(content)}</textarea>`,[{label:'关闭',run:closeModal},{label:'导出 TXT',primary:true,run:async()=>{
  const result=await api('/api/export',{projectId:S.project.id,format:'txt',filename:HistoryExport.filename(S.doc.events[S.event]?.title||S.project.name,'full-story','txt'),content});
  modal('导出完成',`<p>${h(result.name)}</p><p class="link-path">${h(result.path)}</p><a href="${h(result.url+(result.url.includes('?')?'&':'?')+'token='+encodeURIComponent(token))}" download="${h(result.name)}">下载对话</a>`,[{label:'关闭',run:closeModal},{label:'打开所在文件夹',primary:true,run:()=>api('/api/open-export',{name:result.name})}]);
 }}]);
 $('#dialogue-export-separator').onchange=e=>{content=StudentAgeDialogueText.serialize(rows,e.target.value);$('#dialogue-export-text').value=content;};
}
function importDialogueRows(rows){
 if(!editable()||!rows.length)return [];
 if(rows.length>2000)throw Error('一次最多导入 2000 句对话。');
 if(rows.some(row=>row.roleIds===null))throw Error('请先匹配所有说话人物。');
 if(!S.doc.events[S.event])throw Error('先选择一个剧情事件，再导入对话。');
 if(ids(talk()?.option).length&&!S.activeFolder)throw Error('当前句包含选项，请先选择左侧的选项对话夹再导入。');
 const created=[],prior=snapshot('导入前'),undoBefore=S.undo.slice(),redoBefore=S.redo.slice();let state=talk()?currentStage():StudentAgeScene.blank(S.referenceResolution);
 try{mutate('导入对话',()=>{
  const descriptor=S.activeFolder?takeFolder(S.activeFolder):null,folder=descriptor?.folder;
  if(descriptor)S.activeFolder=descriptor.key;
  let previous=talk(),insertion=S.selected;
  if(folder&&!ids(folder.talkIds).includes(insertion)){insertion=ids(folder.talkIds).at(-1)||null;previous=S.doc.talks[insertion||folder.parentTalkId];state=stageAt(previous.id);}
  for(const imported of rows){
   const id=newTalkId(),row=continuationTalk(id,previous,state);row.content=imported.content;row.roleIds=imported.roleIds.slice();row.roleName=row.roleIds.length&&row.roleIds.map(personName).join('、')!==imported.speaker?imported.speaker:'';row.screenEffect=state.cg?[4017]:[];
   let occupied=values(state.roles).filter(role=>role.visible);
   for(const roleId of row.roleIds)if(!state.roles[roleId]?.visible){const axis=occupied.length===0?1:!occupied.some(role=>role.axis===2)?2:3;row.roles.push([roleId,1002,1,axis,0]);occupied.push({id:roleId,axis});}
   if(folder)Timeline.insert(S.doc,S.branchFolders,folder,row,insertion);
   else{row.nextTalk=previous?Timeline.next(S.doc,S.branchFolders,previous.id):[];if(previous)Timeline.setNext(S.doc,S.branchFolders,previous.id,[id]);else S.doc.events[S.event].talkId=[id];S.doc.talks[id]=row;}
   const index=S.order.indexOf(previous?.id);S.order.splice(index<0?S.order.length:index+1,0,id);S.selected=id;created.push(id);state=StudentAgeScene.apply(S.doc,state,row,S.grade);previous=row;insertion=id;
  }
  if(folder){folder.collapsed=false;S.folderOpen[S.activeFolder]=true;}S.search='';$('#talk-search').value='';
 });
 }catch(error){S.undo=undoBefore;S.redo=redoBefore;restore(prior);throw error;}
 S.selected=created.at(-1);scenePlayer?.dispose();scenePlayer=null;render();return created;
}
function showDialogueImport(){
 if(!editable())return;stopLinePlayback();const project=S.project.id,anchor=S.selected,folder=S.activeFolder,bindings={};let parsed={rows:[],errors:[],unmatched:[]};
 modal('导入对话',`<p>导入位置：${anchor?'当前所选对话之后':'当前事件开头'}。导入后选中最后一句，继续导入会接在它后面。</p><p>每行支持：人物 对话、人物：对话、人物:对话。不带人名和分隔符的行自动识别为旁白。按名字识别人物，导入后自动登场，并沿用背景与已有在场人物。</p><label class="dialogue-file-label">读取 TXT 文件<input type="file" id="dialogue-import-file" accept=".txt,text/plain"></label><textarea id="dialogue-import-text" rows="9" placeholder="白雨 今天去哪里？&#10;梁超杰 去操场吧。&#10;两个人走出教室。"></textarea><p class="helper">也可直接粘贴。正文中的换行用 \\n 表示。新对话会接在当前句后，可一次撤销。</p><div id="dialogue-import-match"></div><p id="dialogue-import-count" role="status"></p>`,[{label:'取消',run:closeModal},{label:'导入对话',primary:true,run:()=>{
  if(S.project.id!==project||S.selected!==anchor||S.activeFolder!==folder)throw Error('导入位置已变化，请重新打开导入窗口。');refresh();if(parsed.errors.length||parsed.unmatched.length||!parsed.rows.length)throw Error('请检查文本格式并匹配人物。');
  const count=parsed.rows.length;importDialogueRows(parsed.rows);closeModal();toast('已导入 '+count+' 句对话。');
 }}]);
 function refresh(){parsed=StudentAgeDialogueText.parse($('#dialogue-import-text').value,S.doc.persons,bindings);const speakers=[...new Set(parsed.rows.map(row=>row.speaker))];
  $('#dialogue-import-match').innerHTML=speakers.map(name=>{const row=parsed.rows.find(row=>row.speaker===name);return `<label class="dialogue-person-match"><strong>${h(name)}</strong>${row.roleIds!==null&&!Object.hasOwn(bindings,name)?`<span>${row.roleIds.length?'已识别，将自动登场':'旁白'}</span>`:`<select data-reference-table="PersonCfg" data-import-speaker="${h(name)}" aria-label="匹配 ${h(name)}"><option value="">${row.candidates.length>1?'存在同名人物，请选择':'未匹配，请选择人物'}</option><option value="narrator" ${bindings[name]==='narrator'?'selected':''}>作为旁白</option>${values(S.doc.persons).filter(p=>!S.goalImageIds?.includes(String(p.id))).map(person=>`<option ${StudentAgeRecordLabels.option(person.id)} value="${person.id}" ${String(bindings[name])===String(person.id)?'selected':''}>${h(person.name)}</option>`).join('')}</select>`}</label>`;}).join('');
  $('#dialogue-import-count').textContent=parsed.errors.length?parsed.errors.map(error=>(error.line?'第 '+error.line+' 行：':'')+error.message).join('；'):parsed.rows.length+' 句对话 · '+parsed.unmatched.length+' 个人物待匹配';
  $('#modal [data-modal-button="1"]').disabled=!parsed.rows.length||!!parsed.errors.length||!!parsed.unmatched.length;
  $$('[data-import-speaker]').forEach(select=>select.onchange=()=>{if(select.value)bindings[select.dataset.importSpeaker]=select.value;else delete bindings[select.dataset.importSpeaker];refresh();});
 }
 $('#dialogue-import-text').oninput=refresh;
 $('#dialogue-import-file').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>2*1024*1024)throw Error('对话文件不能超过 2 MB。');const bytes=await file.arrayBuffer();let text;try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{text=new TextDecoder('gb18030').decode(bytes);}if(S.project.id!==project||!$('#dialogue-import-text'))return;$('#dialogue-import-text').value=text;refresh();}catch(error){fail(error);}};refresh();
}
let conditionLoadSequence=0,conditionLoadAbort=null;
function refreshConditionNotice(){
 const root=$('#editor-content');if(!root)return;root.querySelector('#condition-loading-notice')?.remove();
 if(!S.conditionsLoading&&!S.conditionsError)return;const notice=document.createElement('div');notice.id='condition-loading-notice';notice.className='notice-panel';notice.setAttribute('role','status');
 notice.append(document.createTextNode(S.conditionsLoading?'正在读取条件和效果目录，可先编辑对话内容。':S.conditionsError));
 if(!S.conditionsLoading){const retry=document.createElement('button');retry.dataset.action='retry-conditions';retry.textContent='重试读取';notice.append(retry);}root.prepend(notice);
}
async function loadConditionCatalog(){
 conditionLoadAbort?.abort();const controller=new AbortController();conditionLoadAbort=controller;const timeout=setTimeout(()=>controller.abort(),45000);
 const projectId=S.project.id,sequence=++conditionLoadSequence;
 S.conditionsLoading=true;S.conditionsError='';refreshConditionNotice();
 const current=()=>S.project?.id===projectId&&sequence===conditionLoadSequence;
 const get=async path=>{try{const r=await fetch(path,{headers:{'X-Studio-Token':token},signal:controller.signal}),d=await r.json();if(!r.ok||d.error)throw Error(d.error||'目录读取失败');return d;}catch(e){if(e.name==='AbortError')throw Error('读取超时，请重试');throw e;}};
 try{
  const data=await get('/api/commands?projectId='+encodeURIComponent(projectId)),templates=data.commands?.condition||[],effects=data.commands?.effect||[],refs={},localIds={};
  if(!templates.some(t=>Number(t.template?.[0])===7&&Number(t.template?.[1])===0))templates.unshift({label:'人物关系',template:[7,0,0,1],match:{0:7,1:0},parameters:[{index:2,label:'与谁',type:'int',range:{table:'PersonCfg'}},{index:3,label:'关系是',type:'int',range:{table:'OtherRelationCfg'}}]});
  const tables=[...new Set(['ConditionTypeCfg','EffectTypeCfg','EvtTypeCfg','MapCfg','ActionCfg','ActionEvtCfg','InteractCfg',...[...templates,...effects].flatMap(t=>(t.parameters||[]).map(p=>p.range?.table).filter(Boolean))])];
  let cursor=0;const failures=[];
  await Promise.all(Array.from({length:4},async()=>{while(cursor<tables.length&&current()){const name=tables[cursor++];try{const d=await get('/api/table?'+new URLSearchParams({projectId,name}));refs[name]=d.rows;localIds[name]=d.localIds||[];}catch(e){failures.push(name+'：'+e.message);}}}));
  if(!current())return false;
  const doc=S.doc;
  if(!Object.keys(refs.OtherRelationCfg||{}).length)refs.OtherRelationCfg=window.StudentAgeCommandTypes.otherRelations();
  refs.PersonCfg={...refs.PersonCfg,...doc.persons};for(const id of S.goalImageIds||[])delete refs.PersonCfg[id];refs.EvtCfg={...refs.EvtCfg,...doc.events};refs.OptionCfg={...refs.OptionCfg,...doc.options};refs.TalkCfg={...refs.TalkCfg,...doc.talks};
  S.conditionTemplates=templates;S.effectTemplates=effects;S.conditionRefs=refs;S.conditionLocalIds=localIds;
  S.conditionsError=failures.length?'部分目录未读取成功：'+failures.join('；'):'';return true;
 }catch(error){if(current())S.conditionsError='条件和效果目录读取失败：'+error.message;return false;}
 finally{clearTimeout(timeout);if(current()){conditionLoadAbort=null;S.conditionsLoading=false;window.STUDIO_EVENTS?.refresh();refreshConditionNotice();const root=$('#editor-content');mountConditionEditors(root);mountEffectEditors(root);}}
}
window.STUDIO_RETRY_CONDITIONS=()=>loadConditionCatalog();
function conditionMarkup(scope,id,field,title,description,forceOpen=false){return `<details class="condition-section" ${forceOpen||(S.doc?.[scope]?.[id]?.[field]||[]).length?'open':''}><summary>${h(title)} <span>${S.doc?.[scope]?.[id]?.[field]?.length||0} 项</span></summary><div data-condition-scope="${scope}" data-condition-id="${id}" data-condition-field="${field}" data-condition-description="${h(description)}"></div></details>`;}
function mountConditionEditors(root){
  root.querySelectorAll('[data-condition-scope]').forEach(node=>{const scope=node.dataset.conditionScope,id=Number(node.dataset.conditionId),field=node.dataset.conditionField,row=S.doc?.[scope]?.[id];if(!row)return;
    Conditions.mount(node,{rows:row[field]||[],templates:allConditionTemplates(),refs:{...S.conditionRefs,EvtCfg:{...S.conditionRefs.EvtCfg,...S.doc.events},OptionCfg:{...S.conditionRefs.OptionCfg,...S.doc.options},TalkCfg:{...S.conditionRefs.TalkCfg,...S.doc.talks}},localIds:S.conditionLocalIds,readOnly:S.project?.readOnly||S.conditionsLoading,description:node.dataset.conditionDescription,onChange:rows=>{mutate('修改剧情条件',()=>row[field]=rows,null,false);node.closest('details')?.querySelector('summary span')?.replaceChildren(document.createTextNode(rows.length+' 项'));renderList();scenePlayer?.refresh();}});
  });
}
function folderDescription(key){const folder=S.branchFolders[key];if(folder?.kind==='condition')return {key,folder,managed:true,parentTalkId:folder.parentTalkId,option:{content:'分支'+folder.branchId},talkIds:ids(folder.talkIds),references:[]};const [parent,option]=key.split(':').map(Number);return Branches.describe(S.doc,S.branchFolders,parent,option);}
function takeFolder(key){
  let d=folderDescription(key);if(d.folder)return d;
  Branches.initialContinuation(d.option);
  if(d.shared){const newId=nextId(S.doc.options,eventForTalk()*100+1);S.doc.options[newId]={...clone(d.option),id:newId};S.doc.talks[d.parentTalkId].option=ids(S.doc.talks[d.parentTalkId].option).map(id=>id===d.optionId?newId:id);d=Branches.describe(S.doc,S.branchFolders,d.parentTalkId,newId);}
  Branches.create(S.doc,S.branchFolders,d.parentTalkId,d.optionId);return folderDescription(d.key);
}
function addFolderTalk(key,duplicate=false,after=null,options={}){
  if(!editable())return;let d=folderDescription(key);if(!d.option)return;
  const original=duplicate?talk():null;
  mutate(options.cgId?'在选项对话夹添加 CG':options.blank?'在选项对话夹添加空白对话':duplicate?'在选项对话夹复制对话':'在选项对话夹添加对话',()=>{
    d=takeFolder(key);const folder=d.folder,id=newTalkId();
    const insertion=ids(folder.talkIds).includes(Number(after))?Number(after):null;
    const previous=S.doc.talks[insertion||ids(folder.talkIds).at(-1)]||S.doc.talks[d.parentTalkId];
    const row=duplicate&&original?normalizeTalk(clone(original)):continuationTalk(id,previous,stageAt(previous.id),options.blank);row.id=id;row.option=[];if(options.cgId){row.screenEffect=[4015,Number(options.cgId)];row.roleIds=[];row.roleName='';row.highlights=[];}
    Timeline.insert(S.doc,S.branchFolders,folder,row,insertion);
    const predecessor=insertion||folder.talkIds[folder.talkIds.indexOf(id)-1]||d.parentTalkId,index=S.order.indexOf(predecessor);S.order.splice(index+1,0,id);
    if(options.cgId)closeCGBeforeFollowing(row,folder);
    S.activeFolder=d.key;S.folderOpen[d.key]=true;folder.collapsed=false;S.selected=id;S.search='';$('#talk-search').value='';
  });
  setTimeout(()=>$('#scene-dialogue-content')?.focus(),0);
}
function continuationOptions(folder){
  const c=folder?.continuation||{kind:'end'},excluded=new Set([folder?.parentTalkId,...ids(folder?.talkIds)]);
  let result=folder?.kind==='condition'?`<option value="following" ${c.kind==='following'?'selected':''}>继续下面的对话</option>`:'';if(c.kind==='targets')result+='<option selected disabled>保留原有出口</option>';result+=`<option value="end" ${c.kind==='end'?'selected':''}>直接结束</option>`;
  const events=values(S.doc.events).filter(e=>ids(e.talkId).some(id=>S.doc.talks[id]&&!excluded.has(id)));
  result+='<optgroup label="接续后续剧情">'+events.map(e=>`<option ${StudentAgeRecordLabels.option(e.id)} value="event:${e.id}" ${c.kind==='event'&&Number(c.eventId)===Number(e.id)?'selected':''}>${h(e.title||'未命名剧情')}</option>`).join('')+'</optgroup>';
  result+='<optgroup label="接到指定对话">'+S.order.filter(id=>!excluded.has(id)&&!Timeline.internals(S.branchFolders).has(id)).map(id=>`<option ${StudentAgeRecordLabels.option(id)} value="talk:${id}" ${c.kind==='talk'&&Number(c.talkId)===id?'selected':''}>${h(talkLabel(id))}</option>`).join('')+'</optgroup>';return result;
}
function failureOptions(f,parent){
 const failure=f?.failureNext,hidden=Timeline.internals(S.branchFolders);let html=`<option value="auto" ${!Array.isArray(failure)?'selected':''}>继续判断后续分支 / 下面的对话</option>${f?.kind==='condition'?`<option value="end" ${Array.isArray(failure)&&!failure.length?'selected':''}>直接结束</option>`:''}`;
 html+=talkOptions(failure?.[0],parent,false,S.order.filter(id=>!hidden.has(id)));return html;
}
function setFolderFailure(key,value){
 if(!editable())return;
 mutate('设置分支判定失败去向',()=>{if(key.endsWith(':legacy')){const row=S.doc.talks[Number(key.split(':')[0])];if(value!=='auto'&&(!S.doc.talks[Number(value)]||Number(value)===row.id))throw Error('请选择有效的失败对话');row.nextTalk2=value==='auto'?[]:[Number(value)];}else{const f=S.branchFolders[key];Timeline.setFailure(S.doc,S.branchFolders,f,value==='auto'?null:value==='end'?[]:[Number(value)]);}S.folderOpen[key]=true;});
}
function setFolderContinuation(key,value){
  if(!editable())return;const [kind,id]=value.split(':'),continuation=kind==='talk'?{kind,talkId:Number(id)}:kind==='event'?{kind,eventId:Number(id)}:kind==='following'?{kind:'following'}:{kind:'end'};
  mutate('设置选项对话夹结束去向',()=>{const d=takeFolder(key);Timeline.setContinuation(S.doc,S.branchFolders,d.folder,continuation);S.activeFolder=d.key;S.folderOpen[d.key]=true;});
}
function toggleFolder(key){const d=key.endsWith(':legacy')?{}:folderDescription(key);S.folderOpen[key]=!(S.folderOpen[key]??!(d.folder?.collapsed??true));if(d.folder)d.folder.collapsed=!S.folderOpen[key];renderList();}
let pendingModalSave=null;
function modal(title,body,buttons) {
  const d=$('#modal');if(d.open)d.close();
  pendingModalSave=['事件设置','新建事件','导入对话'].includes(title)?buttons.find(b=>b.primary)?.run:null;
  $('#modal-content').innerHTML=`<div class="modal-header"><h2>${h(title)}</h2><button class="close-icon" id="modal-close" aria-label="关闭">×</button></div><div class="modal-body">${body}</div><div class="modal-footer">${buttons.map((b,i)=>`<button data-modal-button="${i}" class="${b.danger?'danger-button':b.primary?'primary':''}">${h(b.label)}</button>`).join('')}</div>`;
  $('#modal-close').onclick=closeModal;$$('[data-modal-button]',d).forEach(b=>b.onclick=async()=>{if(b.disabled)return;b.disabled=true;try{await buttons[Number(b.dataset.modalButton)].run();}catch(error){fail(error);}finally{if(b.isConnected)b.disabled=false;}});d.showModal();
}
function closeModal() {pendingModalSave=null;$('#modal').close();}
async function commitOpenEditor(){if($('#modal').open&&$('#dialogue-import-text')&&!$('#dialogue-import-text').value.trim()){closeModal();return;}if($('#modal').open&&pendingModalSave){const commit=pendingModalSave;await commit();if($('#modal').open)throw Error('当前编辑尚未保存，请检查填写内容。');}}
async function unsaved(next) {
  if(!S.dirty){await next();return;}
  modal('还有尚未保存的修改',`<p>当前模组 <strong>${h(S.project.name)}</strong> 的修改仍在工作台中。保存后再继续，或放弃这些修改。</p>`,[
    {label:'取消',run:closeModal},{label:'放弃修改',run:async()=>{closeModal();await next();}},
    {label:'保存并继续',primary:true,run:async()=>{if(await save()){closeModal();await next();}}}]);
}
async function refreshProjects(preferredId=null,lazy=false) {
  const data=await api('/api/projects');S.projects=(Array.isArray(data)?data:data.projects||[]).filter(isReadableProject);S.connected=true;
  const last=preferredId||localStorage.getItem('studentAgeStudio.project');if(last&&!availableProject(last))localStorage.removeItem('studentAgeStudio.project');
  if(S.project&&!availableProject(S.project.id)){
    if(S.dirty){renderProjects();renderChrome();toast('当前项目已不在模组列表中。未保存的草稿仍保留在窗口内，请处理草稿后再切换。','note');return;}
    scenePlayer?.dispose();scenePlayer=null;stageAudio?.stop();stopAudition();S.project=null;S.doc=null;S.selected=null;S.previewRole=null;S.revision=null;S.order=[];S.undo=[];S.redo=[];S.saved='';S.event='all';S.audios=[];S.defaultBgm=null;S.premises={};S.branchFolders={};S.folderOpen={};S.activeFolder=null;
  }
  renderProjects();renderChrome();
  if(!S.project&&S.projects.length){const id=availableProject(last)?last:S.projects[0].id;if(lazy){S.project=availableProject(id);S.deferredProject=true;renderProjects();renderChrome();}else await selectProjectHome(id);}
  else if(!S.projects.length)render();
}
function isLocalProject(project){return !!project&&String(project.id).startsWith('local:')&&!project.readOnly&&!project.readonly&&(!project.source||project.source==='local');}
function isReadableProject(project){return isLocalProject(project)||!!project&&String(project.id).startsWith('workshop:')&&project.source==='workshop'&&project.readOnly===true;}
function availableProject(id){return S.projects.find(project=>String(project.id)===String(id)&&isReadableProject(project));}
// Only mods sharing a name get their folder name appended; the option keeps the full path for the long-hover tip.
function projectLabel(p,list){const dup=list.filter(o=>String(o.name||'')===String(p.name||'')).length>1,folder=String(p.path||'').replace(/[\\/]+$/,'').split(/[\\/]/).pop();return String(p.name||'')+(dup&&folder?'（'+folder+'）':'');}
window.STUDIO_PROJECT_LABEL=projectLabel;
function renderProjects() {document.body.classList.toggle('original-edit-mode',!!window.STUDIO_ORIGINAL_MODE?.());$('#project-select').innerHTML=S.projects.map(p=>`<option value="${h(p.id)}" data-hover-tip="${h(p.path||'')}" ${S.project&&String(p.id)===String(S.project.id)?'selected':''}>${h(projectLabel(p,S.projects))}${p.readOnly?'（订阅）':''}</option>`).join('');}
async function loadProject(id,preserve=false) {
  if(!id)return false;if(S.project?.id!==id)window.STUDIO_ORIGINAL_SOURCE.set(null);if(!availableProject(id))throw Error('这个模组已不在列表中，请刷新模组列表。');const request=++projectLoadSequence,oldSelection=S.selected,oldEvent=S.event;let previous=null;
  projectBusy(true);projectFeedback('正在打开模组：'+availableProject(id).name+'…');
  try{
  if(!preserve&&(S.deferredProject||String(S.project?.id)!==String(id))&&isLocalProject(availableProject(id))&&!availableProject(id).originalMode){projectFeedback('正在备份模组：'+availableProject(id).name+'…');let backup;try{backup=await api('/api/backup',{projectId:id,kind:'automatic',requestId:crypto.randomUUID()});}catch(error){error.message='自动备份未完成：'+error.message;throw error;}if(backup.warning)toast(backup.warning,'note');if(request!==projectLoadSequence)return false;}
  const data=await api('/api/project?id='+encodeURIComponent(id)+'&talkStorage=indexed');await STUDIO_IDS.refresh(id);if(request!==projectLoadSequence)return false;previous={...S};
  if(!isReadableProject(data.project)||String(data.project.id)!==String(id))throw Error('读取的项目与当前选择不符，请重新打开。');
  if(S.project&&String(S.project.id)!==String(data.project.id)){scenePlayer?.dispose();scenePlayer=null;StudentAgeScene.portraitSizes.clear();portraitSizeRequests.clear();}S.project=data.project;S.deferredProject=false;S.referenceResolution=data.referenceResolution||[2560,1440];S.revision=data.revision;S.localIds=data.localIds||{};S.catalogAvailable=!!data.catalogAvailable;
  S.goalImageIds=data.goalImageIds||[];S.doc={protagonistGender:data.protagonistGender===2?2:1,eventGrades:data.eventGrades||{}};for(const k of MAPS)S.doc[k]=data[k]||{};if(data.indexedTalks)S.doc.talks=IndexedTalks.create(data.indexedTalks.rows);
  S.premises=clone(data.premises||{});S.branchFolders=clone(data.branchFolders||{});S.folderOpen={};S.activeFolder=null;S.doc.talkOwners=clone(data.talkOwners||{});StudentAgeEventOwnership.sync(S.doc,S.branchFolders);S.doc.audioCues=data.audioCues||{version:1,sfx:{},bgm:[]};S.bgmDraft=null;S.audios=[];S.defaultBgm=null;stageAudio?.stop();
  const computedOrder=initialOrder();const storedOrder=ids(data.order).filter(id=>S.doc.talks[id]);S.order=[...new Set([...storedOrder,...computedOrder])];S.event=preserve&&(oldEvent==='all'||S.doc.events[oldEvent])?oldEvent:(values(S.doc.events)[0]?.id || 'all');
  S.search='';$('#talk-search').value='';S.selected=preserve&&S.doc.talks[oldSelection]?oldSelection:(visibleIds()[0]||null);
  S.pinned={talks:new Set((data.pinnedIds?.talks||[]).map(Number)),options:new Set((data.pinnedIds?.options||[]).map(Number)),events:new Set((data.pinnedIds?.events||[]).map(Number))};S.catalogAll=Object.fromEntries(MAPS.map(k=>[k,new Set((data.catalogIds?.[k]||[]).map(String))]));
  S.catalogTalkIds=new Set(Object.keys(S.doc.talks).map(Number).filter(id=>!(S.localIds.talks||[]).map(Number).includes(id)));S.catalogIds=Object.fromEntries(MAPS.map(k=>{const local=new Set((S.localIds[k]||[]).map(String));return [k,new Set(Object.keys(S.doc[k]||{}).filter(id=>!local.has(String(id))))];}));S.idMappings={};S.deleted=[];S.replacements={};S.undo=[];S.redo=[];S.coalesce=null;S.saved=currentSignature();S.dirty=false;
  if(S.previewRole===null||!S.doc.persons[S.previewRole])S.previewRole=values(S.doc.persons).filter(p=>!S.goalImageIds?.includes(String(p.id)))[0]?.id??null;
  const t=talk();if(t&&ids(t.roleIds).length)S.previewRole=ids(t.roleIds)[0];syncFaceFromTalk();
  S.conditionTemplates=[];S.effectTemplates=[];S.conditionRefs={};S.conditionLocalIds={};S.conditionsLoading=true;
  localStorage.setItem('studentAgeStudio.project',String(id));renderProjects();render();if(data.warnings?.length||data.project?.warnings?.length)toast((data.warnings||data.project.warnings)[0],'note');
  projectBusy(false);$('#project-load-status')?.remove();
  loadConditionCatalog();
  loadAudioCatalog().catch(error=>{if(request===projectLoadSequence)toast(error.message,'note')});IndexedTalks.retain(S.doc.talks);window.dispatchEvent(new CustomEvent('studio-project-ready'));return true;
  }catch(error){error.projectId=id;if(request!==projectLoadSequence)return false;if(previous){Object.assign(S,previous);renderProjects();render();}projectBusy(false);projectFeedback('无法打开“'+(availableProject(id)?.name||id)+'”：'+(error.message||error),true,id);throw error;}
}
function newProject(copy=false,sourceId=null) {
  const source=availableProject(sourceId||S.project?.id);if(copy&&(!source||S.projectOpening))return;
  const title=copy?'创建副本':'新建模组';
  modal(title,`<p>${copy?'将复制剧情、配置与素材，保留其他编辑器的扩展数据。独立副本可单独编辑；原模组保持原样。':'填写模组名称。工作台会在游戏的本地模组目录中创建项目。'}</p><label class="field-label">模组名称</label><input id="project-name" maxlength="80" placeholder="例如：我的模组" value="${copy?h(source.name+' · 副本'):''}">`,[
    {label:'取消',run:closeModal},{label:copy?'创建副本':'创建模组',primary:true,run:async()=>{
      const name=$('#project-name').value.trim();if(!name){toast('给模组起一个名字。','note');return;}
      if(copy&&S.project?.id===source.id&&S.dirty&&!(await save()))return;
      const data=await api(copy?'/api/copy':'/api/create',copy?{projectId:source.id,name}:{name});closeModal();
      const id=data.project?.id||data.id||data.projectId;await refreshProjects(id);if(id)await selectProjectHome(id);window.dispatchEvent(new CustomEvent('studio-project-created'));toast(copy?'已创建独立副本，可以开始编辑。':'模组已创建。');if(data.warnings?.length)projectFeedback(data.warnings.join('；'),true);
    }}]);setTimeout(()=>$('#project-name')?.focus(),0);
}
function changedStoryPayload(mappings){
 if(mappings!==undefined)return {...changedStoryPayloadFrom(),...(Object.values(mappings||{}).some(m=>Object.keys(m).length)?{idMappings:mappings}:{})};
 return changedStoryPayloadFrom();
}
function changedStoryPayloadFrom(){
 const baseline=S.saved?IndexedTalks.parse(S.saved):[],before=baseline[0]||{};
 const payload={projectId:S.project.id,revision:S.revision};
 for(const [key,value] of Object.entries(S.doc)){
  const patch=key==='talks'?IndexedTalks.delta(value,before[key]):null;
  if(patch){if(Object.keys(patch.upsert).length||patch.deleted.length)payload.talkPatch=patch;}
  else if(JSON.stringify(value)!==JSON.stringify(before[key]))payload[key]=value;
 }
 const extras={deletedIds:[S.deleted,baseline[2]],replacements:[S.replacements,baseline[3]],order:[S.order,baseline[1]],branchFolders:[Object.fromEntries(Object.entries(S.branchFolders).map(([key,{collapsed,...folder}])=>[key,folder])),baseline[5]],premises:[S.premises,baseline[4]]};
 for(const [key,[value,old]] of Object.entries(extras))if(JSON.stringify(value)!==JSON.stringify(old))payload[key]=value;
 const pinnedNow=pinnedSnapshot();if(JSON.stringify(pinnedNow)!==JSON.stringify(baseline[6]||{talks:[],options:[],events:[]}))payload.pinnedIds=pinnedNow;
 if(Object.values(S.idMappings||{}).some(m=>Object.keys(m).length))payload.idMappings=S.idMappings;
 return payload;
}
async function save() {
  if(!editable()||S.saving)return false;document.activeElement?.blur?.();if(textDirtyTimer!==null)updateDirty();const invalid=document.querySelector('.effect-editor [data-effect-invalid]');if(invalid){for(let parent=invalid.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;toast('有效果参数尚未填好（'+invalid.dataset.effectInvalid+'），已按上一次有效值保存。','note');}if(!S.dirty)return true;
  StudentAgeEventBindings.syncSocialEffects(S.doc);for(const id of S.project.originalMode?[]:S.localIds.talks||[]){const t=S.doc.talks[id];if(t)StudentAgeScene.normalizeNativeMoves(t);}
  for(const id of Timeline.internals(S.branchFolders)){const t=S.doc.talks[id];if(!t)continue;if((t.content||'').trim()||t.roles?.length||t.option?.length||t.effect?.length||t.screenEffect?.length){t.content='';t.roles=[];t.option=[];t.effect=[];t.screenEffect=[];}}S.saving=true;renderChrome();const submittedSignature=currentSignature();
  const sentMappings=S.idMappings;S.idMappings={};
  try{const data=await api('/api/save',changedStoryPayload.call(null,sentMappings));S.revision=data.revision??S.revision;const inverse=Object.fromEntries(Object.entries(sentMappings||{}).map(([t,m])=>[t,Object.fromEntries(Object.entries(m).map(([a,b])=>[b,Number(a)]))]));for(const entry of [...S.undo,...S.redo])entry.idMappings=composeMappings(inverse,entry.idMappings||{});const unchanged=currentSignature()===submittedSignature;if(data.branchFolders&&unchanged)S.branchFolders=clone(data.branchFolders);if(data.premises&&unchanged)S.premises=clone(data.premises);S.saved=unchanged?currentSignature():submittedSignature;S.dirty=currentSignature()!==S.saved;if(data.warnings?.length)toast('已保存。'+data.warnings.join(' '),'note');else toast(S.dirty?'已保存此前的修改，继续编辑的内容仍待保存。':'模组已保存，修改前的文件已备份。');return !S.dirty;}
  catch(error){S.idMappings=composeMappings(sentMappings,S.idMappings);fail(error);throw error;}finally{S.saving=false;renderChrome();scheduleRenumber();}
}
function unassignedTalkIds() {
  const owned=new Set(graphOrder(values(S.doc?.events).flatMap(e=>ids(e.talkId))));
  const idle=S.doc?StudentAgeEventOwnership.interactionTalks(S.doc):new Set();return S.order.filter(id=>!owned.has(id)&&!idle.has(id)&&S.doc?.talks[id]);
}
function phoneEvent(){const e=S.doc?.events[S.event];return e&&[70,71].includes(Number(e.type))?e:null;}
function phoneHome(id){
 const name=S.doc?.persons[id]?.name||'';
 return Number(values(S.doc?.backgrounds).find(r=>name&&String(r.name||'').includes(name)&&/家|卧室/.test(r.name))?.id)||100;
}
const phoneFixedActions=new Set();
function configurePhone(e,caller=Number(e.npc)||0,bg=e.studioPhoneBackground||phoneHome(caller)){
 e.npc=caller;e.studioPhoneBackground=bg;
 const entry=S.doc.talks[ids(e.talkId)[0]];if(!entry)return;
 // Configure only the entry. Never erase subsequent speakers, actions, backgrounds or hang-ups.
 if(!entry.bg)entry.bg=S.doc.backgrounds[201011]?201011:100;
 entry.roles||=[];
 if(!entry.roles.some(r=>Number(r[0])===0&&[1001,1002,1003].includes(Number(r[1]))))entry.roles.unshift([0,1002,1,2,0]);
 entry.screenEffect=[4007,bg,...(caller>0?[caller]:[])];
 if(!ids(entry.roleIds).length)entry.roleIds=[0];

}
function editPaper(){
 if(!editable()||!talk())return;
 const row=talk(),project=S.project.id,action=(row.roles||[]).find(r=>Number(r[1])===5001),oldId=Number(action?.[2])||0;
 const old=S.doc.papers?.[oldId]||{},initial=oldId||STUDIO_IDS.allocate('PaperCfg',S.doc.papers||{});
 modal(oldId?'编辑纸条':'添加纸条',`<label class="field-label">纸条编号</label><input id="paper-id" type="number" min="1" max="2147483647" value="${initial}"><p id="paper-id-warning" class="error" role="status"></p><label class="field-label">纸条文本</label><textarea id="paper-content" rows="8">${h(old.content||'')}</textarea><div class="field-grid"><label><span class="field-label">落款</span><input id="paper-name" value="${h(old.name||'')}"></label><label><span class="field-label">纸张大小</span><input id="paper-scale" type="number" min="1" max="2.3" step="0.1" value="${Math.max(1,Number(old.scale)||1)}"></label><label><span class="field-label">原版笔迹</span><select id="paper-type"><option value="0">手写体</option><option value="1">书信体</option></select></label><label><span class="field-label">文字对齐</span><select id="paper-align"><option value="1">左对齐</option><option value="0">居中</option></select></label></div>`,[
 {label:'取消',run:closeModal},...(oldId?[{label:'从本句移除',danger:true,run:()=>{closeModal();mutate('移除纸条',()=>row.roles=row.roles.filter(r=>Number(r[1])!==5001));}}]:[]),{label:'应用',primary:true,run:()=>{
   const id=Number($('#paper-id').value),content=$('#paper-content').value,name=$('#paper-name').value,type=Number($('#paper-type').value),alignment=Number($('#paper-align').value),scale=Number($('#paper-scale').value);
   if(!Number.isInteger(id)||id<1||id>2147483647)throw Error('纸条编号应为 1 至 2147483647 的整数。');if(Math.fround(id)!==id)throw Error('该纸条编号无法由游戏动作精确保存，请使用 16777216 以内的编号或重新生成。');if(!content.trim())throw Error('请输入纸条文本。');if(!Number.isFinite(scale)||scale<1||scale>2.3)throw Error('纸张大小应为 1 至 2.3。');if(project!==S.project.id||S.doc.talks[row.id]!==row)throw Error('当前对话已变化，请重新添加。');
   closeModal();mutate('设置纸条',()=>{S.doc.papers||={};S.doc.papers[id]={...old,id,content,name,type,alignment,scale};row.roles=(row.roles||[]).filter(r=>Number(r[1])!==5001);row.roles.push([0,5001,id]);largeScene.paperClosed=null;largeScene.paperSignature=null;});
 }}]);$('#paper-type').value=Number(old.type)||0;$('#paper-align').value=oldId?Number(old.alignment)||0:1;
 let paperCheck=0,timer;$('#paper-id').oninput=()=>{const input=$('#paper-id'),warning=$('#paper-id-warning'),id=Number(input.value),seq=++paperCheck;clearTimeout(timer);warning.textContent=id!==oldId&&S.doc.papers?.[id]?'该编号已有纸条，应用后会更新使用此编号的纸条。':'';if(!Number.isInteger(id)||id<1)return;timer=setTimeout(async()=>{try{const result=await api('/api/ids/check',{projectId:S.project.id,table:'PaperCfg',oldId:oldId||initial,newId:id});if(seq!==paperCheck||!warning.isConnected)return;const names=[...new Set((result.conflicts||[]).map(c=>c.name))];if(names.length)warning.textContent='该 ID 已被'+names.map(n=>'「'+n+'」').join('、')+'占用，仍可使用。';}catch{/* Keep local validation available when the registry is refreshing. */}},200);};

}
function createEvent(options={}) {
  if(!editable())return;
  eventDetails(null,{type:Number.isInteger(options.type)?options.type:1});
}
function eventDetails(id=S.event,creation=null) {
  const e=creation?{id:nextId(S.doc.events,1000000),title:"",type:creation.type,talkId:creation.entry?[creation.entry]:[],rate:1,maxcount:1,effect:[],condition:[]}:S.doc?.events[id];if(!e){toast('先选择一个具体事件。','note');return;}
  const readOnly=!!S.project.readOnly;let conditions=clone(e.condition||[]),effects=clone(e.effect||[]),phoneChange=null;
  const eventTalkIds=new Set(graphOrder(ids(e.talkId))),initialBindings={actions:[...values(S.doc.actionEvents).filter(r=>ids(r.evts).includes(Number(e.id))).map(r=>({id:Number(r.id),rate:r.rate??1,mode:'pool'})),...values(S.doc.actions).filter(r=>Number(r.evtId)===Number(e.id)).map(r=>({id:Number(r.id),mode:'direct',rate:1}))],interactions:values(S.doc.interactions).filter(r=>eventTalkIds.has(Number(r.talkId))).map(clone)};
  initialBindings.gifts=StudentAgeEventBindings.giftsForEvent(S.doc,e);
  if(e.studioSocial)initialBindings.social=StudentAgeEventBindings.socialDraft(e);
  let bindings=clone(initialBindings),bindingsChanged=false,socialApplied=clone(e.studioSocial||{});
  const referenceOptions=(table,selected,empty)=>{const rows={...(table==='EvtTypeCfg'?window.StudentAgeEventTypes:{}),...S.conditionRefs[table]};let out=`<option value="0" ${Number(selected||0)===0?'selected':''}>${h(empty)}</option>`;for(const row of values(rows))if(Number(row.id)!==0)out+=`<option ${StudentAgeRecordLabels.option(row.id)} value="${row.id}" ${Number(row.id)===Number(selected)?'selected':''}>${h(row.name||row.title||row.desc||'未命名')}</option>`;if(selected&&!rows[selected])out+=`<option value="${selected}" selected>保留原有设置</option>`;return out;};
  modal(creation?'创建事件':readOnly?'事件信息':'事件设置',`<fieldset ${readOnly?'disabled':''} class="event-settings-fields"><div class="field-grid event-name-grid"><label><span class="field-label">事件名称</span><input id="event-title" value="${h(e.title||'')}"></label><label><span class="field-label">事件 ID</span><input id="event-id" type="number" min="1" max="2147483647" step="1" value="${h(e.id)}" ${!creation&&(S.catalogIds?.events?.has(String(e.id))||S.project?.originalMode)?'disabled title="原版事件的编号不能修改"':''}><small class="helper">1–2147483647 之间的任意整数均可；对话编号随之变为 事件号×1000+序号；与原版或本模组其他事件重复时不会拒绝，只在事件卡上标出。</small></label></div><div class="field-grid"><label><span class="field-label">事件类型</span><button id="event-type" value="${Number(e.type)||0}">${h(StudentAgeCharacterUI.eventName(StudentAgeEventBindings.displayType(e),S.conditionRefs.EvtTypeCfg))} ▾</button></label><label><span class="field-label">发生地点</span><select id="event-map">${referenceOptions('MapCfg',e.mapId,'不限地点')}</select></label></div><p id="event-type-note" class="event-type-note">${h(StudentAgeCharacterUI.eventDescription(e.type||0))}</p><input id="event-npc" type="hidden" value="${Number(e.npc)||0}"><div id="event-parameters" class="field-grid"></div><div class="field-grid"><label><span class="field-label">触发概率（%）</span><input id="event-rate" type="number" min="0" max="100" step="any" value="${h((e.rate??1)*100)}"></label><label><span class="field-label">最多发生次数</span><input id="event-maxcount" type="number" step="1" value="${h(e.maxcount??1)}"></label></div><label class="field-label">从哪句开始</label><select id="event-first">${talkOptions(ids(e.talkId)[0]||0).replace('结束这段对话','尚未添加对话')}</select>${ids(e.talkId).length>1?`<label class="field-label">女主角从哪句开始</label><select id="event-first-female">${talkOptions(ids(e.talkId)[1]||0)}</select><p class="helper">第一项为男主角入口；保留原有其他入口。</p>`:''}</fieldset><h3 class="event-condition-title">事件触发条件</h3><div id="event-conditions"></div><h3 class="event-condition-title">事件效果</h3><div id="event-effects"></div>`,readOnly?[{label:'关闭',run:closeModal}]:[{label:'取消',run:closeModal},{label:creation?'创建':'应用',primary:true,run:async()=>{
    const title=$('#event-title').value.trim(),first=Number($('#event-first').value),type=Number($('#event-type').value),npc=Number($('#event-npc').value),mapId=Number($('#event-map').value),rate=Number($('#event-rate').value)/100,maxcount=Number($('#event-maxcount').value),female=$('#event-first-female')?Number($('#event-first-female').value):null;
    const invalid=$('#event-effects [data-effect-invalid]');if(invalid){invalid.focus();throw Error(invalid.dataset.effectInvalid||'请检查事件效果。');}if(!title)throw Error('请填写事件名称。');if(!Number.isFinite(rate)||rate<0||rate>1||!Number.isInteger(maxcount))throw Error('概率应为 0 到 100，发生次数应为整数。');
    const wantedId=Number($('#event-id').value);if(!Number.isInteger(wantedId)||wantedId<=0||wantedId>2147483647)throw Error('事件 ID 应为 1 到 2147483647 之间的整数。');if(creation&&S.doc.events[wantedId]&&(S.localIds.events||[]).map(Number).includes(wantedId)){const moved=nextId(S.doc.events,1000000);await renameEvent(wantedId,moved);toast('本模组原有事件 '+wantedId+' 已改为 '+moved+'，新事件使用 '+wantedId+'。','note');}
    if(creation)e.id=wantedId;
    if(!creation&&S.doc.events[id]!==e)throw Error('事件已变化，请重新打开设置。');
    if(creation?.entry&&!new Set(unassignedTalkIds()).has(creation.entry))throw Error('这句对话已归属其他事件，请重新选择。');
    if(bindingsChanged&&!bindings.social&&type===4&&bindings.actions.some(r=>r.mode==='direct'&&Number((S.doc.actions[r.id]||S.conditionRefs.ActionCfg?.[r.id])?.evtId)>0&&Number((S.doc.actions[r.id]||S.conditionRefs.ActionCfg[r.id]).evtId)!==Number(e.id)))throw Error('所选行动已有固定剧情，请选择随机剧情池，或先调整原来的固定剧情。');
    if(bindingsChanged&&!bindings.social&&[2,21,22,522].includes(type)&&bindings.interactions.some(r=>!String(r.text||'').trim()))throw Error('请填写社交互动的进度条文字。');
    const gifts=type===110?(bindings.gifts||[]):[];
    if(type===110&&(!gifts.length||gifts.some(r=>!Number.isInteger(r.npc)||r.npc<=0||!Number.isInteger(r.item)||r.item<=0)))throw Error('请在事件类型中选择收礼人和礼物物品。');
    const phoneBg=Number($('#event-phone-bg')?.value)||phoneChange?.bg||e.studioPhoneBackground||phoneHome(npc);
    if(bindings.social)StudentAgeEventBindings.validateSocial(S.doc,{...e,npc,maxcount,talkId:first?[first]:[]},bindings,S.conditionRefs);
    closeModal();mutate(creation?'创建事件':'修改事件与触发条件',()=>{
      const wasPhone=[70,71].includes(Number(e.type)),oldCaller=Number(e.npc)||0;
      Object.assign(e,{title,type,npc,mapId,rate,maxcount,condition:conditions,effect:effects});
      if(wasPhone&&![70,71].includes(type)){for(const tid of graphOrder(ids(e.talkId))){const row=S.doc.talks[tid];if(Number(row.screenEffect?.[0])===4007){row.bg=e.studioPhoneBackground||100;row.screenEffect=[];if(oldCaller>0)row.roles.push([oldCaller,1002,1,1,0]);}else if(Number(row.screenEffect?.[0])===4008)row.screenEffect=[];}delete e.studioPhoneBackground;}
      if(female!==null){e.talkId=ids(e.talkId);e.talkId[0]=first;e.talkId[1]=female;}else if(first!==(ids(e.talkId)[0]||0))e.talkId=first?[first]:[];
      if(creation){S.doc.events[e.id]=e;S.event=e.id;S.selected=null;S.activeFolder=null;if(!(S.localIds.events||[]).map(Number).includes(Number(e.id)))(S.localIds.events??=[]).push(Number(e.id));}
      if(!creation&&wantedId!==Number(e.id))setTimeout(()=>renameEvent(Number(e.id),wantedId).catch(fail),0);
      if(bindingsChanged){
        const selectedActions=type===4&&!bindings.social?bindings.actions:[];
        for(const before of initialBindings.actions){if(before.mode==='direct'){if(Number(S.doc.actions[before.id]?.evtId)===Number(e.id))S.doc.actions[before.id].evtId=0;}else if(S.doc.actionEvents[before.id])S.doc.actionEvents[before.id].evts=ids(S.doc.actionEvents[before.id].evts).filter(id=>id!==Number(e.id));}
        for(const binding of selectedActions){if(binding.mode==='direct'){S.doc.actions[binding.id]={...clone(S.doc.actions[binding.id]||S.conditionRefs.ActionCfg[binding.id]),evtId:e.id};}else{const row=S.doc.actionEvents[binding.id]||clone(S.conditionRefs.ActionEvtCfg?.[binding.id]||{id:binding.id,evts:[],rate:1});row.evts=[...new Set([...ids(row.evts),e.id])];row.rate=binding.rate;S.doc.actionEvents[binding.id]=row;}}
        const interactions=!bindings.social&&[2,21,22,522].includes(type)?bindings.interactions:[];
        for(const row of initialBindings.interactions)if(!interactions.some(r=>r.id===row.id))delete S.doc.interactions[row.id];
        if(interactions.some(r=>!r.talkId)&&!ids(e.talkId)[0]){const tid=STUDIO_IDS.allocate('TalkCfg',S.doc.talks,e.id);S.doc.talks[tid]=normalizeTalk({id:tid,content:'',bg:0,roleIds:[]});e.talkId=[tid];S.order.push(tid);}
        for(const row of interactions)S.doc.interactions[row.id]={...clone(row),npc,name:row.name||title,talkId:row.talkId||ids(e.talkId)[0]};
      }
      if(gifts.length&&!ids(e.talkId)[0]){const tid=STUDIO_IDS.allocate('TalkCfg',S.doc.talks,e.id);S.doc.talks[tid]=normalizeTalk({id:tid,content:'',bg:0,roleIds:[]});e.talkId=[tid];S.order.push(tid);}
      if(gifts.length||initialBindings.gifts.length)StudentAgeEventBindings.applyGifts(S.doc,e,initialBindings.gifts,gifts,rows=>STUDIO_IDS.allocate('GiftEvtCfg',rows));
      if(bindings.social?.kind==='minigame'&&!e.talkId?.[0]){const tid=STUDIO_IDS.allocate('TalkCfg',S.doc.talks,e.id);S.doc.talks[tid]=normalizeTalk({id:tid,content:'',bg:0,roleIds:[]});e.talkId=[tid];S.order.push(tid);}
      e.studioSocial={...(e.studioSocial||{}),conditions:socialApplied.conditions||[],effects:socialApplied.effects||[]};
      StudentAgeEventBindings.applySocial(S.doc,e,bindings,S.conditionRefs,(table,rows)=>STUDIO_IDS.allocate(table,rows));
      if([70,71].includes(type)){e.studioPhoneBackground=phoneBg;configurePhone(e,npc,phoneBg);}
    });window.STUDIO_EVENTS?.refresh();
  }}]);
  function parameters(){
    const type=Number($('#event-type').value),spec=StudentAgeCharacterUI.eventParameter(type),npc=Number($('#event-npc').value),phone=[70,71].includes(type),root=$('#event-parameters');
    $('#event-map').closest('label').hidden=type===37;
    const firstChat=bindings.social?.kind==='talk';$('#event-maxcount').closest('label').hidden=firstChat;if(firstChat)$('#event-maxcount').value=1;
    root.innerHTML=(spec?`<label><span class="field-label">${h(spec[1])}</span><button id="event-parameter-person">${h((spec[0]==='PersonCfg'?S.doc.persons[npc]?.name:S.conditionRefs[spec[0]]?.[npc]?.name)||'未设置')} ▾</button></label>`:'')+(type===37?`<label><span class="field-label">结算阶段</span><select id="event-phase"><option value="1">所有按钮完成后</option><option value="2">每日结算时</option></select></label>`:'')+(phone?`<label><span class="field-label">通话对象的场景</span><select id="event-phone-bg" data-reference-table="BgCfg">${values(S.doc.backgrounds).map(r=>`<option value="${r.id}">${h(r.name||r.id)}</option>`).join('')}</select></label>`:'');
    if(phone)$('#event-phone-bg').value=phoneChange?.bg||e.studioPhoneBackground||phoneHome(npc);
    if(type===37){$('#event-phase').value=Number($('#event-map').value)||1;$('#event-phase').onchange=()=>{const map=$('#event-map'),value=$('#event-phase').value;if(![...map.options].some(o=>o.value===value))map.add(new Option('结算阶段 '+value,value));map.value=value;};}
    $('#event-parameter-person')?.addEventListener('click',async()=>{
      const rows=spec[0]==='PersonCfg'?values(S.doc.persons).filter(p=>!S.goalImageIds?.includes(String(p.id))):values((await StudentAgeCharacterUI.api('table?projectId='+encodeURIComponent(S.project.id)+'&name='+encodeURIComponent(spec[0]))).rows);
      const selected=await StudentAgeCharacterUI.choices(spec[1],rows.filter(r=>!phone||Number(r.id)!==0),{selected:npc,table:spec[0],projectId:S.project.id});
      if(selected&&root.isConnected){$('#event-npc').value=selected.id;if(phone)phoneChange={bg:phoneHome(selected.id)};parameters();}
    });
  }
  $('#event-type').onclick=async()=>{await Promise.all(['PersonGrowCfg','MinigameActionCfg'].map(async name=>{if(!S.conditionRefs[name])S.conditionRefs[name]=(await api('/api/table?'+new URLSearchParams({projectId:S.project.id,name}))).rows;}));const button=$('#event-type'),picked=await StudentAgeCharacterUI.eventType(S.project.id,(bindings.social?.kind==='talk'?-2:bindings.social?.kind==='minigame'?-24:Number(button.value)),{event:{...clone(e),studioSocial:socialApplied,title:$('#event-title').value,maxcount:Number($('#event-maxcount').value),condition:conditions,effect:effects},npc:Number($('#event-npc').value),mapId:Number($('#event-map').value),bindings,persons:S.doc.persons,actions:{...S.conditionRefs.ActionCfg,...S.doc.actions},actionEvents:{...S.conditionRefs.ActionEvtCfg,...S.doc.actionEvents},interactions:{...S.conditionRefs.InteractCfg,...S.doc.interactions},talks:S.doc.talks,eventTalks:Object.fromEntries([...eventTalkIds].map(id=>[id,S.doc.talks[id]])),refs:S.conditionRefs,localIds:S.conditionLocalIds,conditionTemplates:allConditionTemplates(),effectTemplates:S.effectTemplates,getPremises:()=>S.premises});if(picked&&button.isConnected){bindings=picked.bindings||bindings;bindingsChanged=true;button.value=picked.id;button.textContent=picked.name+' ▾';$('#event-npc').value=picked.npc;const map=$('#event-map');if(![...map.options].some(o=>Number(o.value)===picked.mapId))map.add(new Option('参数 '+picked.mapId,picked.mapId));map.value=picked.mapId;$('#event-type-note').textContent=StudentAgeCharacterUI.eventDescription(picked.social?.kind==='talk'?-2:picked.id);if(picked.social){const r=picked.social;const max=r.kind==='talk'?1:r.kind==='topic'?(r.repeat?2147483647:1):r.maxcount;$('#event-maxcount').value=max;if(r.kind==='topic')$('#event-title').value=r.title;const out=StudentAgeEventBindings.socialCommands({...e,studioSocial:socialApplied,condition:conditions,effect:effects},r,picked.npc);conditions=out.condition;effects=out.effect;socialApplied=out.studioSocial;mountCommands();}else{const out=StudentAgeEventBindings.socialCommands({...e,studioSocial:socialApplied,condition:conditions,effect:effects},{},picked.npc);conditions=out.condition;effects=out.effect;socialApplied={};mountCommands();}parameters();}};
  parameters();if(creation)setTimeout(()=>$('#event-title')?.focus(),0);
  const refs={...S.conditionRefs,EvtCfg:{...S.conditionRefs.EvtCfg,...S.doc.events},OptionCfg:{...S.conditionRefs.OptionCfg,...S.doc.options}};
  function mountCommands(){Conditions.mount($('#event-conditions'),{rows:conditions,templates:allConditionTemplates(),refs,localIds:S.conditionLocalIds,readOnly:readOnly||S.conditionsLoading,emptyText:'空列表是否触发由事件类型决定。',description:S.conditionsLoading?'正在读取条件目录，请稍后重新打开设置。':'条件满足时，还会检查事件类型和触发次数。',onChange:rows=>conditions=rows});
  Effects.mount($('#event-effects'),{rows:effects,templates:S.effectTemplates,refs,getPremises:()=>S.premises,readOnly:readOnly||S.conditionsLoading,onError:fail,onChange:rows=>effects=rows});
  }mountCommands();
}
function currentEventGrade(){return eventGradeOverrides.get(S.project?.id+':'+S.event)??S.doc?.eventGrades?.[S.event]??0;}
function setEventGrade(value){
 value=Number(value);if(![0,1].includes(value)||!S.doc)return;
 stopLinePlayback(false);scenePlayer?.pause();
 if(S.project?.readOnly){eventGradeOverrides.set(S.project.id+':'+S.event,value);S.grade=value;invalidateStageMemo();render();}
 else mutate('设置整个事件的学段',()=>{S.doc.eventGrades||={};S.doc.eventGrades[S.event]=value;S.grade=value;});
 scenePlayer?.select(S.selected);prepareSceneExpressions(currentStage());
}
function enterEvent(id) {
  if(!S.doc?.events[id])throw Error('事件已不存在，请返回事件列表刷新。');
  scenePlayer?.dispose();scenePlayer=null;stageAudio?.stop();S.event=Number(id);S.selected=null;S.activeFolder=null;S.search='';S.listStart=0;S.listAnchor=null;S.coalesce=null;$('#talk-search').value='';
  S.selected=visibleIds()[0]||null;sceneMode='edit';syncFaceFromTalk();render();$('#editor-scroll').scrollTo({top:0});return true;
}
function deleteEvents(eventIds) {
 if(!editable())return false;const selected=eventIds.map(Number).filter(id=>S.doc.events[id]);if(!selected.length)return false;
 StudentAgeEventOwnership.sync(S.doc,S.branchFolders);
 const local=Object.keys(S.doc.talks).map(Number).filter(id=>!(S.catalogTalkIds||new Set()).has(id));
 const {talks:owned,options:ownOptions}=StudentAgeEventOwnership.plan(S.doc,S.branchFolders,selected,local);
 const references=[];for(const o of values(S.doc.options))if(!ownOptions.has(Number(o.id))&&selected.includes(Number(o.nextEvtId)))references.push(o.content||'选项');
 for(const f of values(S.branchFolders))if(!owned.has(Number(f.parentTalkId))&&f.continuation?.kind==='event'&&selected.includes(Number(f.continuation.eventId)))references.push('对话夹');
 // Deleting is never refused: dangling jumps are reported so they can be adjusted afterwards.
 if(references.length)toast('已删除的事件仍被引用：'+[...new Set(references)].join('、')+'。这些跳转现在指向不存在的事件，请自行调整。','note');
 mutate('删除事件与全部所属对话',()=>{
  removePremises(Object.keys(S.premises).filter(k=>selected.includes(Number(S.premises[k].eventId))));for(const id of selected){StudentAgeEventBindings.clearSocialBindings(S.doc,S.doc.events[id]);delete S.doc.events[id];delete S.doc.eventGrades?.[id];}
  for(const row of values(S.doc.actionEvents))row.evts=ids(row.evts).filter(value=>!selected.includes(value));for(const row of values(S.doc.actions))if(selected.includes(Number(row.evtId)))row.evtId=0;for(const row of values(S.doc.interactions))if(owned.has(Number(row.talkId)))delete S.doc.interactions[row.id];
  for(const tid of owned){delete S.doc.talks[tid];delete S.doc.talkOwners[tid];S.deleted.push(tid);S.replacements[tid]=[];replaceEdges(tid,[]);delete S.doc.audioCues.sfx[tid];if(S.doc.audioCues.nativeAudio)delete S.doc.audioCues.nativeAudio[tid];}
  for(const oid of ownOptions)delete S.doc.options[oid];
  for(const row of values(S.doc.talks))row.option=ids(row.option).filter(o=>!ownOptions.has(o));for(const row of values(S.doc.events))if(row.options)row.options=ids(row.options).filter(o=>!ownOptions.has(o));
  S.order=S.order.filter(t=>!owned.has(t));S.branchFolders=Branches.cleanup(S.doc,S.branchFolders,S.replacements);S.doc.audioCues.bgm=S.doc.audioCues.bgm.map(g=>({...g,talkIds:ids(g.talkIds).filter(t=>!owned.has(t))})).filter(g=>g.talkIds.length);
  if(selected.includes(Number(S.event))){S.event=values(S.doc.events)[0]?.id||'all';S.selected=null;S.activeFolder=null;}
 });window.STUDIO_EVENTS?.refresh();return true;
}
function deleteEvent(id){return deleteEvents([id]);}
function cycleSpeaker() {
  if(!talk()||!editable()||sceneMode!=='edit')return;
  const choices=['narrator',...presentRoles().map(person=>String(person.id))],speaking=ids(talk().roleIds).filter(id=>id>=0),current=speaking.length===1?String(speaking[0]):'narrator';
  if(choices.length===1){if(speaking.length||talk().roleName)setSpeaker('narrator');return;}
  const index=choices.indexOf(current);setSpeaker(choices[(Math.max(-1,index)+1)%choices.length]);
}

function setSpeaker(value) {
  return mutate('设置说话人物',()=>{const t=talk();t.roleIds=value==='narrator'?[]:[Number(value)];t.roleName='';if(value!=='narrator')S.previewRole=Number(value);});
}

function personOptions(selected,narrator=false) {
  let out=narrator?`<option value="narrator" ${selected==='narrator'?'selected':''}>旁白</option>`:'';
  const cast=presentRoles();
  if(selected!==null&&selected!=='narrator'&&!cast.some(p=>String(p.id)===String(selected)))out+=`<option value="" selected disabled>${h(personName(selected))}（未在场）</option>`;
  for(const p of cast)out+=`<option ${StudentAgeRecordLabels.option(p.id)} value="${p.id}" ${String(selected)===String(p.id)?'selected':''}>${h(personName(p.id))}</option>`;
  return out || '<option value="">先让人物登场</option>';
}
function talkOptions(selected=0,exclude=null,withEnd=true,restricted=null) {
  let out=withEnd?`<option value="0" ${!selected?'selected':''}>结束这段对话</option>`:'';
  const hidden=Timeline.internals(S.branchFolders),list=S.project?.readOnly?(selected?[Number(selected)]:[]):restricted||S.order;
  for(const id of list){if(Number(id)===Number(exclude)||(!restricted&&!S.doc.talks[id])||(hidden.has(Number(id))&&Number(id)!==Number(selected)))continue;out+=`<option ${StudentAgeRecordLabels.option(id)} value="${id}" ${Number(selected)===Number(id)?'selected':''}>${h(talkLabel(id))}</option>`;}
  if(selected&&!list.includes(Number(selected)))out+=`<option ${StudentAgeRecordLabels.option(selected)} value="${selected}" selected>${h(talkLabel(selected))}</option>`;return out;
}
function targetSelect(row,field,attributes,exclude=null){
  const targets=ids(row[field]),options=value=>{let html=talkOptions(value,exclude);if(field==='nextTalk2')html=html.replace('结束这段对话','沿用普通出口');else if(field==='talkId2'&&row.nextEvtId)html=html.replace('结束这段对话','接续本选项设置的事件');return html;};if(targets.length<2)return `<select ${attributes}>${options(targets[0]||0)}</select>`;
  return `<div class="target-genders">${[0,1].map(index=>`<label><span>${index===0?'男主角去向':'女主角去向'}</span><select ${attributes} data-target-sex="${index}">${options(targets[index]||0)}</select></label>`).join('')}</div>`;
}
function renderChrome() {
  const available=!!availableProject(S.project?.id),writable=available&&isLocalProject(S.project);
  $('#undo').disabled=!S.undo.length;$('#redo').disabled=!S.redo.length;$('#copy-project').disabled=!available;
  $('#save').disabled=!writable||!S.dirty||S.saving;$('#save span').textContent=S.saving?'正在保存…':'保存模组';
  $('#footer-status').textContent=S.connected?(S.project?(S.dirty?'修改保留在工作台 · 记得保存':(S.project?.readOnly?'正在查看订阅模组':'已连接本地模组目录')):'本地服务已连接'):'正在连接本地工作台…';
  $('#connection-dot').classList.toggle('offline',!S.connected);$('#project-path').textContent=S.project?.path||'文件保存在你的电脑上';
  if($('#preview-history-count'))$('#preview-history-count').textContent=S.project?'已预演 '+previewHistory().count()+' 句':'尚无预演记录';
}
function render() {
  S.grade=currentEventGrade();renderChrome();renderEvents();renderList();renderEditor();renderPreview();window.STUDIO_EVENTS?.refresh();
}
function renderEvents() {
  $('#event-select').innerHTML='<option value="all" disabled>请从事件列表选择事件</option>'+values(S.doc?.events).map(e=>`<option ${StudentAgeRecordLabels.option(e.id)} value="${e.id}" ${String(e.id)===String(S.event)?'selected':''}>${h(e.title||'未命名事件')}</option>`).join('');
  if(S.event==='all')$('#event-select').value='all';
}
function renderList() {
  if(!S.doc){$('#talk-list').innerHTML='<div class="small-empty">请打开或新建模组。</div>';return;}
  const visible=visibleIds(),allowed=new Set(visible),owners=new Map();for(const [key,f]of Object.entries(S.branchFolders))for(const id of ids(f.talkIds))owners.set(id,key);
  if(S.search){for(const start of visible){let id=start;const seen=new Set();while(owners.has(id)&&!seen.has(id)){seen.add(id);const f=S.branchFolders[owners.get(id)];allowed.add(f.parentTalkId);S.folderOpen[owners.get(id)]=true;id=f.parentTalkId;}}}
  $('#talk-count').textContent=visible.length+' 句对话';const rendered=new Set();let renderedIndex=0;
  function card(id,depth=0){if(!S.doc.talks[id]||rendered.has(id)||!allowed.has(id))return '';rendered.add(id);const t=S.doc.talks[id],restoreScene=Number(t.screenEffect?.[0])===4017&&!String(t.content||'').trim(),name=restoreScene?'恢复场景':Number(t.screenEffect?.[0])===4015?'CG · '+assetName(S.doc.cgs[t.screenEffect[1]]||{name:'插画'},'cg'):speaker(t),index=renderedIndex++;
    const descriptions=ids(t.option).map(oid=>Branches.describe(S.doc,S.branchFolders,id,oid));
    descriptions.push(...Timeline.entries(S.branchFolders,id).map(([key])=>folderDescription(key)));
    if(t.check?.length&&!Timeline.entries(S.branchFolders,id).length)descriptions.push({key:id+':legacy',legacy:true,parentTalkId:id,option:{content:'分支1'},talkIds:[],references:[...new Set([...ids(t.nextTalk),...ids(t.nextTalk2)])]});
    const folders=descriptions.map(d=>renderFolder(d,depth,card)).join('');const personId=ids(t.roleIds).find(id=>id>=0),person=S.doc.persons[personId],gender=personId===0?S.doc.protagonistGender:Number(person?.gender),avatar=personId!==undefined?`<img loading="lazy" alt="${h(name)}" src="/api/talk-head?${new URLSearchParams({projectId:S.project.id,roleId:personId,grade:currentEventGrade()+1,gender:S.doc.protagonistGender,token})}">`:h(name.slice(0,1));
    return `<div class="talk-tree-node"><button class="talk-card ${id===S.selected?'selected':''}" data-speaker-gender="${gender===1?'male':gender===2?'female':'neutral'}" data-action="select-talk" data-id="${id}" draggable="${!S.project?.readOnly}" aria-pressed="${id===S.selected}"><div class="talk-card-header"><span class="speaker-dot">${avatar}</span><strong>${StudentAgeRecordLabels.html(id,name)}</strong><span class="talk-index">${String(index+1).padStart(2,'0')}</span></div><p class="talk-snippet">${h(t.content||(restoreScene?'退出 CG 后继续下一句':Number(t.screenEffect?.[0])===4015?'CG 画面':'空白对话'))}</p>${(t.roles?.length||t.option?.length||t.check?.length)?`<div class="talk-tags">${t.roles?.length?`<span class="mini-tag">${t.roles.length} 个动作</span>`:''}${t.option?.length?`<span class="mini-tag">${t.option.length} 个选择</span>`:''}${t.check?.length?'<span class="mini-tag">有条件</span>':''}</div>`:''}${(n=>n?`<div class="id-notes">${n}</div>`:'')(idConflict('talks',id)+idPinNote('talks',id))}</button>${folders}</div>`;
  }
  const internalTalks=Timeline.internals(S.branchFolders);
  const topLevel=S.order.filter(id=>!internalTalks.has(id)&&allowed.has(id)&&(!owners.has(id)||!allowed.has(S.branchFolders[owners.get(id)]?.parentTalkId)));
  const pageSize=100;
  if(S.listAnchor!==S.selected){
    let root=S.selected;const seen=new Set();while(owners.has(root)&&!seen.has(root)){seen.add(root);root=S.branchFolders[owners.get(root)]?.parentTalkId;}
    S.listStart=Math.floor(Math.max(0,topLevel.indexOf(root))/pageSize)*pageSize;S.listAnchor=S.selected;
  }
  S.listStart=Math.min(S.listStart||0,Math.floor(Math.max(0,topLevel.length-1)/pageSize)*pageSize);
  renderedIndex=S.listStart;let html=topLevel.slice(S.listStart,S.listStart+pageSize).map(id=>card(id)).join('');
  if(topLevel.length>pageSize)html+=`<div class="talk-pagination"><button data-action="talk-page" data-start="${Math.max(0,S.listStart-pageSize)}" ${S.listStart===0?'disabled':''}>上一页</button><span>${Math.floor(S.listStart/pageSize)+1} / ${Math.ceil(topLevel.length/pageSize)}</span><button data-action="talk-page" data-start="${S.listStart+pageSize}" ${S.listStart+pageSize>=topLevel.length?'disabled':''}>下一页</button></div>`;
  $('#talk-list').innerHTML=html||`<div class="small-empty">${S.search?'没有找到匹配的对话。':'尚无对话。<br>点击“添加对话”新建。'}</div>`;
}
function welcome() {
  return `<div class="empty-state"><span class="empty-symbol">✧</span><h2>${S.project?'添加对话':'打开模组'}</h2><p>${S.project?'添加对话、设置人物动作和分支。所有修改都可以撤销。':'选择本地或订阅模组，或创建一个新模组。保存后即可在游戏中继续预览。'}</p>${S.project?'<button class="primary" data-action="add-talk">＋ 添加对话</button>':'<button class="primary" data-action="create-project">＋ 新建模组</button><button data-game-location>选择本地模组目录</button>'}${S.project?`<div class="stat-row"><div class="stat-tile"><strong>${values(S.doc.events).length}</strong><span>剧情事件</span></div><div class="stat-tile"><strong>${values(S.doc.persons).filter(p=>!S.goalImageIds?.includes(String(p.id))).length}</strong><span>可用人物</span></div><div class="stat-tile"><strong>${values(S.doc.backgrounds).length+values(S.doc.cgs).length}</strong><span>场景与 CG</span></div></div>`:''}</div>`;
}
function renderEditor() {
  $('#scene-panel').hidden=!talk();
  const container=$('#editor-content');if(!S.project){container.innerHTML=welcome();return;}
  const banner=(S.project.readOnly?'<div class="read-only-banner">订阅模组可以查看、预演。<button data-action="copy-project">创建副本后编辑</button></div>':'')+(!availableProject(S.project.id)?'<div class="read-only-banner">当前项目已不在模组列表中。已有草稿保留在窗口内。</div>':'')+(S.conditionsLoading?'<div id="condition-loading-notice" class="notice-panel" role="status">正在读取条件和效果目录，可先编辑对话内容。</div>':S.conditionsError?`<div id="condition-loading-notice" class="notice-panel" role="status">${h(S.conditionsError)} <button data-action="retry-conditions">重试读取</button></div>`:'');
  if(!talk())container.innerHTML=banner+welcome();
  else container.innerHTML=banner+renderDialogue();
  if(S.project.readOnly)$$('input[data-edit],textarea[data-edit],select[data-edit],input[data-arg],select[data-arg],[data-option-field],[data-folder-continuation],#sfx-add,#bgm-track,#bgm-loop,#bgm-volume,#bgm-range-start,#bgm-range-end,[data-bgm-talk],[data-sfx-volume]',container).forEach(e=>e.disabled=true);
  mountConditionEditors(container);mountEffectEditors(container);
}
function renderFolder(d,depth,card){
 const f=d.folder,conditional=f?.kind==='condition'||d.legacy,open=S.folderOpen[d.key]??!(f?.collapsed??true);
 const references=d.references||[];
 return `<section class="branch-folder ${conditional?'conditional-folder':''} ${S.activeFolder===d.key?'active-folder':''}" data-folder="${d.key}"><button class="branch-folder-title" data-action="toggle-folder" data-folder-key="${d.key}" aria-expanded="${open}"><span>${open?'▾':'▸'}</span><strong>${StudentAgeRecordLabels.html(conditional?null:d.option?.id,d.option?.content||'未载入选项')}</strong><small>${conditional||d.managed?d.talkIds.length+' 句':'选项'}</small>${conditional?'':(n=>n?`<span class="id-notes">${n}</span>`:'')(idConflict('options',d.option?.id)+idPinNote('options',d.option?.id))}</button>${open?`<div class="branch-folder-body">${d.talkIds.map(child=>card(child,depth+1)).join('')}${references.length?`<div class="branch-references">${references.map(target=>`<button data-action="select-talk" data-id="${target}" ${S.doc.talks[target]?'':'disabled'}>↗ ${StudentAgeRecordLabels.html(target,talkLabel(target))}</button>`).join('')}</div>`:''}${!d.legacy&&d.option?`<div class="branch-add-actions"><button class="branch-add" data-action="folder-add-blank" data-folder-key="${d.key}">＋ 空白对话</button><button class="branch-add" data-action="folder-add" data-folder-key="${d.key}">＋ 对话</button></div>${d.managed?`<label class="branch-continuation"><span>对话夹结束后</span><select data-folder-continuation="${d.key}">${continuationOptions(f)}</select></label>`:''}`:''}${conditional?`<label class="branch-continuation"><span>判定失败后进入</span><select data-folder-failure="${d.key}" ${S.project?.readOnly?'disabled':''}>${failureOptions(f||{failureNext:S.doc.talks[d.parentTalkId]?.nextTalk2?.[0]?S.doc.talks[d.parentTalkId].nextTalk2:null},d.parentTalkId)}</select></label>`:''}</div>`:''}</section>`;
}
function renderDialogue() {
 const t=talk();
 let html=effectMarkup('talks',t.id,'effect','本句效果','在游戏中显示这句对话时执行。');
 html+=`<div class="section-divider"></div><div class="section-title"><h3>对话选项</h3><button class="text-button" data-action="add-option">＋ 添加选项</button></div>`;
 for(const oid of ids(t.option)){
  const o=S.doc.options[oid];if(!o){html+=`<p class="helper">选项内容未载入</p>`;continue;}
  const count=o.precondition?.length||0,folder=S.branchFolders[Branches.key(t.id,oid)],managedEntry=!!folder?.talkIds?.length;
  html+=`<div class="branch-card"><div class="row"><input class="grow" data-option-id="${oid}" data-option-field="content" value="${h(o.content||'')}" placeholder="选项文字" aria-label="选项内容"><button class="icon-button danger-text" data-action="delete-option" data-id="${oid}" aria-label="删除选项">×</button></div><button class="option-limit-button" data-action="option-limit" data-id="${oid}">${count?'可用条件 · '+count+' 项':'＋ 可用条件'}</button><button class="option-limit-button" data-action="option-check" data-id="${oid}">成功判定 · ${o.check?.length||0} 项</button><div class="audio-range"><label><span>${o.check?.length?'判定成功后':'选择后'}</span>${targetSelect(o,'talkId',`data-option-id="${oid}" data-option-field="talkId" ${managedEntry?'disabled title="成功后进入左侧对话夹；后续去向在对话夹底部设置"':''}`,t.id)}</label><label><span>判定失败后</span>${targetSelect(o,'talkId2',`data-option-id="${oid}" data-option-field="talkId2"`,t.id)}</label></div>${effectMarkup('options',oid,'effect','成功效果','选项判定成功时执行。')}${effectMarkup('options',oid,'effect2','失败效果','选项判定失败时执行。')}</div>`;
 }
 html+=`<div class="section-title"><h3>条件分支</h3><button class="text-button" data-action="add-branch">＋ 添加分支</button></div><p class="helper">分支在左侧展开。按顺序判断，进入首个满足条件的分支。</p>`;
 for(const [key,f] of Timeline.entries(S.branchFolders,t.id).filter(([,f])=>f.kind==='condition')){
  const router=S.doc.talks[f.routerId];if(!router)continue;
  html+=`<div class="branch-card conditional-branch-card" data-folder-card="${h(key)}"><div class="row branch-card-head"><strong>分支${f.branchId}</strong><span class="helper">${ids(f.talkIds).length} 句</span><button class="text-button" data-action="reveal-folder" data-folder-key="${h(key)}">在左侧查看</button><button class="icon-button danger-text" data-action="delete-branch" data-folder-key="${h(key)}" aria-label="删除分支">×</button></div>${conditionMarkup('talks',f.routerId,'check','触发条件','按左侧顺序判断，进入首个满足条件的分支；未设置条件时直接进入。',true)}</div>`;
 }
 if(Number(t.screenEffect?.[0])===4015)html+=`<button class="secondary" data-action="pick-cg">更换此 CG</button>`;
 return html+renderAudio();
}
function screenEffectControls(t){const effect=StudentAgeScreenEffects.entries.find(e=>e.id===Number(t.screenEffect?.[0]));return `<section class="screen-effect-controls"><h3>屏幕效果</h3><button data-action="screen-effect">${h(effect?.name|| (t.screenEffect?.length?'已有屏幕效果':'＋ 添加屏幕效果'))}</button>${t.screenEffect?.length?'<button data-action="screen-effect-clear">移除</button>':''}</section>`;}
async function editScreenEffect(){const t=talk();if(!t||!editable())return;const id=t.id;
 const result=await StudentAgeScreenEffects.edit({projectId:S.project.id,api,talk:t,persons:S.doc.persons,allowPaper:true});
 if(!result||talk()?.id!==id)return;if(result.paper){editPaper();return;}
 mutate('设置屏幕效果',()=>Object.assign(talk(),result));
}
function slider(index,arg,label,min,max,step=0.1,unit='') {
  const row=talk().roles[index],v=row[arg]??0;
  return `<label class="range-field"><span class="field-label">${h(label)}<output id="range-${index}-${arg}">${Number(v).toFixed(step>=1?0:1)}${h(unit)}</output></span><input type="range" min="${min}" max="${max}" step="${step}" value="${v}" data-arg="${arg}" data-action-index="${index}" data-unit="${h(unit)}"></label>`;
}
function applyExpression() {
  const t=talk();if(!t||S.previewRole===null||!currentStage().roles[S.previewRole]?.visible)return;mutate('设置人物表情',()=>setRoleCommand(t,Number(S.previewRole),3000,[S.face]));
}

let largeScene=null,scenePlayer=null,sceneMode='edit',sceneSyncing=false,stageAudio=null;
let linePlayback=null,storyPreview=null;
function stopLinePlayback(redraw=true){
 window.StudentAgeAudioFocus?.set('story-line',false);
 if(!linePlayback)return;clearTimeout(linePlayback.frame);clearTimeout(linePlayback.timer);linePlayback=null;
 largeScene?.container.getAnimations?.({subtree:true}).forEach(a=>a.cancel());stageAudio?.stop();sceneMode='edit';
 if($('[data-scene="play"]'))$('[data-scene="play"]').textContent='播放';if(redraw)renderPreview();
}
function playCurrentLine(){
 if(!talk())return;stopLinePlayback(false);ensureScene();scenePlayer.pause();stageAudio.stop();
 const before=currentStage(true),after=currentStage();prepareSceneExpressions(before);prepareSceneExpressions(after);
 sceneMode='clip';const playback=linePlayback={};window.StudentAgeAudioFocus?.set('story-line',true);
 $('[data-scene="play"]').textContent='停止播放';
 largeScene.draw(S.doc,after,{edit:false,animate:true,fromState:before});stageAudio.enter(after.talkId,after.trace);
 const duration=Math.max(1500,StudentAgeScreenEffects.duration(after),...(after.motions||[]).map(m=>(Math.max(0,m.delay||0)+Math.max(.4,m.duration||0,m.shake||0))*1000+150));
 const finish=()=>{if(linePlayback!==playback)return;if(stageAudio.sfx.some(audio=>!audio.ended&&!audio.paused&&!audio.error)){playback.timer=setTimeout(finish,200);return;}stopLinePlayback();};playback.timer=setTimeout(finish,duration);
}
function updateStoryPreviewControls(){
 const button=$('#story-preview-controls [data-story-preview="auto"]');
 if(storyPreview&&scenePlayer?.ended)storyPreview.auto=false;
 if(button){button.setAttribute('aria-pressed',String(!!storyPreview?.auto));button.querySelector('span').textContent=storyPreview?.auto?'自动中':'自动';}
}
function toggleStoryAuto(){
 if(!storyPreview||scenePlayer.ended)return;
 storyPreview.auto=!storyPreview.auto;
 // Reuse the current line's timing without re-rendering/replaying its actions or audio.
 if($('#large-scene .scene-route-overlay').hidden)scenePlayer.playing=true;
 scenePlayer.schedule();updateStoryPreviewControls();
}
function previewRoutes(scene){
 if(!storyPreview)return scene.routeChoices||[];
 const routes=StudentAgeScene.routes({...S.doc,branchFolders:S.branchFolders},S.doc.talks[scene.talkId],{allBranches:true});let index=0;
 return routes.filter(route=>!route.gender||route.gender===protagonistGender()).map(route=>route.genderOnly?{...route,conditional:false,label:route.label.replace(/ · [男女]主角/g,'')}:route).map(route=>route.type==='branch'?{...route,label:'分支'+route.branchId}:route.type==='alternate'&&route.label.startsWith('所有分支')?{...route,label:'不进入分支，继续'}:route.conditional&&route.optionId===undefined&&!route.eventId?{...route,label:'分支'+(++index)}:route);
}
function openStoryPreview(){
 if(largeScene){largeScene.paperClosed=null;largeScene.paperSignature=null;}
 if(!talk()){toast('先选择一个有对话的事件。','note');return;}if(storyPreview)return;
 stopLinePlayback(false);ensureScene();scenePlayer.pause();stageAudio.stop();closeContextMenu();
 storyPreview={auto:false,selected:S.selected,event:S.event,activeFolder:S.activeFolder,folderOpen:clone(S.folderOpen),previewRole:S.previewRole,scroll:$('#editor-scroll').scrollTop,trace:scenePlayer.trace.slice()};
 const stage=$('#large-scene'),controls=$('#story-preview-controls');storyPreview.portals=[stage,controls].map(node=>{const marker=document.createComment('preview-return');node.before(marker);document.body.append(node);return {node,marker};});
 document.activeElement?.blur();window.getSelection()?.removeAllRanges();
 controls.innerHTML='<button type="button" data-story-preview="history" aria-label="Tab 日志"><i aria-hidden="true"></i><span>日志</span></button><button type="button" data-story-preview="auto" aria-label="Shift 自动播放" aria-pressed="false"><i aria-hidden="true"></i><span>自动</span></button><button type="button" data-story-preview="exit" aria-label="Esc 退出剧情预览"><i aria-hidden="true"></i><span>菜单</span></button>';
 document.body.classList.add('story-fullscreen');controls.hidden=false;sceneMode='play';
 const id=S.selected;scenePlayer.select(id,storyPreview.trace.at(-1)===id?storyPreview.trace:null);stageAudio.prime(scenePlayer.trace.slice(0,-1));prepareSceneExpressions(scenePlayer.scene);scenePlayer.play();updateStoryPreviewControls();$('#large-scene').focus();
}
let historyImageObserver=null,historyImageEpoch=0;
const historyPortraitLoads=new Map();
async function loadHistoryPortrait(node,portrait,epoch){
 const current=()=>epoch===historyImageEpoch&&node.isConnected&&$('#story-history').open;
 const img=new Image();img.alt=portrait.name;img.dataset.face=portrait.face;img.dataset.cloth=portrait.cloth;img.decoding='async';if(portrait.flip)img.style.transform='scaleX(-1)';
 const attempt=async fresh=>{for(const path of portrait.paths){if(!current())return false;const loaded=await new Promise(resolve=>{img.onload=()=>resolve(true);img.onerror=()=>resolve(false);img.src=assetUrl(path,portrait.projectId)+(fresh?'&historyRetry='+Date.now():'');});if(loaded){if(current())node.replaceChildren(img);return true;}}return false;};
 if(await attempt(false)||!current())return;
 if(portrait.model){
  const key=JSON.stringify([portrait.projectId,portrait.id,portrait.grade,portrait.cloth,portrait.face,portrait.gender]);
  for(let count=0;count<30&&current();count++){
   let task=historyPortraitLoads.get(key);if(!task){task=api('/api/portraits',{projectId:portrait.projectId,role:portrait.id,grade:portrait.grade,cloth:portrait.cloth,face:portrait.face,gender:portrait.gender});historyPortraitLoads.set(key,task);task.finally(()=>historyPortraitLoads.delete(key)).catch(()=>{});}
   let result;try{result=await task;}catch{break;}
   if(await attempt(true)||!current())return;if(!result.active)break;
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
 }
 if(current()){const missing=document.createElement('small');missing.textContent='该表情未读取到';node.replaceChildren(missing);}
}
function closeStoryHistory(restoreFocus=true){
 const panel=$('#story-history');if(!panel.open)return;panel.close();historyImageObserver?.disconnect();historyImageEpoch++;$('#story-history-entries').replaceChildren();
 if(restoreFocus){$('#large-scene')?.focus({preventScroll:true});scenePlayer?.schedule();}
}
function openStoryHistory(){
 if(!storyPreview)return;const panel=$('#story-history');if(panel.open)return;
 const entries=previewHistory().current?.entries||[],list=$('#story-history-entries');
 list.innerHTML=entries.map((entry,lineIndex)=>entry.kind==='dialogue'?`<article class="story-history-line" data-speaker-gender="${entry.speakerGender===1?'male':entry.speakerGender===2?'female':'neutral'}" data-narration="${entry.narration===true}">${entry.portraits?.length?'<div class="story-history-portraits">'+entry.portraits.map((portrait,index)=>`<div class="story-history-portrait" data-history-line="${lineIndex}" data-history-person="${index}" aria-label="${h(portrait.name)}的当前表情"></div>`).join('')+'</div>':''}<div class="story-history-text"><strong>${h(entry.speaker)}</strong><p>${h(entry.content)}</p></div></article>`:entry.kind==='choice'?`<p class="story-history-choice" aria-label="已选择：${h(entry.content)}">${h(entry.content)}</p>`:'').join('')||'<p class="helper">尚无已播放的对话。</p>';
 panel.showModal();scenePlayer?.schedule();list.scrollTop=list.scrollHeight;list.focus({preventScroll:true});
 const epoch=++historyImageEpoch;
 historyImageObserver=new IntersectionObserver(changes=>{for(const change of changes)if(change.isIntersecting){historyImageObserver.unobserve(change.target);const node=change.target;loadHistoryPortrait(node,entries[Number(node.dataset.historyLine)].portraits[Number(node.dataset.historyPerson)],epoch);}}, {root:list,rootMargin:'160px'});
 list.querySelectorAll('[data-history-person]').forEach(node=>historyImageObserver.observe(node));
}
$('#story-history').addEventListener('cancel',event=>{event.preventDefault();closeStoryHistory();});
$('#story-history').addEventListener('click',event=>{if(event.target.closest('[data-story-history-close]'))closeStoryHistory();});
const storyExitDialog=document.createElement('dialog');storyExitDialog.id='story-exit-confirm';
storyExitDialog.innerHTML='<h2>退出剧情预览？</h2><p>退出后返回当前剧情的编辑界面。</p><div><button data-preview-keep>继续预览</button><button data-preview-confirm-exit>退出预览</button></div>';document.body.append(storyExitDialog);
function keepStoryPreview(){storyExitDialog.close();if(storyPreview){storyPreview.exiting=false;scenePlayer?.schedule();$('#large-scene').focus({preventScroll:true});}}
storyExitDialog.querySelector('[data-preview-keep]').onclick=keepStoryPreview;
storyExitDialog.querySelector('[data-preview-confirm-exit]').onclick=()=>{storyExitDialog.close();closeStoryPreview();};
storyExitDialog.addEventListener('cancel',event=>{event.preventDefault();keepStoryPreview();});
function requestStoryExit(){if(!storyPreview||storyExitDialog.open)return;if(scenePlayer?.ended){closeStoryPreview();return;}if($('#story-history').open){closeStoryHistory();return;}storyPreview.exiting=true;scenePlayer?.schedule();storyExitDialog.showModal();storyExitDialog.querySelector('[data-preview-keep]').focus();}
function closeStoryPreview(){
 window.StudentAgeAudioFocus?.set('story-preview',false);
 if(!storyPreview)return;if(storyExitDialog.open)storyExitDialog.close();closeStoryHistory(false);const prior=storyPreview;storyPreview=null;scenePlayer?.pause();stageAudio?.stop();largeScene?.container.getAnimations?.({subtree:true}).forEach(a=>a.cancel());
 for(const {node,marker} of prior.portals||[]){marker.replaceWith(node);}
 document.body.classList.remove('story-fullscreen');$('#story-preview-controls').hidden=true;sceneMode='edit';
 Object.assign(S,{selected:prior.selected,event:prior.event,activeFolder:prior.activeFolder,folderOpen:prior.folderOpen,previewRole:prior.previewRole});scenePlayer.select(S.selected,prior.trace);render();$('[data-action="preview-story"]')?.focus({preventScroll:true});$('#editor-scroll').scrollTo({top:prior.scroll,behavior:'instant'});requestAnimationFrame(()=>{if(!storyPreview&&S.selected===prior.selected)$('#editor-scroll').scrollTo({top:prior.scroll,behavior:'instant'});});
}
function openActionEditor(){
 if(!editable()||!talk())return;stopLinePlayback();const after=currentStage(),before=currentStage(true),selected=S.selected,project=S.project.id;
 const available=id=>after.roles[id]||before.roles[id]||(talk().roles||[]).some(r=>Number(r[0])===Number(id));
 const role=S.previewRole!==null&&available(S.previewRole)?Number(S.previewRole):Number(Object.values(after.roles).find(r=>r.visible)?.id??talk().roles?.[0]?.[0]??Object.keys(before.roles)[0]);
 if(!Number.isFinite(role)){toast('先选择一个在场人物。','note');return;}
 const appearance=id=>{const actor=currentStage().roles[id]||before.roles[id],person=S.doc.persons[id],cloth=actor?.cloth||0,models=person?.[S.grade===0?'l2d':'l2d2']||[],images=person?.[S.grade===0?'url':'url2']||[];
  return {faces:StudentAgeExpressions.choices({person,faces:S.doc.faces,roleId:id,grade:S.grade,cloth,metadata:portraitAvailability.get(portraitMetadataKey(id,S.grade,cloth))}),clothes:[...new Set([0,cloth,...models.map((v,i)=>v?i:0),...images.map((v,i)=>v?i:0)])].sort((a,b)=>a-b)};};
 const valid=()=>S.project.id===project&&S.selected===selected;
 const changed=()=>{const state=currentStage();S.face=state.roles[role]?.face??0;S.cloth=state.roles[role]?.cloth??0;prepareOriginalExpressions();prepareSceneExpressions(state);};
 StudentAgeActionEditor.open({assetUrl,appearance,blocked:phoneEvent()?[...phoneFixedActions]:[],context:()=>valid()?{doc:S.doc,grade:S.grade,before:currentStage(true),after:currentStage(),row:talk(),role,name:personName(role),...appearance(role)}:null,
 createAudio:()=>new StudentAgeScene.AudioPlayer({getCues:()=>S.doc?.audioCues,getUrl:audioUrl,getLegacy:id=>S.audios.find(a=>Number(a.id)===Number(S.doc?.talks[id]?.audio)),onWarning:m=>toast(m,'note')}),
 add:(code,args)=>{if(!valid()||(phoneEvent()&&phoneFixedActions.has(Number(code))))return null;const accepted=mutate('添加人物动作',()=>{
  const group=[1001,1002,1003].includes(code)?[1001,1002,1003]:[2001,2002].includes(code)?[2001,2002]:[];
  if(group.length)talk().roles=(talk().roles||[]).filter(r=>!(Number(r[0])===role&&group.includes(Number(r[1]))&&Number(r[1])!==code));
  setRoleCommand(talk(),role,code,args);
 },null,false);if(!accepted)return null;changed();return talk().roles.findIndex(r=>Number(r[0])===role&&Number(r[1])===code);},
 update:(index,args)=>{if(!valid()||!talk().roles?.[index])return;const row=talk().roles[index];mutate(args?'调整人物动作':'移除人物动作',()=>{if(args)talk().roles[index]=[row[0],row[1],...args];else talk().roles.splice(index,1);},args?'action-'+selected+'-'+index+'-'+row[1]:null,false);changed();},
 onClose:()=>{S.coalesce=null;render();}});
}
function scrollStoryHistory(direction,amount=120){
 if(!storyPreview)return;
 const panel=$('#story-history'),list=$('#story-history-entries');
 if(!panel.open){if(direction<0){openStoryHistory();list.scrollTop=Math.max(0,list.scrollTop-amount);}return;}
 if(direction>0&&list.scrollTop+list.clientHeight>=list.scrollHeight-2){closeStoryHistory();return;}
 list.scrollTop+=direction*amount;
}
document.addEventListener('wheel',event=>{
 if(!storyPreview||storyExitDialog.open||event.ctrlKey||event.deltaY===0)return;
 event.preventDefault();const unit=event.deltaMode===1?40:event.deltaMode===2?innerHeight:1;
 scrollStoryHistory(Math.sign(event.deltaY),Math.max(20,Math.min(innerHeight*.8,Math.abs(event.deltaY)*unit)));
},{passive:false});
window.STUDIO_PREVIEW_ACTIVE=()=>!!storyPreview;
document.addEventListener('click',event=>{
 if(!storyPreview||storyExitDialog.open)return;
 if($('#story-history').open)return;
 if(event.target.closest('[data-story-preview="history"]')){openStoryHistory();return;}
 if(event.target.closest('[data-story-preview="exit"]')){requestStoryExit();return;}
 if(event.target.closest('[data-story-preview="auto"]')){toggleStoryAuto();return;}
 if(!event.target.closest('#large-scene')||event.target.closest('.scene-route-overlay'))return;
 if(largeScene?.dismissPaper())return;
 if(!$('#large-scene .scene-route-overlay').hidden)return;
 if(scenePlayer.ended)closeStoryPreview();else scenePlayer.next();
});
function sceneContext() {
  const entries=e=>{const targets=ids(e?.talkId);return targets.length>1?[targets[protagonistGender()-1]||targets[0]]:targets;};
  const roots=S.event==='all'?values(S.doc?.events).flatMap(entries):entries(S.doc?.events[S.event]);
  return {roots,event:S.doc?.events[S.event],grade:S.grade,reference:S.referenceResolution||[2560,1440]};
}
let stageMemo=[],stageMemoQueued=false;
function invalidateStageMemo(){stageMemo=[];}
function currentStage(before=false,doc=S.doc) {
  if(!doc||!S.selected||!window.StudentAgeScene)return {roles:{},trace:[],warnings:[]};
  const playerTrace=scenePlayer?.scene?.talkId===S.selected?scenePlayer.trace:null;
  const cached=stageMemo.find(row=>row.doc===doc&&row.selected===S.selected&&row.event===S.event&&row.grade===S.grade&&row.before===before&&row.trace===playerTrace&&row.length===playerTrace?.length);
  if(cached)return cached.state;
  const context=sceneContext(),model={...doc,branchFolders:S.branchFolders},trace=playerTrace?playerTrace.slice():StudentAgeScene.pathTo(model,S.selected,context.roots).path;
  if(before)trace.pop();
  const state=before&&!trace.length?StudentAgeScene.blank(context.reference):StudentAgeScene.reconstruct(model,trace[trace.length-1]||S.selected,{...context,trace});
  stageMemo.push({doc,selected:S.selected,event:S.event,grade:S.grade,before,trace:playerTrace,length:playerTrace?.length,state});
  // Reuse work within a single UI update, never across asynchronous edits.
  if(!stageMemoQueued){stageMemoQueued=true;queueMicrotask(()=>{stageMemoQueued=false;invalidateStageMemo();});}
  return state;
}
function presentRoles(){return values(currentStage().roles).filter(r=>r.visible);}
function sceneStatus(state) {
  const count=values(state.roles).filter(r=>r.visible).length,bg=S.doc?.backgrounds[state.background];
  return (bg?assetName(bg,'background'):'未指定背景')+' · '+count+' 位在场人物'+(state.cg?' · CG':'');
}
function setRoleCommand(row,roleId,code,args) {
  row.roles=row.roles||[];const first=row.roles.findIndex(r=>Number(r[0])===roleId&&Number(r[1])===code);
  row.roles=row.roles.filter(r=>!(Number(r[0])===roleId&&Number(r[1])===code));
  row.roles.splice(first<0?row.roles.length:Math.min(first,row.roles.length),0,[roleId,code,...args]);
}
function selectStageRole(id) {
  const actor=currentStage().roles[Number(id)];if(!actor?.visible)return;
  S.previewRole=Number(id);S.face=actor.face;S.cloth=actor.cloth;
  largeScene?.setSelected(S.previewRole);renderInspector();renderInitialPosition();
  if($('#scene-person-select'))$('#scene-person-select').value=String(S.previewRole);
  $$('#scene-cast [data-id]').forEach(b=>b.classList.toggle('active',Number(b.dataset.id)===S.previewRole));
}
function initialEntry(roleId,state=currentStage()){
 roleId=Number(roleId);if(!state.roles[roleId]?.visible)return null;
 const trace=state.trace||[];
 for(let i=trace.length-1;i>=0;i--){const row=S.doc.talks[trace[i]];if(!row)continue;
  for(let j=(row.roles||[]).length-1;j>=0;j--){const command=row.roles[j];if(Number(command[0])===roleId&&[1001,1002,1003].includes(Number(command[1])))return {talkId:row.id,index:j,axis:Number(command[3])||state.roles[roleId].axis};}
 }
 // Native dialogue may bring in its speaker without an explicit entry command.
 let scene=StudentAgeScene.blank(S.referenceResolution);
 for(const id of trace){const row=S.doc.talks[id];if(!row)continue;scene=StudentAgeScene.apply(S.doc,scene,row,S.grade,false);if(scene.roles[roleId]?.visible)return {talkId:row.id,index:-1,axis:scene.roles[roleId].axis,layer:scene.roles[roleId].layer,implicit:!(row.roles||[]).length?scene.motions.filter(m=>[1001,1002,1003].includes(m.code)).map(m=>[m.id,m.code,scene.roles[m.id].layer,scene.roles[m.id].axis,0]):null};}
 return null;
}
function renderInitialPosition(state=currentStage()){
 const node=$('#scene-initial-position');if(!node)return;const entry=initialEntry(S.previewRole,state),disabled=!entry||!isLocalProject(S.project)||sceneMode!=='edit';
 node.innerHTML=`<div><strong>${entry?h(personName(S.previewRole))+' · ':''}初始站位</strong><small>${entry?(Number(entry.talkId)===Number(S.selected)?'当前句登场，后续位移保留':'调整此前的登场句，后续位移保留'):'先让人物登场，再选择人物'}</small></div><div class="initial-position-buttons" role="group" aria-label="初始站位">${[[1,'左'],[3,'中'],[2,'右']].map(([axis,name])=>`<button data-initial-axis="${axis}" aria-pressed="${entry?.axis===axis}" ${disabled?'disabled':''}>${name}</button>`).join('')}</div>${entry&&Number(entry.talkId)!==Number(S.selected)?`<button class="text-button" data-initial-source="${entry.talkId}">查看登场句</button>`:''}`;
}
function setInitialPosition(roleId,axis){
 roleId=Number(roleId);axis=Number(axis);if(![1,2,3].includes(axis)||!isLocalProject(S.project)||storyPreview)return;
 stopLinePlayback();const entry=initialEntry(roleId);if(!entry||entry.axis===axis)return;
 const row=S.doc.talks[entry.talkId];
 mutate('调整'+personName(roleId)+'的初始站位',()=>{
  if(entry.index>=0){const command=row.roles[entry.index];while(command.length<4)command.push(0);command[3]=axis;}
  else if(entry.implicit?.length){row.roles=entry.implicit.map(command=>{const copy=command.slice();if(Number(copy[0])===roleId)copy[3]=axis;return copy;});}
  else{row.roles||=[];row.roles.unshift([roleId,1001,entry.layer||1,axis,0]);}
 });
}
function commitSceneDrag(roleId,dx,dy,context=null) {
  if(context&&(Number(context.talkId)!==Number(S.selected)||context.doc!==S.doc))return;
  const selected=talk(),state=currentStage();if(!selected||!state.roles[roleId]?.visible)return;
  const target={x:Math.round((context?.x??state.roles[roleId].x)+dx),y:Math.round((context?.y??state.roles[roleId].y)+dy)};
  try{
    const commands=StudentAgeScene.planSceneDrag(selected,state,Number(roleId),target,roles=>currentStage(false,{...S.doc,talks:{...S.doc.talks,[S.selected]:{...selected,roles}}}));
    mutate('拖动人物位置',()=>{selected.roles=commands;});
  }catch(error){toast(error.message,'note');render();}

}
function enterSceneRole(id,appearance={}) {
  id=Number(id);if(!talk()||!S.doc?.persons[id])return;
  if(phoneEvent()){if(id!==0)mutate('更换通话对象',()=>{configurePhone(phoneEvent(),id,phoneHome(id));if(appearance.cloth!=null)setRoleCommand(talk(),id,3006,[Number(appearance.cloth)]);});selectStageRole(id);return;}
  if(currentStage().roles[id]?.visible){selectStageRole(id);return;}
  const occupied=presentRoles(),axis=occupied.length===0?1:!occupied.some(r=>r.axis===2)?2:3;
  S.previewRole=id;mutate('人物登场',()=>{talk().roles=(talk().roles||[]).filter(r=>!(Number(r[0])===id&&[1001,1002,1003,2001,2002].includes(Number(r[1]))));talk().roles.push([id,1002,1,axis,0]);if(Number.isInteger(appearance.cloth)&&appearance.cloth>=0&&appearance.cloth<=9)setRoleCommand(talk(),id,3006,[appearance.cloth]);});
  selectStageRole(id);
}
function removeStageRole(id) {
  id=Number(id);if(!talk())return;if(phoneEvent()){if(id===0)return;mutate('移除通话对象',()=>configurePhone(phoneEvent(),0));return;}const inherited=currentStage(true).roles[id]?.visible;
  mutate('移除舞台人物',()=>{const row=talk();row.roles=(row.roles||[]).filter(r=>Number(r[0])!==id);if(inherited)row.roles.push([id,2002,0]);row.roleIds=ids(row.roleIds).filter(x=>x!==id);row.highlights=ids(row.highlights).filter(x=>x!==id);});
}
function flipStageRole(id,code=3005) {
  id=Number(id);const now=currentStage().roles[id];if(!now?.visible)return;
  const baseDoc=clone(S.doc);baseDoc.talks[S.selected].roles=(talk().roles||[]).filter(r=>!(Number(r[0])===id&&[3005,3007].includes(Number(r[1]))));
  const base=currentStage(false,baseDoc).roles[id];const desired=!now.flip;
  mutate('翻转人物',()=>{talk().roles=baseDoc.talks[S.selected].roles;if(desired!==!!base?.flip)talk().roles.push([id,code,0]);});
}
function quickApplyAction(code) {
  code=Number(code);const id=Number(S.previewRole);if(!currentStage().roles[id]?.visible){toast('先选择在场人物。','note');return;}
  if(code===2002){removeStageRole(id);return;}if(code===3005||code===3007){flipStageRole(id,code);return;}
  if(code===3004||code===3008){openScene();$('#large-scene').focus();return;}
  const action=ACTIONS[code];if(!action)return;
  mutate(action.name,()=>setRoleCommand(talk(),id,code,code===3000?[S.face]:code===3006?[S.cloth]:action.args.slice()));
}
function renderSceneWarnings(assetWarnings=[]) {
  const warnings=[...(scenePlayer?.scene?.warnings||[]),...assetWarnings];
  $('#scene-warnings').innerHTML=(warnings.length?warnings:['按实际对话路径还原背景与人物。']).map(w=>`<p class="scene-warning">${h(w)}</p>`).join('');
}
function closeContextMenu(){$('#scene-context-menu').hidden=true;}
function openActorMenu(id,x,y) {
  if(S.project?.readOnly||sceneMode!=='edit')return;selectStageRole(id);
  const state=currentStage(),speaking=state.speakerIds.includes(id),highlighted=state.highlightIds.includes(id),menu=$('#scene-context-menu');menu.dataset.role=String(id);menu.dataset.talk=String(S.selected);menu.dataset.project=S.project.id;
  menu.innerHTML=`<strong>${h(personName(id))}</strong><button role="menuitem" data-stage-menu="flip-instant">无动画翻转</button><button role="menuitem" data-stage-menu="flip">有动画翻转</button>${speaking?'<button role="menuitem" data-stage-menu="remove-speaker">不再由此人说话</button>':'<button role="menuitem" data-stage-menu="add-speaker">添加为说话人</button>'}<button role="menuitem" class="danger-text" data-stage-menu="remove">从此句移除人物</button><button role="menuitem" data-stage-menu="light-toggle" ${speaking?'disabled title="说话人物保持高光"':''}>${highlighted?'取消高光':'设为高光'}</button><div class="context-initial-position"><span>初始站位</span>${[[1,'左'],[3,'中'],[2,'右']].map(([axis,label])=>`<button role="menuitem" data-stage-menu="initial-position" data-axis="${axis}" aria-label="初始站位：${label}">${label}</button>`).join('')}</div>`;
  if(phoneEvent()){if(Number(id)===0)menu.querySelector('[data-stage-menu="remove"]')?.remove();}
  menu.hidden=false;menu.style.left=Math.max(8,Math.min(x,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(y,innerHeight-menu.offsetHeight-8))+'px';
}
function scenePlayerRender(state,flags) {
 window.StudentAgeAudioFocus?.set('story-preview',!!storyPreview&&!flags.ended);
  if(!state||!largeScene)return;
  if(flags.ended&&storyPreview){closeStoryPreview();return;}
  const menu=$('#scene-context-menu');if(!menu.hidden&&(menu.dataset.project!==S.project?.id||Number(menu.dataset.talk)!==S.selected||!state.roles[menu.dataset.role]?.visible||sceneMode!=='edit'))closeContextMenu();$('#scene-panel').hidden=!talk();
  largeScene.draw(S.doc,state,{edit:sceneMode==='edit'&&!S.project?.readOnly,animate:flags.animate});largeScene.showChoices([],()=>{});
  const visible=values(state.roles).filter(r=>r.visible);
  if(!state.roles[S.previewRole]?.visible)S.previewRole=visible[0]?.id??null;
  if(S.previewRole!==null){S.face=state.roles[S.previewRole].face;S.cloth=state.roles[S.previewRole].cloth;}
  largeScene.setSelected(S.previewRole);
  $('#scene-enter-button small').textContent=visible.length+' 位人物在场';
  $('#scene-person-select').innerHTML=personOptions(S.previewRole);renderInitialPosition(state);
  const shownBackground=state.phone?.left||state.background,inheritedBackground=!state.phone&&!Number(talk()?.bg),backgroundName=S.doc.backgrounds[shownBackground]?assetName(S.doc.backgrounds[shownBackground],'background'):'';
  $('#scene-background-button small').textContent=(inheritedBackground&&backgroundName?'沿用：':'')+(backgroundName||'选择背景图片');
  $('#scene-position').textContent=state.trace.length+' 句';$('#scene-summary').textContent=sceneStatus(state);
  $('#scene-status').textContent=flags.ended?'本段播放结束。':sceneMode==='edit'?'单击选择人物；拖动设置移动；右键编辑人物。':'播放中保留整场状态，分支由你选择。';
  $('[data-scene="play"]').textContent=scenePlayer?.playing?'播放中':'播放';
  $$('[data-scene="mode"]').forEach(b=>b.classList.toggle('active',b.dataset.mode===sceneMode));
  $('#scene-cast').innerHTML=visible.length?visible.map(r=>`<button class="cast-chip ${r.id===S.previewRole?'active':''}" data-scene="inspect" data-id="${r.id}">${h(personName(r.id))}</button>`).join(''):'<p class="helper">尚无在场人物。请在舞台上方选择人物登场。</p>';
  for(const id of ['scene-enter-button','scene-background-button','scene-action-button','scene-effect-button','scene-cg-button'])$('#'+id).disabled=!!S.project?.readOnly;
  renderSpeakers(state);
  renderSceneWarnings([...largeScene.assetWarnings.values()]);renderInspector();prepareSceneExpressions(state);
  updateStoryPreviewControls();
  if(flags.ended)stageAudio?.stop();else if(sceneMode==='play'&&flags.animate)stageAudio?.enter(state.talkId,state.trace);
}
function ensureScene() {
  if(!stageAudio)stageAudio=new StudentAgeScene.AudioPlayer({getCues:()=>S.doc?.audioCues,getUrl:audioUrl,getDefaultBgm:()=>S.defaultBgm?{...S.defaultBgm,url:assetUrl(S.defaultBgm.url)}:null,getLegacy:id=>S.audios.find(a=>Number(a.id)===Number(S.doc?.talks[id]?.audio)),onWarning:m=>toast(m,'note')});
  if(!largeScene)largeScene=new StudentAgeScene.Renderer($('#large-scene'),{screenRefs:()=>S.conditionRefs,onPaperClose:()=>scenePlayer?.schedule(),assetUrl,emojiAtlas:'/api/social-emojis?token='+encodeURIComponent(token),talkUi:{manifest:'/api/talk-ui?token='+encodeURIComponent(token),resource:name=>'/api/talk-ui?resource='+encodeURIComponent(name)+'&token='+encodeURIComponent(token)},onBeforeInteract:()=>{if(storyPreview||!isLocalProject(S.project))return false;if(linePlayback)stopLinePlayback();return sceneMode==='edit';},onDrag:commitSceneDrag,onSelectRole:selectStageRole,onContextMenu:openActorMenu,onCGContextMenu:openCGMenu,onAssetStatus:renderSceneWarnings,canEditDialogue:()=>sceneMode==='edit'&&isLocalProject(S.project)&&!!talk(),onChooseSpeaker:cycleSpeaker});
  if(!scenePlayer)scenePlayer=new StudentAgeScene.Player({getDoc:()=>({...S.doc,branchFolders:S.branchFolders}),onHistory:recordPreviewHistory,getContext:sceneContext,manual:()=>!!largeScene?.paperVisible||!!storyPreview&&(!storyPreview.auto||storyPreview.exiting||$('#story-history').open),getChoices:previewRoutes,onRender:scenePlayerRender,onChoices:choices=>{largeScene.showChoices(choices,route=>scenePlayer.choose(route));$('#scene-status').textContent='请选择要预览的路线。';},onSelect:id=>{S.selected=id;S.activeFolder=Branches.ownedBy(S.branchFolders,id);if(S.activeFolder)S.folderOpen[S.activeFolder]=true;S.coalesce=null;renderChrome();renderList();renderEditor();},onWarning:m=>toast(m,'note'),onPlaying:()=>updateStoryPreviewControls()});
}
function renderPreview() {
  if(S.doc)window.StudentAgePreviewUI?.load();
  if(S.doc&&talk())prepareSceneExpressions(currentStage());
  $('#scene-panel').hidden=!talk();
  if(!S.doc||!talk()){renderInspector();return;}
  if(sceneMode!=='edit'){largeScene?.refreshPortraits();renderInspector();return;}
  if(!sceneSyncing){ensureScene();sceneSyncing=true;try{if(scenePlayer.scene?.talkId===S.selected)scenePlayer.refresh();else scenePlayer.select(S.selected);}finally{sceneSyncing=false;}}
}
function renderMiniScene(){renderPreview();}
function openScene() {
  if(!talk()){toast('先选择一句对话。','note');return;}
  ensureScene();largeScene.invalidateAssets(true);renderPreview();$('#editor-scroll').scrollTo({top:0,behavior:'smooth'});
}
document.addEventListener('click',event=>{
  const axisButton=event.target.closest('[data-initial-axis]');if(axisButton){if(!axisButton.disabled)setInitialPosition(S.previewRole,axisButton.dataset.initialAxis);return;}
  const sourceButton=event.target.closest('[data-initial-source]');if(sourceButton){selectTalk(Number(sourceButton.dataset.initialSource));return;}
  const item=event.target.closest('[data-stage-menu]');if(item){if(item.disabled)return;const menu=$('#scene-context-menu'),id=Number(menu.dataset.role),op=item.dataset.stageMenu;
    if(menu.dataset.project!==S.project?.id||Number(menu.dataset.talk)!==S.selected)return;
    closeContextMenu();if(op==='initial-position')setInitialPosition(id,item.dataset.axis);else if(op==='add-speaker')addSpeaker(id);else if(op==='remove-speaker')removeSpeaker(id);else if(op==='remove')removeStageRole(id);else if(op==='flip')flipStageRole(id,3005);else if(op==='flip-instant')flipStageRole(id,3007);else if(op==='light-toggle'){
      const state=currentStage();if(state.speakerIds.includes(id))return;const enabled=!state.highlightIds.includes(id);
      mutate('设置人物高光',()=>{const row=talk();row.studioLighting||={};row.studioLighting[id]=enabled;row.highlights=ids(row.highlights).filter(v=>v!==id);if(enabled)row.highlights.push(id);});
    }return;}
  const b=event.target.closest('[data-scene]');if(!b)return;const action=b.dataset.scene;
  if(action==='inspect'){selectStageRole(b.dataset.id);return;}
  if(action==='mode'){scenePlayer?.pause();stageAudio?.stop();sceneMode=b.dataset.mode;renderPreview();return;}
  if(action==='play'){if(linePlayback)stopLinePlayback();else playCurrentLine();return;}
  if(action==='pause'){scenePlayer?.pause();stageAudio?.pause();scenePlayer?.refresh();return;}
  if(action==='next')scenePlayer?.next();else if(action==='back'){stageAudio?.stop();scenePlayer?.back();if(sceneMode==='play')stageAudio?.enter(S.selected,scenePlayer?.trace);}else if(action==='reset'){stageAudio?.stop();scenePlayer?.reset();}
});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('#scene-context-menu'))closeContextMenu();});
$('#editor-scroll').addEventListener('scroll',closeContextMenu,{passive:true});

function audioData(){return S.doc?.audioCues||{version:1,sfx:{},bgm:[]};}
function audioName(id){const row=S.audios.find(a=>Number(a.id)===Number(id));return row?assetName(row,'audio'):'声音 '+id;}
function audioUrl(id){const row=S.audios.find(a=>Number(a.id)===Number(id));return row&&row.available!==false&&(row.assetPath||row.url)?assetUrl(row.assetPath||row.url):null;}
async function loadAudioCatalog() {
  if(!S.project)return;const projectId=S.project.id;S.audioLoading=true;
  try{const data=await api('/api/audio?projectId='+encodeURIComponent(projectId));if(S.project?.id!==projectId)return;S.audios=data.audios||[];S.defaultBgm=data.defaultBgm||null;if(storyPreview&&!scenePlayer?.ended||linePlayback)stageAudio?.enter(S.selected,scenePlayer?.trace);}
  finally{if(S.project?.id===projectId){S.audioLoading=false;const section=$('#audio-section');if(section)section.innerHTML=renderAudioContents();}}
}
function bgmDraft() {
  const cues=audioData(),stamp=JSON.stringify(cues),group=cues.bgm.find(g=>ids(g.talkIds).includes(S.selected));
  if(!S.bgmDraft||S.bgmDraft.talk!==S.selected||S.bgmDraft.stamp!==stamp){const groupIds=new Set(ids(group?.talkIds)),members=group?S.order.filter(id=>groupIds.has(id)):visibleIds().slice(Math.max(0,visibleIds().indexOf(S.selected)));S.bgmDraft={talk:S.selected,stamp,groupId:group?.id||null,track:group?.audioId||0,start:members[0]||S.selected,end:members[members.length-1]||S.selected,loop:group?.loop??true,volume:group?.volume??1,ids:members};}
  return S.bgmDraft;
}
function audioOptions(type,selected=0) {
  let result='<option value="0">'+(type===1?'使用原版默认音乐':'选择音效，即刻加入本句')+'</option>';
  for(const row of S.audios.filter(a=>Number(a.type)===type))result+=`<option value="${row.id}" ${Number(selected)===Number(row.id)?'selected':''}>${h(assetName(row,'audio'))}${row.available===false?'（尚未读取）':''}</option>`;
  return result;
}
function renderAudioContents() {
  if(!talk())return '';const cues=audioData(),sfx=cues.sfx[S.selected]||[],draft=bgmDraft(),legacy=S.audios.find(a=>Number(a.id)===Number(talk().audio)),nativeBgm=Number(cues.nativeAudio?.[S.selected])||(Number(legacy?.type)===1?Number(legacy.id):0);
  let html=`<div class="section-title"><h3>音效与 BGM</h3><button class="text-button" data-action="stop-audio">停止试听</button></div><div class="audio-caption">本句音效</div><div class="audio-pick-row"><button class="primary" data-action="import-audio" data-type="2">＋ 添加音效</button></div>`;
  for(const [index,cue] of sfx.entries())html+=`<div class="audio-cue-row"><span>${h(audioName(cue.audioId))}</span><button data-action="preview-audio" data-id="${cue.audioId}">试听</button><label>音量<input type="range" min="0" max="1" step="0.05" value="${cue.volume??1}" data-sfx-volume="${index}" aria-label="${h(audioName(cue.audioId))} 音量"></label><button class="danger-text" data-action="remove-sfx" data-index="${index}">移除</button></div>`;
  if(nativeBgm)html+=`<div class="audio-caption">原句背景音乐</div><div class="audio-cue-row"><span>${h(audioName(nativeBgm))}</span><button data-action="preview-audio" data-id="${nativeBgm}">试听</button><button class="danger-text" data-action="remove-native-bgm">移除</button></div><p class="helper">从本句开始延续播放。设置范围音乐后会改用范围规则。</p>`;
  html+=`<div class="audio-caption">范围背景音乐</div><div class="audio-range"><label><span>起始对话</span><select id="bgm-range-start">${talkOptions(draft.start,null,false,visibleIds())}</select></label><label><span>结束对话</span><select id="bgm-range-end">${talkOptions(draft.end,null,false,visibleIds())}</select></label></div><div class="audio-pick-row"><button class="primary" data-action="import-audio" data-type="1">♫ ${draft.track?h(audioName(draft.track)):"选择 BGM"}</button></div><div class="audio-range"><label><span>播放方式</span><select id="bgm-loop"><option value="loop" ${draft.loop?'selected':''}>循环播放</option><option value="once" ${draft.loop?'':'selected'}>只播放一次</option></select></label><label><span>音量</span><input id="bgm-volume" type="range" min="0" max="1" step="0.05" value="${draft.volume}"></label></div><div class="row"><button data-action="preview-audio" data-id="${draft.track}" ${draft.track?'':'disabled'}>试听背景音乐</button>${draft.groupId?'<button class="danger-text" data-action="remove-bgm">移除此范围音乐</button>':''}</div><p class="helper">选择即应用。可按起止句选范围，也可勾选不连续对话；从起始句默认应用到本事件末尾，后续句沿用音乐，直到设置另一首。</p>`;
  html+=`<details id="bgm-specific" class="audio-specific" ${S.bgmExpanded?'open':''}><summary>自选对话（${(draft.ids||[]).length} 句，可不连续）</summary><div class="audio-talk-list">${S.bgmExpanded?renderBgmChoices(draft):''}</div></details>`;
  if(audioNeedsPlugin())html+='<p class="helper audio-plugin-notice" role="status">'+h(AUDIO_PLUGIN_NOTICE)+'</p>';
  if(S.audioLoading)html+='<p class="helper">正在读取声音列表…</p>';
  if(S.audios.some(a=>a.available===false))html+='<button class="text-button" data-action="refresh-audio">读取尚未缓存的原版声音</button>';
  if(Number(talk().audio)>0)html+='<p class="helper">背景音乐与音效按原版声音类型保存。</p>';
  return html;
}
function renderBgmChoices(draft=bgmDraft()){const selected=new Set(draft.ids||[]);return (S.project?.readOnly?(draft.ids||[]).slice(0,100):visibleIds()).map(id=>`<label><input type="checkbox" data-bgm-talk="${id}" ${selected.has(id)?'checked':''}><span>${StudentAgeRecordLabels.html(id,talkLabel(id))}</span></label>`).join('');}
function renderAudio(){return '<section id="audio-section" class="audio-section">'+renderAudioContents()+'</section>';}
const AUDIO_PLUGIN_NOTICE='游戏内实现多音轨、单次播放或独立音量需要安装插件；当前版本不附带插件，这些高级设置仅在编辑器预览中生效。普通保存同一句优先保留背景音乐，否则保留一个音效。';
function audioNeedsPlugin(talkIds=[S.selected]){
 const cues=audioData();
 return talkIds.some(id=>{
  const group=cues.bgm.find(g=>ids(g.talkIds).includes(Number(id))),effects=cues.sfx[id]||[],legacy=S.audios.find(a=>Number(a.id)===Number(S.doc?.talks[id]?.audio));
  const effectIds=new Set(effects.map(c=>Number(c.audioId)));if(Number(legacy?.type)===2)effectIds.add(Number(legacy.id));
  const music=group||Number(cues.nativeAudio?.[id])||Number(legacy?.type)===1;
  return effectIds.size>1||effectIds.size>0&&!!music||effects.some(c=>(c.volume??1)!==1)||group&&(group.loop===false||(group.volume??1)!==1);
 });
}
function warnAudioPlugin(talkIds){if(audioNeedsPlugin(talkIds))toast('这些声音设置需要游戏插件；当前版本未附带，仅预览支持。','note');}
function addSfx(id) {
  id=Number(id);if(!id||!talk())return;
  mutate('设置本句音效',()=>{preserveLegacyAudio(S.selected,false);const cues=S.doc.audioCues,rows=cues.sfx[S.selected]||[];if(!rows.some(c=>Number(c.audioId)===id))rows.push({audioId:id,volume:1});cues.sfx[S.selected]=rows;talk().audio=0;});
  warnAudioPlugin();
}
function preserveLegacyAudio(talkId,replacingBgm) {
  const cues=S.doc.audioCues,row=S.doc.talks[talkId],old=S.audios.find(a=>Number(a.id)===Number(row?.audio));
  if(old&&Number(old.type)===2){const list=cues.sfx[talkId]||[];if(!list.some(c=>Number(c.audioId)===Number(old.id)))list.push({audioId:Number(old.id),volume:1});cues.sfx[talkId]=list;}
  if(old&&Number(old.type)===1&&!replacingBgm){cues.nativeAudio=cues.nativeAudio||{};cues.nativeAudio[talkId]=Number(old.id);}
  if(replacingBgm&&cues.nativeAudio)delete cues.nativeAudio[talkId];
}
function applyBgmDraft() {
  const draft={...bgmDraft()},list=visibleIds(),a=list.indexOf(Number(draft.start)),b=list.indexOf(Number(draft.end));
  if(a<0||b<0)return;
  const members=draft.ids||list.slice(Math.min(a,b),Math.max(a,b)+1),covered=new Set(members),groupId=draft.groupId||'bgm-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,7);
  mutate('设置范围背景音乐',()=>{const cues=S.doc.audioCues;cues.bgm=cues.bgm.filter(g=>g.id!==draft.groupId).map(g=>({...g,talkIds:ids(g.talkIds).filter(id=>!covered.has(id))})).filter(g=>g.talkIds.length);
    if(Number(draft.track)>0&&members.length)cues.bgm.push({id:groupId,audioId:Number(draft.track),talkIds:members,loop:!!draft.loop,volume:Number(draft.volume)});
    for(const id of members)if(S.doc.talks[id]){preserveLegacyAudio(id,true);S.doc.talks[id].audio=Number(draft.track)||0;}
    S.bgmDraft={...draft,groupId:Number(draft.track)>0&&members.length?groupId:null,ids:members,stamp:JSON.stringify(cues)};
  });
  warnAudioPlugin(members);
}
async function previewAudio(id) {
  const url=audioUrl(id);if(!url){toast('这段声音尚未读取到本地，请刷新声音资源。','note');return;}
  const player=$('#audio-audition');player.pause();player.src=url;player.controls=true;player.hidden=false;player.loop=false;player.volume=1;
  try{await player.play();}catch(_){toast('声音未能播放，请检查素材。','note');}
}
function stopAudition(){const player=$('#audio-audition');player.pause();player.hidden=true;}
async function importAudioFile(file,type) {
  if(!file||!editable())return;if(file.size>48*1024*1024)throw new Error('声音文件不能超过 48 MB。');
  const projectId=S.project.id,selected=S.selected;if(S.dirty&&!await window.STUDIO_NAV.prepareLeave({allowDiscard:false}))return;
  if(S.project.id!==projectId)return;const importRevision=S.revision;
  const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('声音读取失败。'));reader.readAsDataURL(file);});
  const result=await api('/api/audio-import',{projectId,revision:importRevision,fileName:file.name,data,name:file.name.replace(/\.[^.]+$/,''),type});
  if(S.project.id!==projectId){toast('声音已导入原模组。');return;}S.revision=result.revision;await loadAudioCatalog();
  if(S.selected===selected){if(type===2)addSfx(result.id);else{const draft=bgmDraft();draft.track=Number(result.id);applyBgmDraft();}}
  toast('声音已导入并应用，可以撤销当前播放设置。');warnAudioPlugin();
}
async function refreshAudio() {
  await api('/api/audio-refresh',{});toast('正在读取原版声音。');
  for(let count=0;count<120;count++){await new Promise(r=>setTimeout(r,1500));const status=await api('/api/audio-status');if(!['running','queued'].includes(status.status)){await loadAudioCatalog();toast(status.message||'声音列表已刷新。');break;}}
}

const protagonistGender=()=>StudentAgeScene.protagonistGender(S.doc||{});
const portraitIdentity=id=>StudentAgeScene.portraitIdentity(S.doc||{},id);
const portraitMetadataKey=(id,grade,cloth)=>[S.project?.id,portraitIdentity(id),grade,cloth].join(':');
function setProtagonistGender(value){
 if(!S.doc||![1,2].includes(value)||value===protagonistGender())return;
 stopLinePlayback();scenePlayer?.pause();S.face=0;
 if(S.project?.readOnly){S.doc.protagonistGender=value;invalidateStageMemo();renderPreview();}
 else mutate('设置主角预览性别',()=>{S.doc.protagonistGender=value;});
}
function portraitPath() {
  const p=S.doc?.persons[S.previewRole];if(!p)return {path:null,note:'选择人物后，可以预览已有的本地立绘。'};
  const source=StudentAgeScene.portraitSource(S.doc,{id:Number(S.previewRole),grade:S.grade,cloth:S.cloth,face:S.face});
  return {...source,note:source.missing?'此服装或学段缺少所选表情图片，按游戏备用规则显示。':'人物立绘'};
}
const portraitRequests=new Map(),portraitAvailability=new Map(),scenePortraitRequests=new Set(),scenePortraitStamps=new Map();
function refreshSceneAssets(){
  invalidateStageMemo();
  StudentAgeActionEditor.refresh?.();
  largeScene?.invalidateAssets();
  // A background cache response must not replace an in-progress movement with its final pose.
  if(sceneMode!=='edit'){largeScene?.refreshPortraits();renderInspector();return;}
  const animations=largeScene?.container.getAnimations?.({subtree:true}).filter(a=>a.playState==='running')||[];
  if(animations.length){
    const scene=scenePlayer?.scene;
    Promise.allSettled(animations.map(a=>a.finished)).then(()=>{if(sceneMode==='edit'&&scenePlayer?.scene===scene)renderPreview();});
    renderInspector();return;
  }
  renderPreview();
}
const portraitSizeRequests=new Set();
function prepareSceneExpressions(state){
 const project=S.project?.id,paths=[...new Set(values(state?.roles).filter(r=>r.visible).flatMap(r=>StudentAgeScene.portraitCandidates(S.doc,r)))].filter(p=>p&&!p.startsWith('portrait-cache/')&&!portraitSizeRequests.has(project+':'+p));
 if(paths.length){
  paths.forEach(p=>portraitSizeRequests.add(project+':'+p));
  api('/api/portrait-dimensions',{projectId:project,paths}).then(sizes=>{
   if(S.project?.id!==project)return;
   for(const [path,size] of Object.entries(sizes))StudentAgeScene.portraitSizes.set(path,size);
   if(Object.keys(sizes).length)largeScene?.refreshPortraits();
  }).catch(()=>paths.forEach(p=>portraitSizeRequests.delete(project+':'+p)));
 }

 for(const role of values(state?.roles)){
  const person=S.doc?.persons[role.id];if(!role.visible||!(role.grade===0?person?.l2d:person?.l2d2)?.length)continue;
  const project=S.project?.id,gender=role.id===0?protagonistGender():1,metadataKey=portraitMetadataKey(role.id,role.grade,role.cloth),key=metadataKey+':'+role.face;
  if(scenePortraitRequests.has(key))continue;scenePortraitRequests.add(key);let attempts=0;
  const current=()=>S.project?.id===project&&(role.id!==0||gender===protagonistGender());
  async function check(){
   if(!current()){scenePortraitRequests.delete(key);return;}
   if(attempts&&largeScene?.state){const shown=largeScene.state.roles[role.id];if(!shown?.visible||shown.cloth!==role.cloth||shown.grade!==role.grade||shown.face!==role.face){scenePortraitRequests.delete(key);return;}}
   try{
    const result=await api('/api/portraits',{projectId:project,role:role.id,grade:role.grade,cloth:role.cloth,face:role.face,gender});if(!current()){scenePortraitRequests.delete(key);return;}
    const stamp=JSON.stringify([result.available,result.faces,result.sameAsDefault,result.frame,result.status]);portraitAvailability.set(metadataKey,result);
    if(result.frame)StudentAgeScene.portraitFrames.set(`${portraitIdentity(role.id)}-${role.grade}-${role.cloth}`,result.frame);
    if(stamp!==scenePortraitStamps.get(metadataKey)){scenePortraitStamps.set(metadataKey,stamp);refreshSceneAssets();}
    if(result.status==='error'&&largeScene){largeScene.assetWarnings.set(role.id,personName(role.id)+'：'+result.message+'；稍后自动重试。');renderSceneWarnings([...largeScene.assetWarnings.values()]);}
    if(result.active||result.status==='error'){attempts++;setTimeout(check,result.status==='error'?Math.max(3,result.retryAfter||15)*1000:Math.min(4000,1000+250*attempts));}
    else scenePortraitRequests.delete(key);
   }catch{attempts++;if(current())setTimeout(check,Math.min(15000,1000*Math.pow(2,Math.min(attempts,4))));else scenePortraitRequests.delete(key);}
  }check();
 }
}

function prepareOriginalExpressions() {
  const person=S.doc?.persons[S.previewRole];if(!person||!(S.grade===0?person.l2d:person.l2d2)?.length)return;
  const selected=[S.project?.id,S.previewRole,S.grade,S.cloth,S.face,Number(S.previewRole)===0?protagonistGender():1],key=selected.join(':');
  if(portraitRequests.has(key))return;portraitRequests.set(key,true);
  let attempts=0,previous='';
  async function check(){
    if(selected.join(':')!==[S.project?.id,S.previewRole,S.grade,S.cloth,S.face,Number(S.previewRole)===0?protagonistGender():1].join(':')){portraitRequests.delete(key);return;}
    try{
      const result=await api('/api/portraits',{projectId:selected[0],role:Number(selected[1]),grade:selected[2],cloth:selected[3],face:selected[4],gender:selected[5]});
      if(selected.join(':')!==[S.project?.id,S.previewRole,S.grade,S.cloth,S.face,Number(S.previewRole)===0?protagonistGender():1].join(':')){portraitRequests.delete(key);return;}
      const available=result.available||[],stamp=JSON.stringify([available,result.active,result.faces,result.sameAsDefault,result.frame]);portraitAvailability.set(portraitMetadataKey(Number(selected[1]),selected[2],selected[3]),result);if(result.frame)StudentAgeScene.portraitFrames.set(`${portraitIdentity(Number(selected[1]))}-${selected[2]}-${selected[3]}`,result.frame);
      if(previous!==stamp){previous=stamp;refreshSceneAssets();}
      if(available.includes(S.face)&&!result.active)return;
      if(result.message&&!result.available?.length)$('#portrait-note').title=result.message;
      if(result.active)setTimeout(check,Math.min(4000,1000+250*attempts++));else portraitRequests.delete(key);
    }catch{portraitRequests.delete(key);}
  }
  check();
}
function renderInspector() {
  const p=S.doc?.persons[S.previewRole],t=talk();
  for(const button of $$('[data-action=set-grade]')){button.classList.toggle('active',Number(button.dataset.value)===S.grade);button.setAttribute('aria-pressed',String(Number(button.dataset.value)===S.grade));}
  for(const button of $$('[data-action=set-protagonist-gender]')){button.classList.toggle('active',Number(button.dataset.value)===protagonistGender());button.setAttribute('aria-pressed',String(Number(button.dataset.value)===protagonistGender()));}
  $('#preview-controls').innerHTML=S.doc?`<select data-reference-table="PersonCfg" id="preview-person" data-no-search="true" aria-label="预览人物">${personOptions(S.previewRole)}</select><div class="row"><select id="preview-cloth" aria-label="预览服装">${Array.from({length:10},(_,n)=>`<option value="${n}" ${n===S.cloth?'selected':''}>${n===0?'默认服装':'服装 '+(n+1)}</option>`).join('')}</select></div>`:'';
  if(!S.doc){$('#expression-grid').innerHTML='';return;}
  const asset=portraitPath();
  const previewPaths=p?StudentAgeScene.portraitCandidates(S.doc,{id:Number(S.previewRole),grade:S.grade,cloth:S.cloth,face:S.face}):[];
  const inspector=$('#portrait-inspector'),note=$('#portrait-note'),caption=p?faceName():'',description=asset.missing?caption+' · '+asset.note:caption;note.textContent=description;
  const empty=()=>{const node=document.createElement('div');node.className='empty-portrait';node.innerHTML=`<span class="frame-glyph">⌑</span><strong>${p?h(p.name||'人物'):'选择一个人物'}</strong><p>${p?(asset.hasModel?'正在读取原版人物模型…':'这张图片尚未在本地找到'):'暂无本地立绘'}</p>`;inspector.replaceChildren(node);};
  if(p){ensureScene();largeScene.image(inspector,previewPaths,'preview-character',(p.name||'人物')+' · '+caption,empty,()=>{inspector.querySelector('img')?.setAttribute('data-preview-character','');note.textContent=description;});}
  else if(largeScene)largeScene.image(inspector,[],'','',empty);else empty();
  const availability=portraitAvailability.get(portraitMetadataKey(S.previewRole,S.grade,S.cloth));
  const choices=window.StudentAgeExpressions.choices({person:p,faces:S.doc.faces,roleId:S.previewRole,grade:S.grade,cloth:S.cloth,metadata:availability});
  $('#expression-grid').innerHTML=choices.map(({id,name})=>`<button class="${id===S.face?'active':''}" data-action="set-face" data-value="${id}" title="${h(name)}"><span>${h(name)}</span></button>`).join('');
  prepareOriginalExpressions();
  $('#expression-current').textContent=p?faceName():'';$$('#expression-grid button').forEach(b=>b.disabled=!p||S.previewRole===null);
}
function updatePreviewText() {
  const t=talk();if(!t)return;const name=speaker(t),content=t.content||'';
  for(const state of [largeScene?.state,scenePlayer?.scene])if(state?.talkId===S.selected){state.content=content;state.speaker=name;}
  for(const node of $$('#large-scene .scene-speaker-name strong,.preview-caption strong'))node.textContent=name;
  for(const node of $$('#large-scene .scene-dialogue p,.preview-caption p'))node.textContent=content||'输入对话内容';
}
function updateTalkTextCard(){
  if(S.search){renderList();return;}
  const card=$('#talk-list .talk-card[data-id="'+S.selected+'"]');if(!card)return;const t=talk(),name=speaker(t);
  card.querySelector('.talk-snippet').textContent=t.content||'空白对话';card.querySelector('strong').innerHTML=StudentAgeRecordLabels.html(t.id,name);card.querySelector('.speaker-dot').textContent=name.slice(0,1);
}


const actions={
  'refresh-projects':()=>refreshProjects(),'create-project':()=>unsaved(()=>newProject(false)),'copy-project':()=>newProject(true),'save':save,'undo':undo,'redo':redo,
  'talk-page':b=>{S.listStart=Number(b.dataset.start);renderList();$('#talk-list').scrollTop=0;},
  'retry-conditions':()=>loadConditionCatalog(),'select-talk':b=>selectTalk(b.dataset.id),'add-blank-talk':()=>addTalk(false,{blank:true}),'add-talk':()=>addTalk(false),'duplicate-talk':()=>addTalk(true),'delete-talk':deleteTalk,'move-up':()=>moveTalk(-1),'move-down':()=>moveTalk(1),
  'toggle-folder':b=>toggleFolder(b.dataset.folderKey),'folder-add-blank':b=>addFolderTalk(b.dataset.folderKey,false,null,{blank:true}),'folder-add':b=>addFolderTalk(b.dataset.folderKey),'reveal-folder':b=>{S.folderOpen[b.dataset.folderKey]=true;renderList();document.querySelector('[data-folder="'+b.dataset.folderKey+'"]')?.scrollIntoView({block:'nearest'});},
  'history-export':showHistoryExport,
  'dialogue-import':showDialogueImport,
  'preview-story':openStoryPreview,
  'action-editor':openActionEditor,'edit-paper':editPaper,
  'create-event':()=>{window.STUDIO_OPEN_EVENTS();createEvent();},'event-details':()=>eventDetails(),'event-list':()=>window.STUDIO_OPEN_EVENTS(),'add-option':addOption,'delete-option':b=>deleteOption(Number(b.dataset.id)),
  'add-branch':addConditionalBranch,'delete-branch':b=>deleteFolder(b.dataset.folderKey),'branch-conditions':b=>openConditionSettings('talks',Number(b.dataset.id),'check','分支触发条件'),'option-limit':b=>openConditionSettings('options',Number(b.dataset.id),'precondition','选项可用条件'),'option-check':b=>openConditionSettings('options',Number(b.dataset.id),'check','选项成功判定'),
  'jump-next':()=>{const id=ids(talk()?.nextTalk)[0];if(id&&S.doc.talks[id])selectTalk(id);else toast('这里是本段对话的结束。','note');},
  'open-scene':()=>openScene(),'edit-fields':()=>$('#editor-content').scrollIntoView({behavior:'smooth',block:'start'}),
  'pick-person':()=>pickScenePerson(),'pick-background':()=>openAssetPicker('background',{intent:'background'}),'pick-cg':()=>{if(Number(talk()?.screenEffect?.[0])===4015)openAssetPicker('cg',{intent:'replace-cg'});},'add-cg':()=>openAssetPicker('cg',{intent:'add-cg'}),'folder-add-cg':b=>openAssetPicker('cg',{intent:'add-cg',folderKey:b.dataset.folderKey}),
  'screen-effect':editScreenEffect,'screen-effect-clear':()=>mutate('移除屏幕效果',()=>talk().screenEffect=[]),'speaker-add':b=>openSpeakerPicker(b),'speaker-remove':b=>removeSpeaker(Number(b.dataset.id)),
  'clear-bg':()=>mutate('沿用上一句背景',()=>talk().bg=0),'clear-cg':()=>mutate('结束 CG',()=>{talk().screenEffect=[4017];S.previewCG=false;}),
  'delete-action':b=>mutate('删除动作',()=>talk().roles.splice(Number(b.dataset.index),1)),
  'preview-action':b=>{const row=talk().roles[Number(b.dataset.index)];selectStageRole(row[0]);},
  'set-position':b=>mutate('调整登场位置',()=>{talk().roles[Number(b.dataset.index)][3]=Number(b.dataset.value);}),
  'set-protagonist-gender':b=>setProtagonistGender(Number(b.dataset.value)),
  'set-face':b=>{S.face=Number(b.dataset.value);S.previewCG=false;if(S.project?.readOnly)renderInspector();else applyExpression();},'set-grade':b=>setEventGrade(b.dataset.value),'apply-expression':applyExpression,
  'preview-audio':b=>previewAudio(Number(b.dataset.id)),'stop-audio':stopAudition,'refresh-audio':refreshAudio,
  'import-audio':b=>openAssetPicker('audio',{intent:'audio',audioType:Number(b.dataset.type)}),
  'remove-sfx':b=>mutate('移除本句音效',()=>{const cues=S.doc.audioCues.sfx[S.selected]||[];cues.splice(Number(b.dataset.index),1);if(!cues.length)delete S.doc.audioCues.sfx[S.selected];}),
  'remove-bgm':()=>{const id=bgmDraft().groupId;mutate('移除范围背景音乐',()=>{const group=S.doc.audioCues.bgm.find(g=>g.id===id);for(const talkId of ids(group?.talkIds)){preserveLegacyAudio(talkId,true);if(S.doc.talks[talkId])S.doc.talks[talkId].audio=0;}S.doc.audioCues.bgm=S.doc.audioCues.bgm.filter(g=>g.id!==id);});},
  'remove-native-bgm':()=>mutate('移除原句背景音乐',()=>{preserveLegacyAudio(S.selected,true);talk().audio=0;}),
  'help':()=>window.STUDIO_NAV?.help()
};
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
  const action=actions[button.dataset.action];if(action)Promise.resolve().then(()=>action(button)).catch(fail);
});
let talkDrag=null;
function closeTalkMenu(){document.querySelector('#talk-context-menu')?.remove();}
document.addEventListener('contextmenu',event=>{
 const title=event.target.closest('#talk-list .branch-folder-title');
 if(title){event.preventDefault();closeTalkMenu();const key=title.dataset.folderKey,menu=document.createElement('div');menu.id='talk-context-menu';menu.className='talk-context-menu';menu.setAttribute('role','menu');const conditional=title.closest('.conditional-folder');const folderRow=S.branchFolders[key];menu.innerHTML=(conditional&&folderRow?'<button role="menuitem" data-folder-menu="conditions">触发条件…</button>':'')+'<button role="menuitem" data-folder-menu="add">添加对话</button><button role="menuitem" class="danger-text" data-folder-menu="delete">'+(conditional?'删除分支':'删除对话夹')+'</button>';document.body.append(menu);menu.style.left=Math.max(8,Math.min(event.clientX,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(event.clientY,innerHeight-menu.offsetHeight-8))+'px';menu.querySelectorAll('button').forEach(b=>b.disabled=!!S.project?.readOnly);menu.addEventListener('click',e=>{const op=e.target.closest('[data-folder-menu]')?.dataset.folderMenu;if(!op)return;closeTalkMenu();try{if(op==='delete')deleteFolder(key);else if(op==='add')addFolderTalk(key);else if(op==='conditions'){const f=S.branchFolders[key];if(f)openConditionSettings('talks',f.routerId,'check','分支'+f.branchId+' · 触发条件');}}catch(error){fail(error);}});return;}
 const card=event.target.closest('#talk-list .talk-card');if(!card)return;event.preventDefault();selectTalk(card.dataset.id);closeTalkMenu();
 const menu=document.createElement('div');menu.id='talk-context-menu';menu.className='talk-context-menu';menu.setAttribute('role','menu');
 const autoNumbered=!!renumberableEvent();
 menu.innerHTML=(autoNumbered?'':'<button role="menuitem" data-record-table="TalkCfg" data-record-id="'+S.selected+'">修改对话编号</button>')+(S.pinned.talks.has(Number(S.selected))?'<button role="menuitem" data-talk-menu="unpin">恢复自动编号</button>':'')+'<button role="menuitem" data-talk-menu="add-option">添加选项…</button><button role="menuitem" data-talk-menu="add-branch">添加条件分支…</button><button role="menuitem" data-talk-menu="jump">跳转到…</button><button role="menuitem" data-talk-menu="duplicate">创建副本</button><button role="menuitem" class="danger-text" data-talk-menu="delete">删除对话</button>';document.body.append(menu);
 menu.style.left=Math.max(8,Math.min(event.clientX,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(event.clientY,innerHeight-menu.offsetHeight-8))+'px';
 menu.addEventListener('click',e=>{const op=e.target.closest('[data-talk-menu]')?.dataset.talkMenu;if(!op)return;closeTalkMenu();try{if(op==='duplicate')addTalk(true);else if(op==='delete')deleteTalk();else if(op==='add-option')addOptionWithSettings();else if(op==='add-branch')addConditionalBranch();else if(op==='jump')openJumpPicker(S.selected);else if(op==='unpin')unpinId('talks',S.selected);}catch(error){fail(error);}});
});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('#talk-context-menu'))closeTalkMenu();});
document.addEventListener('input',e=>{if(e.target.matches('[data-speaker-name]'))setSpeakerName(e.target.value);});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeTalkMenu();});
function clearTalkDrop(){document.querySelectorAll('.talk-drop-before,.talk-drop-after').forEach(n=>n.classList.remove('talk-drop-before','talk-drop-after'));}
document.addEventListener('dragstart',e=>{const card=e.target.closest('#talk-list .talk-card');if(!card||S.project?.readOnly)return;closeTalkMenu();talkDrag=Number(card.dataset.id);e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',String(talkDrag));card.classList.add('talk-dragging');});
document.addEventListener('dragover',e=>{
 if(talkDrag===null)return;const card=e.target.closest('#talk-list .talk-card');clearTalkDrop();if(!card||Number(card.dataset.id)===talkDrag)return;e.preventDefault();e.dataTransfer.dropEffect='move';const rect=card.getBoundingClientRect();card.classList.add(e.clientY>rect.top+rect.height/2?'talk-drop-after':'talk-drop-before');
 const list=$('#talk-list'),bounds=list.getBoundingClientRect();if(e.clientY<bounds.top+45)list.scrollTop-=18;else if(e.clientY>bounds.bottom-45)list.scrollTop+=18;
});
document.addEventListener('drop',e=>{if(talkDrag===null)return;e.preventDefault();const card=e.target.closest('#talk-list .talk-card'),source=talkDrag;talkDrag=null;const after=card?.classList.contains('talk-drop-after');clearTalkDrop();if(card)try{reorderTalk(source,Number(card.dataset.id),after);}catch(error){fail(error);}});
document.addEventListener('dragend',()=>{talkDrag=null;clearTalkDrop();document.querySelectorAll('.talk-dragging').forEach(n=>n.classList.remove('talk-dragging'));});
document.addEventListener('input',event=>{
  const e=event.target;
  if(e.dataset.sfxVolume!==undefined){if(!editable())return;history('调整音效音量','sfx-volume:'+S.selected+':'+e.dataset.sfxVolume);S.doc.audioCues.sfx[S.selected][Number(e.dataset.sfxVolume)].volume=Number(e.value);updateDirty();return;}
  if(e.id==='talk-search'){S.search=e.value;S.listStart=0;S.listAnchor=S.selected;renderList();return;}
  if(e.dataset.edit&&e.tagName!=='SELECT'&&talk()){
    if(!editable())return;history('编辑对话文字','text:'+S.selected+':'+e.dataset.edit);talk()[e.dataset.edit]=e.value;updateTextDirty();updateTalkTextCard();updatePreviewText();if(e.dataset.edit==='content'){const count=$('#character-count');if(count)count.textContent=e.value.length+' 字';}return;
  }
  if(e.dataset.optionField&&e.tagName!=='SELECT'){
    if(!editable())return;const o=S.doc.options[e.dataset.optionId];if(!o)return;history('编辑选项文字','option:'+o.id);o[e.dataset.optionField]=e.value;updateDirty();renderList();return;
  }
  if(e.dataset.arg&&e.type==='range'){
    if(!editable())return;const i=Number(e.dataset.actionIndex),arg=Number(e.dataset.arg);history('调整动作参数','arg:'+S.selected+':'+i+':'+arg);const row=talk().roles[i];while(row.length<=arg)row.push(0);row[arg]=Number(e.value);updateDirty();const output=$('#range-'+i+'-'+arg);if(output)output.textContent=Number(e.value).toFixed(Number(e.step)>=1?0:1)+(e.dataset.unit||'');
  }
});
document.addEventListener('change',event=>{
  const e=event.target;S.coalesce=null;
  if(e.dataset.folderFailure){try{setFolderFailure(e.dataset.folderFailure,e.value);}catch(error){fail(error);renderList();}return;}
  if(e.dataset.folderContinuation){try{setFolderContinuation(e.dataset.folderContinuation,e.value);}catch(error){fail(error);renderList();}return;}
  if(e.dataset.bgmTalk!==undefined){const draft=bgmDraft(),member=Number(e.dataset.bgmTalk),members=new Set(draft.ids||[]);if(e.checked)members.add(member);else members.delete(member);draft.ids=visibleIds().filter(id=>members.has(id));if(draft.ids.length){draft.start=draft.ids[0];draft.end=draft.ids[draft.ids.length-1];}if(draft.track||draft.groupId)applyBgmDraft();return;}
  if(e.dataset.sfxVolume!==undefined){warnAudioPlugin();const section=$('#audio-section');if(section)section.innerHTML=renderAudioContents();return;}
  if(e.id==='sfx-add'){if(Number(e.value)>0)addSfx(e.value);return;}
  if(['bgm-track','bgm-loop','bgm-volume','bgm-range-start','bgm-range-end'].includes(e.id)){
    const draft=bgmDraft();if(e.id==='bgm-track')draft.track=Number(e.value);else if(e.id==='bgm-loop')draft.loop=e.value==='loop';else if(e.id==='bgm-volume')draft.volume=Number(e.value);else {draft[e.id==='bgm-range-start'?'start':'end']=Number(e.value);draft.ids=null;}
    if(draft.track||draft.groupId)applyBgmDraft();return;
  }
  if(e.id==='audio-file'){const file=e.files[0];e.value='';importAudioFile(file,S.audioImportType||2).catch(fail);return;}
  if(e.id==='project-select'){const id=e.value;e.value=S.project?.id||'';if(id&&String(id)!==String(S.project?.id))unsaved(()=>selectProjectHome(id)).catch(fail);return;}
  if(e.id==='event-select'){if(S.doc?.events[e.value])enterEvent(e.value);return;}
  if(['preview-person','scene-person-select'].includes(e.id)){selectStageRole(e.value);return;}
  if(e.id==='scene-quick-action'){if(e.value!=='')quickApplyAction(e.value);return;}
  if(e.id==='preview-cloth'){S.cloth=Number(e.value);if(S.project?.readOnly){renderInspector();return;}if(S.previewRole!==null)mutate('更换服装',()=>setRoleCommand(talk(),Number(S.previewRole),3006,[S.cloth]));return;}
  if(e.dataset.edit&&e.tagName==='SELECT'&&talk()){
    mutate(e.dataset.edit==='speaker'?'设置说话人物':'设置下一句',()=>{const t=talk();if(e.dataset.edit==='speaker'){t.roleIds=e.value==='narrator'?[]:[Number(e.value)];t.roleName='';if(e.value!=='narrator')S.previewRole=Number(e.value);}else {const field=e.dataset.edit;if(e.dataset.targetSex!==undefined){t[field]=ids(t[field]);t[field][Number(e.dataset.targetSex)]=Number(e.value);}else t[field]=Number(e.value)?[Number(e.value)]:[];const folder=S.branchFolders[Branches.ownedBy(S.branchFolders,t.id)];if(field==='nextTalk'&&folder&&ids(folder.talkIds).at(-1)===t.id)folder.continuation=Number(e.value)?{kind:'talk',talkId:Number(e.value)}:{kind:'end'};}});return;
  }
  if(e.dataset.optionField&&e.tagName==='SELECT'){
    mutate('设置选项去向',()=>{const o=S.doc.options[e.dataset.optionId],field=e.dataset.optionField;if(e.dataset.targetSex!==undefined){o[field]=ids(o[field]);o[field][Number(e.dataset.targetSex)]=Number(e.value);}else o[field]=Number(e.value)?[Number(e.value)]:[];if(field==='talkId')for(const f of Object.values(S.branchFolders))if(Number(f.optionId)===Number(o.id)&&!f.talkIds?.length)f.continuation=Number(e.value)?{kind:'talk',talkId:Number(e.value)}:{kind:'end'};});return;
  }
  if(e.dataset.arg&&e.tagName==='SELECT')mutate('调整动作参数',()=>{const row=talk().roles[Number(e.dataset.actionIndex)],arg=Number(e.dataset.arg);while(row.length<=arg)row.push(0);row[arg]=Number(e.value);});
});
document.addEventListener('toggle',event=>{if(event.target.id==='bgm-specific'&&event.target.isConnected){S.bgmExpanded=event.target.open;const list=event.target.querySelector('.audio-talk-list');if(S.bgmExpanded&&!list.children.length)list.innerHTML=renderBgmChoices();}if(event.target.id==='dialogue-actions'&&event.target.isConnected)S.actionsExpanded=event.target.open;},true);
document.addEventListener('focusout',event=>{if(event.target.matches('input,textarea'))S.coalesce=null;});
document.addEventListener('keydown',event=>{
  if(event.target.closest('#json-editor'))return;
  if(storyPreview){if(storyExitDialog.open)return;if(event.key==='Shift'&&!event.repeat){event.preventDefault();toggleStoryAuto();}else if(event.key==='Tab'){event.preventDefault();if($('#story-history').open)closeStoryHistory();else openStoryHistory();}else if(event.key==='Escape'){event.preventDefault();if(!event.repeat)requestStoryExit();}else if(event.key==='ArrowUp'||event.key==='ArrowDown'){event.preventDefault();scrollStoryHistory(event.key==='ArrowUp'?-1:1);}return;}
  if(document.querySelector('#action-editor[open]'))return;
  if(document.querySelector('#workshop:not([hidden])'))return;
  const command=event.metaKey||event.ctrlKey,key=event.key.toLowerCase(),editing=event.target.matches('input,textarea,[contenteditable=true]');
  if(window.STUDIO_EVENTS?.isOpen?.()){
    if(command&&key==='s'){event.preventDefault();if($('#modal').open)toast('先应用或关闭事件设置，再保存模组。','note');else window.STUDIO_SAVE_EVENT_CHANGES().catch(fail);}
    else if(command&&key==='f'&&!$('#modal').open){event.preventDefault();$('#event-search')?.focus();}
    else if(command&&key==='z'&&!editing&&!$('#modal').open){event.preventDefault();event.shiftKey?redo():undo();}
    else if(command&&key==='y'&&!editing&&!$('#modal').open){event.preventDefault();redo();}
    return;
  }
  if(event.key==='Escape'&&!$('#scene-context-menu').hidden){event.preventDefault();closeContextMenu();return;}
  if(event.target.closest('#large-scene')&&!editing&&!event.target.closest('button,select,[role=combobox]')){
    if(key===' '){event.preventDefault();$('[data-scene="play"]').click();return;}
  }
  if(command&&key==='s'){event.preventDefault();save().catch(fail);return;}
  if(command&&key==='f'&&!$('#modal').open){event.preventDefault();$('#talk-search').focus();$('#talk-search').select();return;}
  if(command&&key==='z'&&!editing&&!$('#modal').open){event.preventDefault();event.shiftKey?redo():undo();return;}
  if(command&&key==='y'&&!editing&&!$('#modal').open){event.preventDefault();redo();return;}
  if(!editing&&!$('#modal').open&&(key==='delete'||key==='backspace')&&talk()){event.preventDefault();if(event.target.closest('#large-scene')&&S.previewRole!==null)removeStageRole(S.previewRole);else deleteTalk();}
});
window.addEventListener('beforeunload',event=>{if(S.dirty){event.preventDefault();event.returnValue='当前模组还有未保存的修改。';}});
window.STUDIO_HAS_UNSAVED_CHANGES=()=>S.dirty;
window.STUDIO_CURRENT_PROJECT=()=>S.project?.id||null;
window.STUDIO_BACKUP_PROJECT=async()=>{if(!editable())throw Error('请先打开可编辑的本地模组。');const result=await api('/api/backup',{projectId:S.project.id,kind:'manual',requestId:crypto.randomUUID()});toast(result.warning||'手动备份已完成，可在工坊设置中查看备份文件夹。',result.warning?'note':undefined);return result;};
window.STUDIO_PROJECTS=()=>S.projects;
window.STUDIO_REFRESH_PROJECTS=()=>refreshProjects();
window.STUDIO_NEW_PROJECT=copy=>newProject(!!copy);
window.STUDIO_PAUSE_PREVIEW=()=>{StudentAgeActionEditor.close();stopLinePlayback();closeStoryPreview();scenePlayer?.pause();stageAudio?.stop();stopAudition();};
async function selectProjectHome(id,keepSource=false){
 if(S.dirty)throw Error('请先保存当前剧情草稿。');const project=availableProject(id);if(!project)throw Error('模组已不在列表中，请刷新。');
 if(!keepSource)window.STUDIO_ORIGINAL_SOURCE.set(null);
 window.STUDIO_PAUSE_PREVIEW?.();scenePlayer?.dispose();scenePlayer=null;window.STUDIO_EVENTS?.close();
 ++projectLoadSequence;StudentAgeScene.portraitSizes.clear();portraitSizeRequests.clear();S.project=project;S.doc=null;S.localIds={};S.conditionRefs={};S.deferredProject=true;S.selected=null;S.event='all';S.revision=null;S.undo=[];S.redo=[];S.saved='';S.order=[];S.premises={};S.branchFolders={};S.conditionsLoading=false;
 localStorage.setItem('studentAgeStudio.project',String(id));renderProjects();renderChrome();
 await window.STUDIO_OPEN_WORKSHOP();window.dispatchEvent(new CustomEvent('studio-project-ready'));return true;
}
window.STUDIO_SELECT_PROJECT=selectProjectHome;
window.STUDIO_SET_ORIGINAL_MODE=async value=>{
 const id=S.project?.id;if(!id||!isLocalProject(availableProject(id)))throw Error('请先选择可编辑的本地模组。');
 const before=window.STUDIO_ORIGINAL_MODE();window.STUDIO_ORIGINAL_SOURCE.set(value?id:null);
 try{await selectProjectHome(id,true);}catch(error){window.STUDIO_ORIGINAL_SOURCE.set(before?id:null);await selectProjectHome(id,true);throw error;}
};
window.STUDIO_OPEN_EDITOR=async()=>window.STUDIO_OPEN_EVENTS();
window.STUDIO_EVENT_CONTEXT=()=>({project:S.project,doc:S.doc,currentEvent:S.event,readOnly:!!S.project?.readOnly,dirty:S.dirty,saving:S.saving,conditionTemplates:allConditionTemplates(),conditionRefs:S.conditionRefs,conditionsReady:!S.conditionsLoading,unassignedTalkIds:unassignedTalkIds()});
window.STUDIO_OPEN_EVENTS=()=>{if(!S.project)return false;window.STUDIO_PAUSE_PREVIEW();closeContextMenu();window.STUDIO_EVENTS.open();return true;};
window.STUDIO_CREATE_EVENT=createEvent;
window.STUDIO_OVERRIDE_ORIGINAL_EVENT=async id=>{
 if(!editable())throw Error('请先打开可编辑的本地模组。');const projectId=S.project.id;
 const data=await api('/api/table?'+new URLSearchParams({projectId,name:'EvtCfg'}));
 if(S.project?.id!==projectId)throw Error('模组已切换，请重新选择。');
 const original=data.referenceRows?.[id];if(!original)throw Error('原版事件未找到。');
 if(!S.doc.events[id])mutate('覆盖原版事件',()=>{S.doc.events[id]=clone(original);});
 window.STUDIO_EVENTS?.refresh();return true;
};
window.STUDIO_RESTORE_ORIGINAL_EVENT=async id=>{
 if(!editable())throw Error('请先打开可编辑的本地模组。');const projectId=S.project.id;
 const data=await api('/api/table?'+new URLSearchParams({projectId,name:'EvtCfg'}));
 if(S.project?.id!==projectId||!data.referenceRows?.[id])throw Error('原版事件已变化，请重新选择。');
 mutate('撤销原版事件覆盖',()=>{delete S.doc.events[id];if(Number(S.event)===Number(id)){S.event=null;S.selected=null;S.activeFolder=null;}});
 window.STUDIO_EVENTS?.refresh();return true;
};
window.STUDIO_EDIT_EVENT=eventDetails;
window.STUDIO_ENTER_EVENT=enterEvent;
window.STUDIO_DELETE_EVENT=deleteEvent;
window.STUDIO_SAVE_EVENT_CHANGES=async()=>{const result=await save();window.STUDIO_EVENTS?.refresh();return result;};
window.STUDIO_REFRESH_CURRENT_PROJECT=async(force=false)=>{if(S.project&&(!S.deferredProject||force))await loadProject(S.project.id,!S.deferredProject);};
window.STUDIO_REUSE_CONTEXT=()=>({project:S.project,revision:(S.deferredProject?window.STUDIO_WORKSHOP_NAV?.assetContext?.(S.project?.id)?.revision:S.revision)??S.revision,selected:S.selected,previewRole:S.previewRole,grade:S.grade,cloth:S.cloth,face:S.face});
window.STUDIO_PREPARE_ASSET_REUSE=async()=>{
 if(!editable())return null;
 const docs=[S.doc,...S.undo.map(v=>v.doc),...S.redo.map(v=>v.doc)],reserved=new Set();
 for(const doc of docs)for(const key of MAPS)for(const id of Object.keys(doc?.[key]||{})){const n=Number(id);if(Number.isInteger(n)&&n>=0){reserved.add(n);if(key==='faces')reserved.add(Math.floor(n/1000));}}
 return {...window.STUDIO_REUSE_CONTEXT(),reservedIds:[...reserved],reservedCgIds:[...new Set(docs.flatMap(doc=>Object.keys(doc?.cgs||{})).map(Number).filter(id=>id>0))]};
};
function mergeImportedAssets(result){
 const currentRevision=window.STUDIO_REUSE_CONTEXT().revision;
 if(currentRevision===result.revision)return;
 if(currentRevision!==result.previousRevision)throw Error('导入期间模组版本发生变化，当前草稿已保留。请重新打开素材目录。');
 if(!result.importDelta)throw Error('导入结果缺少素材增量，当前草稿已保留。');
 const aliases={PersonCfg:'persons',ModFaceCfg:'faces',BgCfg:'backgrounds',CGCfg:'cgs',PaperCfg:'papers',ItemCfg:'items',BookCfg:'books'};
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 const plans=[];
 function plan(doc,saved=false){if(!doc)return;const edits=[];for(const [table,delta] of Object.entries(result.importDelta)){
   const key=aliases[table];if(!key)continue;
   for(const [id,row]of Object.entries(delta.after||{})){
    const before=delta.before?.[id],draft=doc[key]?.[id];
    if(before==null&&draft&&!same(draft,row))throw Error('导入编号与当前草稿重复，当前草稿已保留。');
    let merged=clone(row);
    if(!saved&&draft&&before){merged=clone(draft);for(const [field,value]of Object.entries(row))if(!same(value,before[field])&&(same(draft[field],before[field])||!Object.hasOwn(draft,field)))merged[field]=clone(value);}
    // Preserve a deliberately deleted draft row; saved state still learns the import.
    if(!saved&&before&&!draft)continue;
    edits.push({key,id,row:merged});
   }
  }plans.push({doc,edits});}
 const saved=S.saved?IndexedTalks.parse(S.saved):null;
 plan(S.doc);for(const entry of [...S.undo,...S.redo])plan(entry.doc);if(saved)plan(saved[0],true);
 for(const {doc,edits}of plans)for(const {key,id,row}of edits){doc[key]??={};doc[key][id]=row;}
 if(saved)S.saved=IndexedTalks.stringify(saved);
 for(const [table,delta]of Object.entries(result.importDelta)){
  const key=aliases[table];if(key)S.localIds[key]=[...new Set([...(S.localIds[key]||[]),...Object.keys(delta.after).map(Number)])];
  if(S.conditionRefs?.[table])Object.assign(S.conditionRefs[table],clone(delta.after));
 }
 const previousRevision=currentRevision;S.revision=result.revision;updateDirty();
 window.dispatchEvent(new CustomEvent('studio-assets-imported',{detail:{projectId:S.project.id,previousRevision,revision:S.revision,importDelta:result.importDelta}}));
}
if(window.webkit?.messageHandlers?.studioAssetFolder){
  const requests=new Map();
  window.STUDIO_CHOOSE_ASSET_FOLDER=kind=>new Promise((resolve,reject)=>{
    if(!['portrait','background','cg','audio','social','avatar','mods','game','cache'].includes(kind)){reject(Error('未知文件夹类型。'));return;}
    const id=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);requests.set(id,resolve);
    window.webkit.messageHandlers.studioAssetFolder.postMessage({id,kind});
  });
  window.STUDIO_ASSET_FOLDER_CHOSEN=({id,path})=>{const resolve=requests.get(id);if(resolve){requests.delete(id);resolve(typeof path==='string'?path:null);}};
}
window.STUDIO_PICKER_CONTEXT=()=>({...window.STUDIO_REUSE_CONTEXT(),doc:S.doc,localIds:S.localIds,event:S.event,folderKey:S.activeFolder});
function openAssetPicker(kind,options={}) {
  if(!editable())return;
  if(options.intent==='add-cg'&&!S.doc?.events[S.event]){toast('先选择一个事件，再添加 CG。','note');return;}
  if(options.intent!=='add-cg'&&!talk()){toast('先添加或选择一句对话。','note');return;}
  return window.STUDIO_ASSET_PICKER.open(kind,{...options,selected:S.selected,event:S.event,folderKey:options.folderKey??S.activeFolder});
}
async function pickScenePerson(){
 if(!editable()||!talk())return;
 const selected=S.selected,projectId=S.project.id;
 await openAssetPicker('portrait',{multiple:true,selectPerson:true,selectFromDocument:true,
  excludePersonIds:()=>S.goalImageIds,
  onUse:picked=>{if(S.project?.id!==projectId||S.selected!==selected)return false;
   const id=Number(picked.personId);if(!S.doc.persons[id]||S.goalImageIds.map(String).includes(String(id)))return false;
   enterSceneRole(id);syncFaceFromTalk();return true;}});
}
window.STUDIO_USE_PICKED_ASSET=async(result,options={})=>{
  if(!S.project||String(S.project.id)!==String(result.projectId))throw Error('当前模组已切换。素材已导入原模组时，可在原模组的自添加目录中找到。');
  if(options.intent==='library'){if(result.imported)mergeImportedAssets(result);return true;}
  if(options.selected!==undefined&&S.selected!==options.selected)throw Error('当前对话已变化，请重新选择素材。');
  const selected=S.selected,event=S.event,folder=options.folderKey??S.activeFolder,
    pendingBgm=result.kind==='audio'&&Number(options.audioType||result.row?.type)===1?clone(bgmDraft()):null;
  if(result.imported)mergeImportedAssets(result);
  // Merge only committed resource rows; insertion remains part of the draft.
  S.selected=selected;S.event=event;S.activeFolder=folder&&S.branchFolders[folder]?folder:null;
  if(pendingBgm)S.bgmDraft={...pendingBgm,stamp:JSON.stringify(audioData())};
  const kind=result.kind,id=Number(result.personId??result.id);if(!Number.isFinite(id)||id<0)throw Error('素材编号无效。');
  if(kind==='portrait'){
    if(!S.doc.persons[id])throw Error('人物尚未载入，请重新打开素材目录。');
    if(result.grade!=null){S.doc.eventGrades||={};S.doc.eventGrades[S.event]=Math.max(0,Math.min(1,Number(result.grade)-1));S.grade=S.doc.eventGrades[S.event];}
    S.previewRole=id;enterSceneRole(id,{cloth:result.cloth==null?undefined:Number(result.cloth)});syncFaceFromTalk();
  }else if(kind==='background'){
    if(!S.doc.backgrounds[id])throw Error('场景尚未载入，请重新打开素材目录。');
    mutate('设置场景',()=>{if(phoneEvent())configurePhone(phoneEvent(),Number(phoneEvent().npc)||0,id);else talk().bg=id;});
  }else if(kind==='cg'){
    if(!S.doc.cgs[id])throw Error('CG 尚未载入，请重新打开素材目录。');
    if(options.intent==='add-cg'){
      if(folder){const description=folderDescription(folder);if(!description.option)throw Error('选项对话夹已变化，请重新选择。');addFolderTalk(folder,false,selected,{cgId:id});}
      else addTalk(false,{cgId:id});
    }else mutate('更换 CG',()=>talk().screenEffect=[4015,id]);
  }else if(kind==='audio'){
    await loadAudioCatalog();
    if(Number(options.audioType||result.row?.type)===1){const draft=bgmDraft();S.bgmDraft={...draft,track:id};applyBgmDraft();}else addSfx(id);
  }
  sceneMode='edit';render();$('#editor-scroll').scrollTo({top:0});

};

window.STUDIO_SAVE_CURRENT=save;
window.STUDIO_COMMIT_OPEN_EDITOR=commitOpenEditor;
window.STUDIO_HAS_OPEN_DRAFT=()=>!!($('#modal').open&&pendingModalSave);
window.STUDIO_DISCARD_STORY=()=>{
 closeModal();if(!S.dirty)return;
 const [doc,order,deleted,replacements,premises,branchFolders]=IndexedTalks.parse(S.saved);
 S.undo=[];S.redo=[];restore({doc,order,deleted,replacements,premises,branchFolders,selected:doc.talks[S.selected]?S.selected:order[0]||null,event:S.event==='all'||doc.events[S.event]?S.event:'all'});window.STUDIO_EVENTS?.refresh();
};
window.STUDIO_BEFORE_WORKSHOP=async()=>{if(!S.project)return false;const options={dirty:()=>S.dirty||window.STUDIO_HAS_OPEN_DRAFT(),save:async()=>{await commitOpenEditor();return !S.dirty||await save();},discard:window.STUDIO_DISCARD_STORY};return window.STUDIO_NAV?window.STUDIO_NAV.prepareLeave(options):options.save();};
window.STUDIO_REQUEST_CLOSE=async()=>{await commitOpenEditor();const deadline=Date.now()+45000;while(S.saving||S.projectOpening){if(Date.now()>deadline)throw Error('读取或保存尚未完成，请稍后重试。');await new Promise(r=>setTimeout(r,50));}return !S.dirty||await save();};
window.STUDIO_STORY_NAV={
 capture:()=>({event:S.event,selected:S.selected,activeFolder:S.activeFolder,folderOpen:clone(S.folderOpen),search:S.search,listStart:S.listStart,previewRole:S.previewRole}),
 busy:()=>S.projectOpening||S.saving,
 restore:state=>{scenePlayer?.dispose();scenePlayer=null;stageAudio?.stop();sceneMode='edit';S.event=state.event==='all'||S.doc.events[state.event]?state.event:'all';S.search=state.search||'';$('#talk-search').value=S.search;S.listStart=state.listStart||0;S.folderOpen=clone(state.folderOpen||{});S.activeFolder=S.branchFolders[state.activeFolder]?state.activeFolder:null;S.selected=S.doc.talks[state.selected]?Number(state.selected):visibleIds()[0]||null;S.previewRole=state.previewRole;syncFaceFromTalk();render();},
 actions:{save,undo,redo,refresh:refreshProjects}
};
// Exposed pure/data operations make graph integrity checkable without a running game.
const jsonStoryKeys={TalkCfg:'talks',EvtCfg:'events',OptionCfg:'options',PersonCfg:'persons',ModFaceCfg:'faces',BgCfg:'backgrounds',CGCfg:'cgs',PaperCfg:'papers',ActionCfg:'actions',ActionEvtCfg:'actionEvents',InteractCfg:'interactions',GiftEvtCfg:'giftEvents',MinigameActionCfg:'minigameActions'};
window.STUDIO_STORY_JSON={
 read(name,disk={}){const key=jsonStoryKeys[name];if(!key||!S.doc?.[key]||S.deferredProject)return null;const baseline=S.saved?IndexedTalks.parse(S.saved)[0]?.[key]||{}:{},rows=S.doc[key],keys=new Set([...Object.keys(disk),...(S.localIds[key]||[]).map(String)]);for(const [id,row]of Object.entries(rows))if(JSON.stringify(row)!==JSON.stringify(baseline[id]))keys.add(id);return Object.fromEntries([...keys].filter(id=>rows[id]).map(id=>[id,clone(rows[id])]));},
 async write(name,rows,disk={}){const key=jsonStoryKeys[name];if(!key||!S.doc?.[key]||S.deferredProject)return false;if(!editable())throw Error('当前模组不可编辑。');const previous=this.read(name,disk);if(JSON.stringify(previous)===JSON.stringify(rows))return true;
  rows=clone(rows);const map={};if(['talks','options','events'].includes(key))for(const [id,row]of Object.entries(rows)){const next=Number(row?.id);if(Number.isInteger(next)&&next>0&&next<=2147483647&&String(next)!==id){map[id]=next;row.id=Number(id);}}
  for(const [id,next]of Object.entries({...map}))if((rows[next]||S.doc[key][next])&&localStoryIds(key).has(Number(next))&&map[next]===undefined)map[next]=Number(id);
  if(new Set(Object.values(map)).size!==Object.keys(map).length)throw Error('多条记录指向同一个编号，请逐条修改编号。');
  history('编辑 JSON');const beforeIds=new Set(Object.keys(S.doc.talks));for(const id of Object.keys(previous))if(!rows[id])delete S.doc[key][id];Object.assign(S.doc[key],clone(rows));
  if(key==='talks'){S.order=S.order.filter(id=>S.doc.talks[id]);for(const id of Object.keys(rows).map(Number))if(!S.order.includes(id))S.order.push(id);}
  // Rows typed into the JSON carry the numbers the author chose: keep them out of automatic renumbering.
  if(key==='talks'||key==='options')for(const id of Object.keys(rows))if(!previous[id]&&Number.isInteger(Number(id)))S.pinned[key].add(Number(id));
  // Keep the left-hand list live: talks added in the JSON belong to the event being edited, renamed/removed
  // talks leave stale folders behind, and ownership decides what the current event lists.
  for(const [k,f] of Object.entries(S.branchFolders))if(f.kind!=='condition'&&!S.doc.talks[f.parentTalkId]&&!S.catalogTalkIds?.has(Number(f.parentTalkId)))delete S.branchFolders[k];
  S.branchFolders=Branches.cleanup(S.doc,S.branchFolders,S.replacements);StudentAgeEventOwnership.sync(S.doc,S.branchFolders);
  // A new talk that no event reaches yet belongs to the event being edited; one linked from an event (e.g. an
  // imported event together with its lines) keeps just that event.
  if(S.doc.events[S.event])for(const id of Object.keys(S.doc.talks))if(!beforeIds.has(id)&&!(S.doc.talkOwners[id]||[]).length)S.doc.talkOwners[id]=[Number(S.event)];
  if(key==='talks'&&!S.doc.talks[S.selected])S.selected=visibleIds()[0]||S.order[0]||null;
  updateDirty();render();
  if(Object.keys(map).length){const ok=await runRenumber({[name]:map});if(!ok)throw Error('编号同步尚未完成，请再次检查 JSON。');if(key!=='events')for(const id of Object.values(map))S.pinned[key].add(Number(id));updateDirty();render();}
  window.STUDIO_EVENTS?.refresh();return true;},
 saved(name,rows,revision){const key=jsonStoryKeys[name];S.revision=revision;if(!key||!S.doc||!S.saved)return;const saved=IndexedTalks.parse(S.saved);saved[0][key]=clone(S.doc[key]);if(key==='talks')saved[1]=S.order.slice();S.saved=IndexedTalks.stringify(saved);S.localIds[key]=Object.keys(rows).map(Number);updateDirty();renderChrome();
 }
};
window.STUDIO_CURRENT_REVISION=()=>S.revision;
window.StudentAgeStudioTest={S,addTalk,deleteTalk,undo,redo,renameEvent,addAfterBranches,addSpeaker,removeSpeaker,openJumpPicker,addOptionWithSettings,openScreenEffectMenu,openCGMenu,renumberEvent,renumberPlan,eventTraversal,branchBlock,selectTalk,save,toggleStoryAuto,setEventGrade,currentEventGrade,openStoryHistory,closeStoryHistory,scrollStoryHistory,importDialogueRows,exportDialogueRows,playCurrentLine,openStoryPreview,closeStoryPreview,Timeline,Branches,Conditions,Effects,HistoryExport,previewHistory,showHistoryExport,initialEntry,setInitialPosition,getScenePlayer:()=>scenePlayer,getSceneRenderer:()=>largeScene,reorderTalk,addConditionalBranch,addFolderTalk,setFolderContinuation,setFolderFailure,replaceEdges,graphOrder,moveTalk,normalizeTalk,nextId,currentStage,commitSceneDrag,refreshSceneAssets,enterSceneRole,removeStageRole,flipStageRole,applyBgmDraft,addSfx,audioNeedsPlugin,changedStoryPayload,getAudioPlayer:()=>stageAudio};
window.STUDIO_INITIALIZE=async()=>{await refreshProjects(null,true);};
})();
