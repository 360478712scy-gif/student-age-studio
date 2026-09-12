/* IDs preserve the game's parent/child blocks. All known projects share the registry. */
(()=>{
'use strict';
const derived={TalkCfg:['EvtCfg',1000],OptionCfg:['EvtCfg',100],KZoneCommentCfg:['KZoneContentCfg',100],ModFaceCfg:['PersonCfg',1000]};
const linked={DIYCfg:'ItemCfg',BirthdayPaintGuessCfg:'PersonCfg',PersonGrowCfg:'PersonCfg',KZoneProfileCfg:'PersonCfg',ModFaceCfg:'PersonCfg',ActionEvtCfg:'ActionCfg',ShopCfg:'ItemCfg / BookCfg'};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const token=window.STUDIO_TOKEN&&window.STUDIO_TOKEN!=='__STUDIO_TOKEN__'?window.STUDIO_TOKEN:location.hash.slice(1).replace(/^token=/,'');
let registry=null,used=new Set(),blocks={},reserved=new Set(),working=false,draft=null,applying=null,undoEntry=null,redoEntry=null,checkTimer=null,checkSequence=0;
const dialog=document.createElement('dialog');dialog.id='record-id-dialog';dialog.setAttribute('aria-label','修改编号');document.body.append(dialog);
async function api(url,data){const response=await fetch(url,{method:data?'POST':'GET',headers:{'Content-Type':'application/json','X-Studio-Token':token},body:data?JSON.stringify(data):undefined});const value=await response.json();if(!response.ok)throw Error(value.error||'编号操作失败');return value;}
function configure(data){registry=data;used=new Set(Object.values(data.tables||{}).flat().map(Number));blocks={};for(const [child,[parent,factor]]of Object.entries(derived)){blocks[parent]||=new Set();for(const id of data.tables?.[child]||[])blocks[parent].add(Math.floor(Number(id)/factor));}blocks.PhoneMsgCfg=new Set((data.tables?.PhoneMsgCfg||[]).map(id=>Math.floor(Number(id)/1000)*1000+1));}
let registryProject=null,registryPromise=null;
async function ensure(projectId){if(registry&&registryProject===projectId)return registry;if(registryPromise?.projectId===projectId)return registryPromise.promise;const promise=refresh(projectId).finally(()=>{if(registryPromise?.promise===promise)registryPromise=null;});registryPromise={projectId,promise};return promise;}
async function refresh(projectId=window.STUDIO_CURRENT_PROJECT?.()){if(!projectId)return;const data=await api('/api/ids?projectId='+encodeURIComponent(projectId));configure(data);registryProject=projectId;return data;}
function rule(table,id,owner){if(derived[table]){const [parent,factor]=derived[table];owner=Number(owner??Math.floor(Number(id)/factor));return {min:1,max:2147483647,start:owner*factor+1,end:Math.min(2147483647,owner*factor+factor-1),owner,parent,factor,step:1};}return {min:1,max:2147483647,start:table==='BookCfg'?3000000:1000000,end:table==='BookCfg'?3999999:1999999,step:table==='PhoneMsgCfg'?1000:1};}
function allocate(table,rows={},owner){if(!registry)throw Error('编号目录尚未读取完成，请稍后再试。');const r=rule(table,0,owner),low=r.start+(r.step===1000?1:0),count=Math.floor((r.end-low)/r.step)+1;if(!Number.isSafeInteger(count)||count<=0)throw Error('所属内容的编号超出可用范围。');const rand=new Uint32Array(1);crypto.getRandomValues(rand);const start=table==='TalkCfg'?0:rand[0]%count;
 const free=id=>!used.has(id)&&!reserved.has(id)&&!rows[id]&&!blocks[table]?.has(id);
 for(let n=0;n<count;n++){const id=low+(start+n)%count*r.step;if(free(id)){reserved.add(id);return id;}}
 for(let id=r.end+r.step;id<2147483647;id+=r.step)if(free(id)){reserved.add(id);return id;}
 throw Error('这类内容的可用编号已用尽。');}
const project=()=>window.STUDIO_CURRENT_PROJECT?.(),revision=()=>window.STUDIO_CURRENT_REVISION?.();
function canHistory(kind){const entry=kind==='undo'?undoEntry:redoEntry;return !!entry&&entry.projectId===project()&&entry.revision===revision()&&!window.STUDIO_HAS_UNSAVED_CHANGES?.()&&!window.STUDIO_WORKSHOP_NAV?.dirty();}
function mapState(view,maps){if(!view)return view;const result=structuredClone(view),s=result.state||{},m=(table,v)=>maps[table]?.[v]??v;
 const folder=key=>typeof key==='string'?key.split(':').map((v,i,arr)=>i===0?m('TalkCfg',v):i===1&&arr.length===2?m('OptionCfg',v):v).join(':'):key;
 if(result.view==='story'){s.event=m('EvtCfg',s.event);s.selected=m('TalkCfg',s.selected);s.previewRole=m('PersonCfg',s.previewRole);s.activeFolder=folder(s.activeFolder);s.folderOpen=Object.fromEntries(Object.entries(s.folderOpen||{}).map(([k,v])=>[folder(k),v]));}
 if(result.view==='workshop'){s.selected=String(m(s.table,s.selected));s.personId=m('PersonCfg',s.personId);if(s.special){if(s.mode==='warehouse'&&s.special.editor){const ed=s.special.editor;ed.id=String(m(ed.table,ed.id));}const social=s.mode==='social';s.special.selected=String(m(s.mode==='external-dialogues'?'TalkCfg':s.mode==='idle-chats'?'InteractCfg':s.mode==='messages'?'PhoneMsgCfg':s.mode==='goals'?'IntentCfg':social?'KZoneContentCfg':'PersonCfg',s.special.selected));if(s.mode==='idle-chats')s.special.line=m('TalkCfg',s.special.line);if(s.mode==='messages'){s.special.root=String(m('PhoneMsgCfg',s.special.root));s.special.choices=Object.fromEntries(Object.entries(s.special.choices||{}).map(([k,v])=>[m('PhoneMsgCfg',k),m('PhoneMsgCfg',v)]));}if(s.mode==='social'&&s.special.branchChoices)s.special.branchChoices=Object.fromEntries(Object.entries(s.special.branchChoices).map(([key,v])=>{const [kind,id]=key.split(':');return [kind+':'+m(kind==='post'?'KZoneContentCfg':'KZoneCommentCfg',id),m('KZoneCommentCfg',v)];}));if(s.mode==='characters'&&s.special.face)s.special.face=m('ModFaceCfg',s.special.face);if(s.special.target)s.special.target=String(m('KZoneCommentCfg',s.special.target));}}
 return result;
}
async function reload(view,mappings){await window.STUDIO_REFRESH_CURRENT_PROJECT();await window.STUDIO_WORKSHOP_NAV?.invalidateIds?.();const mapped=mapState(view,mappings);if(mapped)await window.STUDIO_NAV.restore(mapped);window.STUDIO_EVENTS?.refresh();window.STUDIO_NAV.changed();}
function notice(error){const node=dialog.querySelector('[data-id-error]');if(dialog.open&&node)node.textContent=error.message||String(error);else window.STUDIO_REPORT_ERROR?.(error);}
function clearWarning(){clearTimeout(checkTimer);checkSequence++;const node=dialog.querySelector('[data-id-warning]');if(node)node.textContent='';}
function queueWarning(){
 clearWarning();const input=dialog.querySelector('input'),node=dialog.querySelector('[data-id-warning]');
 if(!draft||draft.commit||!input||!node)return;
 dialog.querySelector('[data-id-error]').textContent='';
 const value=input.value;if(!/^\d+$/.test(value)||Number(value)<1||Number(value)>2147483647)return;
 const sequence=checkSequence,snapshot=draft;
 checkTimer=setTimeout(async()=>{
  try{
   const result=await api('/api/ids/check',{...snapshot,newId:Number(value)});
   if(sequence!==checkSequence||draft!==snapshot||input.value!==value||!dialog.open)return;
   const groups=[['id','该 ID '],['related','关联编号']];
   node.textContent=groups.map(([kind,label])=>{const names=[...new Set((result.conflicts||[]).filter(c=>c.kind===kind).map(c=>c.name))];return names.length?label+'已被'+names.map(name=>'「'+name+'」').join('、')+'占用。仍可使用此 ID。':'';}).filter(Boolean).join('\n');
  }catch(error){if(sequence===checkSequence&&draft===snapshot&&dialog.open)node.textContent='暂时无法检查占用情况，仍可填写并应用。';}
 },200);
}
async function regenerate(){
 if(!draft||working)return;working=true;const snapshot=draft;dialog.querySelectorAll('button,input').forEach(n=>n.disabled=true);
 try{await refresh(snapshot.projectId);if(draft===snapshot){dialog.querySelector('input').value=allocate(draft.table,{},rule(draft.table,draft.oldId).owner);queueWarning();}}
 catch(error){notice(error);}finally{working=false;dialog.querySelectorAll('button,input').forEach(n=>n.disabled=false);window.STUDIO_NAV?.changed();}
}
let inlineSession=null;
function inline(anchor,{oldId,commit}){
 if(!anchor?.isConnected||working||draft||inlineSession)return;
 const original=anchor.innerHTML,input=document.createElement('input'),error=document.createElement('span');
 input.type='text';input.inputMode='numeric';input.autocomplete='off';input.spellcheck=false;input.value=String(oldId);input.className='record-id-inline-input';input.setAttribute('aria-label','编辑编号');input.title='Enter 确认 · Esc 取消';
 error.className='record-id-inline-error';error.setAttribute('role','alert');anchor.replaceChildren(input,error);anchor.classList.add('record-id-editing');let closed=false,busy=false;
 const finish=()=>{if(closed)return;closed=true;if(anchor.isConnected){anchor.innerHTML=original;anchor.classList.remove('record-id-editing');}inlineSession=null;};
 inlineSession={finish};
 const submit=async()=>{if(closed||busy)return;const text=input.value.trim(),id=Number(text);if(!/^\d+$/.test(text)||!Number.isSafeInteger(id)||id<1||id>2147483647){error.textContent='请输入 1–2147483647 的整数';input.setAttribute('aria-invalid','true');input.focus();return;}if(id===Number(oldId)){finish();return;}busy=true;working=true;input.readOnly=true;
  try{const result=await commit(id);if(result===false)throw Error('内容已变化，请重试');finish();}catch(e){if(anchor.isConnected){error.textContent=e.message||'编号修改失败';input.setAttribute('aria-invalid','true');input.focus();}else finish();}finally{busy=false;working=false;input.readOnly=false;window.STUDIO_NAV?.changed();}
 };
 input.onkeydown=e=>{e.stopPropagation();if(e.key==='Escape'){e.preventDefault();if(!busy)finish();}else if(e.key==='Enter'){e.preventDefault();submit();}};
 input.oninput=()=>{error.textContent='';input.removeAttribute('aria-invalid');};input.onblur=()=>{if(!closed&&!busy)submit();};
 anchor.addEventListener('click',e=>{if(!closed)e.stopPropagation();},{capture:true,once:true});input.focus();input.select();
}
async function commitStored(table,oldId,newId){
 if(linked[table])throw Error('此编号与所属内容绑定，请修改 '+linked[table]+' 的编号。');
 const projectId=project(),view=window.STUDIO_NAV.capture();working=true;
 try{if(await window.STUDIO_NAV.saveAll()===false)throw Error('保存已取消，编号未修改。');if(window.STUDIO_HAS_UNSAVED_CHANGES?.()||window.STUDIO_WORKSHOP_NAV?.dirty())throw Error('仍有未保存内容，编号未修改。');const fresh=await refresh(projectId);const result=await api('/api/ids/rename',{projectId,revision:fresh.revision,table,oldId:Number(oldId),newId});undoEntry={projectId,revision:result.revision,token:result.undoToken};redoEntry=null;await reload(view,result.mappings);}finally{working=false;window.STUDIO_NAV?.changed();}
}
async function open(table,oldId,anchor){if(anchor)return inline(anchor,{oldId,commit:newId=>commitStored(table,oldId,newId)});if(working||draft)return;working=true;try{const data=await refresh();if(!data)throw Error('请先打开模组。');const row={projectId:project(),revision:data.revision,table,oldId:Number(oldId)},r=rule(table,oldId);draft=row;
 dialog.innerHTML=`<header><div><span class="record-id-eyebrow">编号设置</span><h2>修改编号</h2></div><button data-id-cancel aria-label="关闭编号设置">×</button></header><p class="record-id-current">当前编号 <strong>${esc(oldId)}</strong></p>${linked[table]?`<p>此编号随所属内容同步。请在 ${esc(linked[table])} 修改对应 ID。</p>`:`<label for="record-id-value">新的编号</label><div class="record-id-input-row"><input id="record-id-value" type="number" step="1" min="${r.min}" max="${r.max}" value="${esc(oldId)}"><button data-id-random>重新生成</button></div><p data-id-warning role="status" aria-live="polite"></p><p class="helper">可填 1–2147483647 之间的任意整数${r.parent?'；前缀对应所属'+(r.parent==='EvtCfg'?'事件':'动态')+'，修改所属内容的 ID 会同步调整此编号':''}。若编号已被本模组其他内容使用，两者会互换编号；与游戏或其他模组重复只作提示。</p><p>应用时保存当前页面的修改，并同步更新本模组的关联引用。取消不会保存或修改编号。</p>`}<p data-id-error role="alert"></p><footer><button data-id-cancel>取消</button>${linked[table]?'':'<button class="primary" data-id-apply>应用并保存</button>'}</footer>`;dialog.showModal();dialog.querySelector('input')?.focus();queueWarning();
 }catch(error){notice(error);}finally{working=false;window.STUDIO_NAV?.changed();}}
async function apply(){if(applying)return applying;if(!draft||linked[draft.table])return;const value=dialog.querySelector('input').value;if(!/^\d+$/.test(value))throw Error('请输入整数 ID。');const newId=Number(value);if(newId<1||newId>2147483647)throw Error('请输入 1 到 2147483647 之间的整数编号。');if(newId===Number(draft.oldId)){dialog.close();draft=null;return;}
 if(draft.commit){working=true;dialog.querySelectorAll('button,input').forEach(n=>n.disabled=true);try{const ok=await draft.commit(newId);if(ok===false)throw Error('内容正在变化，编号尚未修改，请再次应用。');draft=null;dialog.close();}finally{working=false;dialog.querySelectorAll('button,input').forEach(n=>n.disabled=false);window.STUDIO_NAV?.changed();}return;}
 const payload={...draft,newId},view=window.STUDIO_NAV.capture();applying=(async()=>{working=true;dialog.querySelectorAll('button,input').forEach(n=>n.disabled=true);try{await window.STUDIO_NAV.saveAll();const fresh=await refresh(payload.projectId);payload.revision=fresh.revision;const result=await api('/api/ids/rename',payload);undoEntry={projectId:payload.projectId,revision:result.revision,token:result.undoToken};redoEntry=null;draft=null;dialog.close();await reload(view,result.mappings);}finally{working=false;dialog.querySelectorAll('button,input').forEach(n=>n.disabled=false);window.STUDIO_NAV.changed();}})();try{return await applying;}finally{applying=null;}}
async function history(kind){if(!canHistory(kind))return;working=true;const entry=kind==='undo'?undoEntry:redoEntry,view=window.STUDIO_NAV.capture();try{const result=await api('/api/ids/undo',entry),next={projectId:entry.projectId,revision:result.revision,token:result.undoToken};if(kind==='undo'){undoEntry=null;redoEntry=next;}else{redoEntry=null;undoEntry=next;}await reload(view,result.mappings);}finally{working=false;window.STUDIO_NAV.changed();}}
dialog.addEventListener('click',e=>{if(working)return;const b=e.target.closest('button');if(!b)return;if(b.hasAttribute('data-id-cancel')){draft=null;dialog.close();}else if(b.hasAttribute('data-id-random'))regenerate();else if(b.hasAttribute('data-id-apply'))apply().catch(notice);});
dialog.addEventListener('input',e=>{if(e.target.id==='record-id-value')queueWarning();});
dialog.addEventListener('close',()=>{clearWarning();if(!dialog.open)draft=null;});
dialog.addEventListener('cancel',e=>{if(working){e.preventDefault();return;}draft=null;});
dialog.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();apply().catch(notice);}});
document.addEventListener('click',e=>{const b=e.target.closest('[data-record-table]');if(!b||b.disabled||e.target.closest('.record-id-inline-input'))return;e.preventDefault();e.stopImmediatePropagation();open(b.dataset.recordTable,b.dataset.recordId,b);},true);
document.addEventListener('keydown',event=>{if(working||dialog.open||!(event.metaKey||event.ctrlKey)||event.target.closest('input,textarea,[contenteditable=true]'))return;const key=event.key.toLowerCase(),kind=key==='z'?(event.shiftKey?'redo':'undo'):key==='y'?'redo':null;if(kind&&canHistory(kind)){event.preventDefault();event.stopImmediatePropagation();history(kind).catch(notice);}},true);
function editDraft({oldId,title='修改编号',commit}){
 if(working||draft)return;draft={oldId:Number(oldId),commit};
 dialog.innerHTML=`<header><div><span class="record-id-eyebrow">编号设置</span><h2>${esc(title)}</h2></div><button data-id-cancel aria-label="关闭编号设置">×</button></header><p class="record-id-current">当前编号 <strong>${esc(oldId)}</strong></p><label for="record-id-value">新的编号</label><div class="record-id-input-row"><input id="record-id-value" type="text" inputmode="numeric" autocomplete="off" spellcheck="false" value="${esc(oldId)}"></div><p class="helper">输入 1–2147483647 之间的整数。与本模组已有编号重复时互换，相关引用同步更新。</p><p class="record-id-draft-note">应用到当前草稿，可撤销；保存模组后写入文件。手动指定的对话和选项编号会保持固定。</p><p data-id-error role="alert"></p><footer><button data-id-cancel>取消</button><button class="primary" data-id-apply>应用编号</button></footer>`;
 dialog.showModal();const input=dialog.querySelector('input');input.focus();input.select();
}
window.STUDIO_IDS={inline,editDraft,configure,refresh,ensure,allocate,rule,open,apply,history,canUndo:()=>canHistory('undo'),canRedo:()=>canHistory('redo'),get busy(){return working;}};
})();
