/* Shared desktop toolbar and view history. History contains selection, never old data. */
(()=>{
'use strict';
// Suppress browser commands while allowing editor shortcuts and custom menus.
document.addEventListener('contextmenu',event=>event.preventDefault());
document.addEventListener('dragstart',event=>{if(event.target.closest('img,.scene-backdrop,.scene-cg-layer'))event.preventDefault();});
document.addEventListener('keydown',event=>{
 const key=event.key.toLowerCase(),command=event.ctrlKey||event.metaKey;
 const browserKey=['f5','f11'].includes(key)||(command&&['r','p','l','u','+','=','-','0'].includes(key))||(command&&event.shiftKey&&['i','j','c'].includes(key));
 if(browserKey){event.preventDefault();event.stopImmediatePropagation();}
 else if(key==='escape'&&!document.querySelector('dialog[open]'))event.preventDefault();
},true);
document.addEventListener('wheel',event=>{if(event.ctrlKey||event.metaKey)event.preventDefault();},{passive:false});

const $=s=>document.querySelector(s), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bar=document.createElement('header');bar.id='studio-toolbar';bar.setAttribute('aria-label','工作台顶部工具栏');
const saveKey=/Mac|iPhone|iPad/.test(navigator.platform)?'⌘S':'Ctrl+S';
bar.innerHTML=`<strong class="studio-brand"><img src="/icon.png" alt="">拾光工坊</strong><button data-nav="backup" class="studio-backup" title="先保存当前修改，再备份完整模组">手动备份</button><nav class="studio-history" aria-label="页面浏览历史"><button data-nav="back" aria-label="后退" title="后退 · Alt+←" disabled>←</button><button data-nav="forward" aria-label="前进" title="前进 · Alt+→" disabled>→</button></nav><label class="studio-project"><span>模组</span><select id="studio-project" aria-label="选择模组"><option>正在读取…</option></select></label><label class="studio-feature studio-project"><span>功能</span><select id="studio-feature" aria-label="选择工坊功能" data-search="true"><option value="">选择功能…</option></select></label><button data-nav="refresh" class="studio-refresh" aria-label="刷新模组列表" title="刷新模组列表">↻</button><button data-nav="home" class="secondary">工坊主页</button><button data-nav="original" aria-pressed="false" title="浏览原版资源，将修改保存为当前模组的覆盖记录">原版资源修改</button><div class="studio-toolbar-actions"><button data-nav="create">新建模组</button><button data-nav="copy">创建副本</button><button data-nav="undo" title="撤销修改" aria-label="撤销修改">↶</button><button data-nav="redo" title="重做修改" aria-label="重做修改">↷</button><button data-nav="save" class="primary"><span>保存模组</span><kbd>${saveKey}</kbd></button><button id="studio-auto-save" role="switch" aria-checked="false" title="开启后，离开编辑页面时自动保存；退出保存可在工坊设置调整">自动保存：关</button><button data-display-ids aria-pressed="true">显示 ID</button><button data-nav="help">操作说明</button><button data-game-location>工坊设置</button></div><span id="studio-save-state" role="status"></span>`;
document.body.prepend(bar);document.body.classList.add('studio-navigation');
const sourceButton=bar.querySelector('[data-nav=original]');sourceButton.id='studio-original-corner';sourceButton.className='json-corner original-mode-corner';sourceButton.setAttribute('aria-label','原版资源修改');
sourceButton.innerHTML='<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5C8 3.5 5 3.5 2.5 4.5v14c2.8-1 5.7-.5 8.5 1 1.5-.8 3-1.3 4.5-1.3M11 5v14.5M14 4.3c1.4-.3 2.8-.2 4.3.2"/><path d="m14 14 1-3 5.8-5.8 2 2L17 13l-3 1Z"/></svg>';
const dock=document.createElement('aside');dock.id='studio-corner-tools';dock.setAttribute('aria-label','快捷工具');
const cornerItems=document.createElement('div');cornerItems.id='studio-corner-items';
const helpButton=bar.querySelector('[data-nav=help]'),settingsButton=bar.querySelector('[data-game-location]');
const svg=paths=>'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths+'</svg>';
for(const [button,id,label,paths] of [[helpButton,'studio-help-corner','操作说明','<path d="M5 3h14v18H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm0 0v14h14M3 19h16M9 7h6M9 11h5"/>'],[settingsButton,'studio-settings-corner','工坊设置','<path d="m9 3-.6 2.2-2 .9-2.1-.6-2 3.5 1.6 1.6v2.3L2.3 15l2 3.5 2.2-.6 2 .9L9 21h4l.6-2.2 2-.9 2.1.6 2-3.5-1.6-1.6v-2.3L19.7 9l-2-3.5-2.2.6-2-.9L13 3Z"/><circle cx="11" cy="12" r="3"/>']]){button.id=id;button.className='json-corner';button.title=label;button.setAttribute('aria-label',label);button.innerHTML=svg(paths);}
const pluginButton=document.createElement('button');pluginButton.id='studio-plugin-corner';pluginButton.className='json-corner';pluginButton.type='button';pluginButton.title='插件编辑模式';pluginButton.setAttribute('aria-label','插件编辑模式');pluginButton.setAttribute('aria-pressed','false');pluginButton.innerHTML=svg('<path d="M8 3v5m8-5v5M6 8h12v4a6 6 0 0 1-12 0V8Zm6 10v3"/>');
cornerItems.append(helpButton,settingsButton,sourceButton,pluginButton);
pluginButton.onclick=()=>{if(!pluginButton.disabled)run(()=>wk().togglePlugins()).catch(error);};
const fold=document.createElement('button');fold.id='studio-corner-toggle';fold.className='json-corner';fold.type='button';fold.setAttribute('aria-controls',cornerItems.id);fold.innerHTML=svg('<path d="m6 9 6 6 6-6"/>');
let cornersCollapsed=false;try{cornersCollapsed=localStorage.getItem('studio-corners-collapsed')==='true';}catch{}
function setCornersCollapsed(value){cornersCollapsed=value;dock.classList.toggle('collapsed',value);cornerItems.inert=value;fold.setAttribute('aria-expanded',String(!value));fold.title=value?'展开快捷工具':'收起快捷工具';fold.setAttribute('aria-label',fold.title);try{localStorage.setItem('studio-corners-collapsed',String(value));}catch{}}
fold.onclick=()=>setCornersCollapsed(!cornersCollapsed);dock.append(cornerItems,fold);document.body.append(dock);setCornersCollapsed(cornersCollapsed);
// The corner tools live in the top layer above every secondary window.
window.STUDIO_LAYERING?.keepOnTop(dock);
window.STUDIO_CORNER_TOOLS={add:button=>{if(button.id==='config-doctor-corner')cornerItems.insertBefore(button,cornerItems.querySelector('#json-corner'));else cornerItems.append(button);}};
helpButton.onclick=()=>{if(!helpButton.disabled)action('help').catch(error);};
// Group navigation, context and document actions without changing their handlers.
const contextGroup=document.createElement('div');contextGroup.className='studio-context-group';contextGroup.setAttribute('role','group');contextGroup.setAttribute('aria-label','当前模组与编辑功能');
const projectLabels=[...bar.querySelectorAll('.studio-project')];bar.insertBefore(contextGroup,projectLabels[0]);contextGroup.append(...projectLabels,bar.querySelector('[data-nav=refresh]'));
const fileActions=document.createElement('div');fileActions.className='studio-file-actions';fileActions.setAttribute('role','group');fileActions.setAttribute('aria-label','模组文件操作');
const actions=bar.querySelector('.studio-toolbar-actions');actions.prepend(fileActions);
for(const [name,label,paths] of [
 ['backup','手动备份','<path d="M4 7h16v14H4zM3 3h18v4H3M9 12h6"/>'],
 ['create','新建模组','<path d="M12 5v14M5 12h14"/>'],
 ['copy','创建副本','<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/>']]){
 const node=bar.querySelector(`[data-nav=${name}]`);node.setAttribute('aria-label',label);node.title=label;node.classList.add('studio-symbol-action');node.innerHTML=svg(paths);fileActions.append(node);
}


const notice=document.createElement('div');notice.id='studio-navigation-notice';notice.hidden=true;notice.setAttribute('role','alert');document.body.append(notice);
const saving=document.createElement('div');saving.id='studio-saving';saving.hidden=true;saving.innerHTML='<div role="status">正在保存，请稍候…</div>';document.body.append(saving);
const entries=[];let cursor=-1,restoring=false,savePromise=null,backupPromise=null,transition=false,scheduled=null,projectSignature='',helpBase=null,featureSignature='',autoSave=window.STUDIO_AUTO_SAVE===true,saveOnExit=window.STUDIO_SAVE_ON_EXIT===true,preferencePromise=null,leavePromise=null;
const wk=()=>window.STUDIO_WORKSHOP_NAV,story=()=>window.STUDIO_STORY_NAV;
const busy=()=>window.STUDIO_BOOTSTRAPPING||window.STUDIO_IDS?.busy||window.STUDIO_PREVIEW_ACTIVE?.()||restoring||transition||!!savePromise||!!backupPromise||!!leavePromise||!!preferencePromise||wk()?.busy()||story()?.busy();
const scrollSelectors=['#editor-scroll','#talk-list','#wk-main','#wk-row-list','#wk-form','#wk-preview','.events-main','#studio-help-main','#studio-help-nav'];
function scrolls(){return Object.fromEntries(scrollSelectors.map(s=>[s,$(s)?.scrollTop||0]));}
function base(){const project=window.STUDIO_CURRENT_PROJECT?.(),original=!!window.STUDIO_ORIGINAL_MODE?.();if(!project)return null;if(window.STUDIO_EVENTS?.isOpen())return {view:'events',project,original,state:window.STUDIO_EVENTS.capture()};if(wk()?.isOpen())return {view:'workshop',project,original,state:wk().capture()};return {view:'story',project,original,state:story()?.capture()||{}};}
function capture(){if(window.STUDIO_HELP?.isOpen())return {view:'help',project:window.STUDIO_CURRENT_PROJECT?.(),state:window.STUDIO_HELP.capture(),base:helpBase,scroll:scrolls()};const result=base();return result?{...result,scroll:scrolls()}:null;}
function key(v){if(!v)return '';const s=v.state||{};return JSON.stringify([v.project,v.original,v.view,v.view==='workshop'?[s.mode,s.mode==='table'?s.table:null,s.source,['table','social','space','characters'].includes(s.mode)?s.selected:null,s.special?.selected,s.special?.target,s.special?.source,s.special?.tab]:v.view==='story'?[s.event,s.selected,s.activeFolder]:v.view==='help'?s.section:null]);}
function updateCurrent(){const value=capture();if(cursor>=0&&key(entries[cursor])===key(value))entries[cursor]=value;}
function record(){scheduled=null;if(busy())return;const value=capture();if(!value)return;if(key(entries[cursor])===key(value))entries[cursor]=value;else{entries.splice(cursor+1);entries.push(value);if(entries.length>100)entries.shift();cursor=entries.length-1;}render();}
function changed(){if(scheduled)return;scheduled=setTimeout(record,90);}
function error(e){notice.hidden=true;window.STUDIO_NOTIFY?.(e?.message||String(e),true);}
function renderFeatures(blocked){
 const select=$('#studio-feature'),features=wk()?.features?.()||[],current=window.STUDIO_CURRENT_PROJECT?.();
 const state=wk()?.capture(),selected=wk()?.isOpen()?state?.feature||'':current?'story':'';
 const signature=JSON.stringify([current,selected,features]);
 if(signature!==featureSignature){featureSignature=signature;const option=f=>`<option value="${esc(f.id)}" ${f.id===selected?'selected':''}>${esc(f.label)}</option>`;select.innerHTML='<option value="" disabled hidden>选择功能…</option>'+[true,false].map(favorite=>{const rows=features.filter(f=>!!f.favorite===favorite);return rows.length?`<optgroup label="${favorite?'★ 收藏':'全部功能'}">${rows.map(option).join('')}</optgroup>`:'';}).join('');select.value=features.some(f=>f.id===selected)?selected:'';}
 select.disabled=blocked||!current||!features.length;
}
function render(){
 const list=window.STUDIO_PROJECTS?.()||[],current=window.STUDIO_CURRENT_PROJECT?.(),project=list.find(p=>p.id===current),signature=JSON.stringify([list.map(p=>[p.id,p.name,p.readOnly,p.path]),current]);
 if(signature!==projectSignature){projectSignature=signature;const option=p=>`<option value="${esc(p.id)}" data-hover-tip="${esc(p.path||'')}" ${p.id===current?'selected':''}>${esc(window.STUDIO_PROJECT_LABEL?window.STUDIO_PROJECT_LABEL(p,list):p.name)}</option>`;$('#studio-project').innerHTML='<option value="" disabled>选择模组…</option>'+[false,true].map(readOnly=>`<optgroup label="${readOnly?'订阅模组 · 只读':'模组'}">${list.filter(p=>!!p.readOnly===readOnly).map(option).join('')}</optgroup>`).join('');}
 const blocked=busy(),state=wk()?.isOpen()?wk().toolbar():{dirty:!!window.STUDIO_HAS_UNSAVED_CHANGES?.(),readOnly:!!project?.readOnly,canUndo:!$('#undo')?.disabled,canRedo:!$('#redo')?.disabled};
 for(const button of [...bar.querySelectorAll('[data-nav]'),sourceButton,helpButton]){const name=button.dataset.nav;button.hidden=name==='copy'&&!!window.STUDIO_ORIGINAL_MODE?.()||['create','copy'].includes(name)&&!!current&&!wk()?.isOpen();button.disabled=blocked||(!current&&!['help','create','refresh','back','forward'].includes(name))||(name==='back'&&cursor<1)||(name==='forward'&&cursor>=entries.length-1)||(['backup','original'].includes(name)&&state.readOnly)||(name==='save'&&(!state.dirty||state.readOnly))||(name==='undo'&&(!state.canUndo&&!window.STUDIO_IDS?.canUndo()||state.readOnly))||(name==='redo'&&(!state.canRedo&&!window.STUDIO_IDS?.canRedo()||state.readOnly));}
 const saveLabel=bar.querySelector('[data-nav=save] span');if(saveLabel)saveLabel.textContent='保存模组';
 const pluginActive=wk()?.pluginEditing?.()||false;pluginButton.disabled=blocked||!current;pluginButton.classList.toggle('active',pluginActive);pluginButton.setAttribute('aria-pressed',String(pluginActive));pluginButton.title=pluginActive?'插件编辑模式已开启 · 点击退出':'插件编辑模式';
 const original=!!window.STUDIO_ORIGINAL_MODE?.();sourceButton.classList.toggle('active',original);sourceButton.setAttribute('aria-pressed',String(original));sourceButton.setAttribute('aria-label',original?'返回模组编辑':'原版资源修改');sourceButton.title=original?'正在修改原版资源 · 点击返回模组编辑':'原版资源修改';
 $('#studio-project').disabled=blocked;renderFeatures(blocked);bar.querySelector('[data-nav=home]').classList.toggle('active',wk()?.isOpen()&&wk().capture().mode==='home'&&!window.STUDIO_HELP?.isOpen());
 helpButton.classList.toggle('active',!!window.STUDIO_HELP?.isOpen());
 const toggle=$('#studio-auto-save');toggle.disabled=blocked;toggle.setAttribute('aria-checked',String(autoSave));toggle.classList.toggle('active',autoSave);toggle.textContent='自动保存：'+(autoSave?'开':'关');
 const label=blocked?'正在处理…':!current?'':state.readOnly?'订阅模组 · 只读':state.dirty?'有未保存的修改':(autoSave?'已保存 · 自动保存已开启':'已保存 · 手动保存');
 if($('#studio-save-state').textContent!==label)$('#studio-save-state').textContent=label;
}
const previousClose=window.STUDIO_REQUEST_CLOSE;
async function saveAll(){
 if(savePromise)return savePromise;
 savePromise=(async()=>{saving.hidden=false;notice.hidden=true;window.STUDIO_PAUSE_PREVIEW?.();try{await window.STUDIO_COMMIT_OPEN_EDITOR?.();const dialogs=[...document.querySelectorAll('dialog[open]')].map(node=>[node,node.inert]);for(const [node]of dialogs)node.inert=true;let allowed;try{allowed=await previousClose();}finally{for(const [node,value]of dialogs)node.inert=value;}if(!allowed){throw Error('保存未完成，请检查当前页面的提示。窗口与编辑内容已保留。');}return true;}finally{saving.hidden=true;}})();render();
 try{return await savePromise;}catch(e){dismissHelp();throw e;}finally{savePromise=null;render();}
}
async function backupAll(){
 if(backupPromise)return backupPromise;
 backupPromise=(async()=>{await saveAll();saving.firstElementChild.textContent='正在备份完整模组，请稍候…';saving.hidden=false;try{return await window.STUDIO_BACKUP_PROJECT();}finally{saving.hidden=true;saving.firstElementChild.textContent='正在保存，请稍候…';}})();
 try{return await backupPromise;}finally{backupPromise=null;render();}
}
// All automatic transitions share one policy; explicit Save never goes through it.
async function setAutoSave(value){
 if(preferencePromise)return preferencePromise;
 preferencePromise=(async()=>{const response=await fetch('/api/display-settings',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':window.STUDIO_TOKEN},body:JSON.stringify({autoSave:!!value})});const result=await response.json();if(!response.ok||result.error)throw Error(result.error||'自动保存设置未保存');autoSave=result.autoSave===true;window.STUDIO_AUTO_SAVE=autoSave;})();render();
 try{await preferencePromise;}finally{preferencePromise=null;render();}
}
async function setSaveOnExit(value){
 if(preferencePromise)await preferencePromise;
 preferencePromise=(async()=>{const r=await fetch('/api/display-settings',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':STUDIO_TOKEN},body:JSON.stringify({saveOnExit:!!value})});const v=await r.json();if(!r.ok)throw Error(v.error);saveOnExit=v.saveOnExit;window.STUDIO_SAVE_ON_EXIT=saveOnExit;})();
 try{await preferencePromise;}finally{preferencePromise=null;render();}
}
function askToLeave(allowDiscard=true){
 window.STUDIO_PAUSE_PREVIEW?.();
 return new Promise(resolve=>{
  const dialog=document.createElement('dialog');dialog.id='studio-unsaved';dialog.setAttribute('aria-labelledby','studio-unsaved-title');
  dialog.innerHTML='<h2 id="studio-unsaved-title">有未保存的修改</h2><p>本次操作需要你决定是否保存。保存后继续，或不保存并放弃本次未保存的修改。</p><div class="studio-unsaved-actions"><button data-leave="cancel" autofocus>取消</button><button data-leave="discard">不保存</button><button data-leave="save" class="primary">保存并继续</button></div>';
  if(!allowDiscard){dialog.querySelector('p').textContent='此操作需要先保存当前编辑内容。自动保存已关闭，请选择保存后继续，或取消操作保留草稿。';dialog.querySelector('[data-leave=discard]').remove();}
  const done=value=>{dialog.close();dialog.remove();resolve(value);};
  dialog.onclick=event=>{const button=event.target.closest('[data-leave]');if(button)done(button.dataset.leave);};
  dialog.oncancel=event=>{event.preventDefault();done('cancel');};
  // Keep editor shortcuts from applying to a background document under this dialog.
  dialog.addEventListener('keydown',event=>event.stopPropagation());document.body.append(dialog);dialog.showModal();
 });
}
async function prepareLeave(options={}){
 if(leavePromise)return leavePromise;
 leavePromise=(async()=>{
  document.activeElement?.blur?.();
  const dirty=options.dirty??(()=>!!window.STUDIO_HAS_UNSAVED_CHANGES?.()||!!window.STUDIO_HAS_OPEN_DRAFT?.());
  if(!dirty())return true;
  const decision=(options.closing?saveOnExit:autoSave)?'save':await askToLeave(options.allowDiscard!==false);
  if(decision==='cancel')return false;
  if(decision==='save')return await (options.save||saveAll)();
  await (options.discard||(()=>{wk()?.discard();window.STUDIO_DISCARD_STORY?.();}))();return true;
 })();render();
 try{return await leavePromise;}finally{leavePromise=null;render();}
}
window.addEventListener('keydown',event=>{if($('#studio-unsaved')?.open){event.stopImmediatePropagation();if(event.key!=='Escape'&&(event.ctrlKey||event.metaKey))event.preventDefault();}},true);
$('#studio-auto-save').onclick=()=>{if(!busy())setAutoSave(!autoSave).catch(error);};
window.STUDIO_REQUEST_CLOSE=async()=>{try{if(backupPromise)await backupPromise;if(preferencePromise)await preferencePromise;if(savePromise)await savePromise;return await prepareLeave({closing:true});}catch(e){error(e);throw e;}};
async function restoreBase(value){
 if(!value)return;
 if(window.STUDIO_CURRENT_PROJECT?.()!==value.project){if(!(window.STUDIO_PROJECTS?.()||[]).some(p=>p.id===value.project))throw Error('历史记录中的模组已不可用。');await window.STUDIO_SELECT_PROJECT(value.project);}
 if(!!window.STUDIO_ORIGINAL_MODE?.()!==!!value.original)await window.STUDIO_SET_ORIGINAL_MODE(!!value.original);
 window.STUDIO_EVENTS?.close();
 if(value.view==='workshop')await wk().restore(value.state);
 else{await window.STUDIO_REFRESH_CURRENT_PROJECT?.(true);wk()?.hide();if(value.view==='events')window.STUDIO_EVENTS.restore(value.state);else story().restore(value.state);}
}
async function restore(value){window.STUDIO_HELP?.close();if(value.view==='help'){helpBase=value.base;await restoreBase(value.base);window.STUDIO_HELP.open(value.state);}else await restoreBase(value);await new Promise(requestAnimationFrame);applyScroll(value);}
// Help overlays a live editor. Returning to that editor must not save or rebuild it.
function applyScroll(value){for(const [selector,top]of Object.entries(value?.scroll||{}))$(selector)?.scrollTo({top,behavior:'instant'});}
function dismissHelp(){if(!window.STUDIO_HELP?.isOpen())return;window.STUDIO_HELP.close();applyScroll(helpBase);}
function sameHelpBase(value){const target=value?.view==='help'?value.base:value;return !!target&&key(target)===key(base());}
async function restoreHelpOnly(value){
 if(value.view==='help'){helpBase=value.base;window.STUDIO_HELP.open(value.state);}
 else window.STUDIO_HELP.close();
 await new Promise(requestAnimationFrame);applyScroll(value);
}
async function travel(delta){
 if(busy())return;record();const index=cursor+delta;if(index<0||index>=entries.length)return;
 const before=capture(),target=entries[index],helpOnly=(before?.view==='help'||target.view==='help')&&sameHelpBase(target);
 restoring=true;render();let saved=false;
 try{
  if(helpOnly){notice.hidden=true;await restoreHelpOnly(target);}
  else{if(!await prepareLeave())return;saved=true;await restore(target);}
  cursor=index;entries[index]=capture();
 }catch(e){
  // A failed save leaves the live draft mounted; rebuilding can discard form input.
  if(saved){try{await restore(before);dismissHelp();}catch{}}
  error(e);
 }finally{restoring=false;record();render();}
}
function returnFromHelp(){
 if(!window.STUDIO_HELP?.isOpen()||restoring||transition||savePromise)return;
 updateCurrent();const underlying=base();let index=cursor-1;
 while(index>=0&&(entries[index].view==='help'||key(entries[index])!==key(underlying)))index--;
 dismissHelp();notice.hidden=true;
 if(index>=0){cursor=index;entries[index]=capture();render();}else record();
}
async function run(fn){if(busy())return;record();transition=true;notice.hidden=true;render();try{await fn();}catch(e){error(e);}finally{transition=false;record();render();}}
async function home(){if(!await prepareLeave())return;window.STUDIO_HELP?.close();await wk().open();window.STUDIO_EVENTS?.close();}
function help(){record();if(!window.STUDIO_HELP?.isOpen())helpBase={...base(),scroll:scrolls()};notice.hidden=true;window.STUDIO_PAUSE_PREVIEW?.();window.STUDIO_HELP.open();record();}
function confirmOriginalMode(){
 return new Promise(resolve=>{
  const dialog=document.createElement('dialog');dialog.id='studio-original-confirm';dialog.setAttribute('aria-labelledby','studio-original-confirm-title');
  const project=(window.STUDIO_PROJECTS?.()||[]).find(p=>p.id===window.STUDIO_CURRENT_PROJECT?.());
  dialog.innerHTML=`<h2 id="studio-original-confirm-title">进入原版资源修改模式？</h2><p>你可以浏览并修改原版事件、人物等内容。修改将保存到「${esc(project?.name||'当前模组')}」，用于覆盖原版效果，原版文件不会改动。</p><div class="studio-unsaved-actions"><button data-original-cancel autofocus>取消</button><button data-original-enter class="primary">进入</button></div>`;
  const done=value=>{dialog.close();dialog.remove();resolve(value);};
  dialog.onclick=event=>{if(event.target.closest('[data-original-enter]'))done(true);else if(event.target.closest('[data-original-cancel]'))done(false);};
  dialog.oncancel=event=>{event.preventDefault();done(false);};dialog.addEventListener('keydown',event=>event.stopPropagation());document.body.append(dialog);dialog.showModal();
 });
}
async function action(name){
 if(name==='back'||name==='forward')return travel(name==='back'?-1:1);
 if(name==='help'){if(!busy())help();return;}
 return run(async()=>{
  if(name==='original'){if(!window.STUDIO_ORIGINAL_MODE()&&!await confirmOriginalMode())return;if(!await prepareLeave())return;window.STUDIO_HELP?.close();return window.STUDIO_SET_ORIGINAL_MODE(!window.STUDIO_ORIGINAL_MODE());}
  if(name==='home')return home();
  if(name==='save')return saveAll();
  if(name==='backup')return backupAll();
  if(name==='create'||name==='copy'){if(!await prepareLeave())return;window.STUDIO_NEW_PROJECT(name==='copy');return;}
  if(name==='refresh'){if(!await prepareLeave())return;return story().actions.refresh();}
  if(name==='undo'||name==='redo'){if(window.STUDIO_IDS?.[name==='undo'?'canUndo':'canRedo']())return window.STUDIO_IDS.history(name);if(wk()?.isOpen())return wk().action(name);return story().actions[name]();}
 });
}
sourceButton.onclick=()=>{if(!sourceButton.disabled)action('original').catch(error);};
bar.addEventListener('click',event=>{const button=event.target.closest('[data-nav]');if(button&&!button.disabled)action(button.dataset.nav).catch(error);});
$('#studio-feature').addEventListener('change',event=>{const id=event.target.value,currentFeature=wk()?.isOpen()?wk().capture()?.feature:window.STUDIO_CURRENT_PROJECT?.()?'story':'';featureSignature='';renderFeatures(busy());if(!id||id===currentFeature)return;run(async()=>{if(!await prepareLeave())return;window.STUDIO_HELP?.close();window.STUDIO_EVENTS?.close();await wk().openFeature(id);});});
$('#studio-project').addEventListener('change',event=>{const id=event.target.value;event.target.value=window.STUDIO_CURRENT_PROJECT?.()||'';if(!id||id===window.STUDIO_CURRENT_PROJECT?.())return;run(async()=>{if(!await prepareLeave())return;await window.STUDIO_SELECT_PROJECT(id);});});
document.addEventListener('click',()=>{if(!busy())record();changed();},true);
document.addEventListener('change',changed,true);document.addEventListener('input',changed,true);
document.addEventListener('scroll',()=>{if(!busy())updateCurrent();},true);
document.addEventListener('keydown',event=>{if(savePromise||!saving.hidden){event.preventDefault();event.stopImmediatePropagation();return;}if(event.altKey&&!event.metaKey&&!event.ctrlKey&&['ArrowLeft','ArrowRight'].includes(event.key)&&!document.querySelector('dialog[open]')){event.preventDefault();travel(event.key==='ArrowLeft'?-1:1);}},true);
const observer=new MutationObserver(changed);for(const selector of ['#workshop','#story-events','#editor-content','#talk-list'])if($(selector))observer.observe($(selector),{childList:true,subtree:true,attributes:true,attributeFilter:['hidden','disabled']});
for(const event of ['studio-project-ready','studio-project-created'])window.addEventListener(event,changed);
new ResizeObserver(()=>document.documentElement.style.setProperty('--studio-toolbar-height',Math.ceil(bar.getBoundingClientRect().height)+'px')).observe(bar);
window.STUDIO_NAV={help,returnFromHelp,home:()=>run(home),back:()=>travel(-1),forward:()=>travel(1),changed,saveAll,prepareLeave,setAutoSave,setSaveOnExit,get saveOnExit(){return saveOnExit;},get autoSave(){return autoSave;},capture,restore,get history(){return {entries:structuredClone(entries),cursor};}};
bar.querySelector('[data-display-ids]').onclick=()=>StudentAgeRecordLabels.setVisible(!StudentAgeRecordLabels.visible).catch(error);
StudentAgeRecordLabels.apply();
changed();render();
})();
