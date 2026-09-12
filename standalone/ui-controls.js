/* Window layering. Secondary windows (dialogs) are shown as manual popovers instead of true modals: they still
   sit in the browser's top layer with a backdrop, but the page is not made inert, so the corner tools and the
   JSON drawer can be kept above them and stay usable. Browsers without the Popover API keep native modals. */
(()=>{
'use strict';
if(typeof HTMLDialogElement==='undefined'||!HTMLElement.prototype.showPopover)return;
const proto=HTMLDialogElement.prototype,nativeShowModal=proto.showModal,nativeClose=proto.close,stack=[],pinned=[];
function raise(){for(const el of pinned){if(!el.isConnected)continue;try{if(el.matches(':popover-open'))el.hidePopover();void el.getBoundingClientRect();el.showPopover();void el.getBoundingClientRect();}catch{}}}
function layered(d){return d.hasAttribute('data-studio-layered');}
proto.showModal=function(){
 if(this.open||this.matches(':popover-open'))return;
 this._studioReturnFocus=document.activeElement;
 // A transparent shield under the window swallows clicks meant for the page, as a modal backdrop would.
 const shield=document.createElement('div');shield.className='studio-layer-shield';shield.setAttribute('popover','manual');shield.setAttribute('aria-hidden','true');
 // Top-layer insertions are applied at the next style update; flushing layout between the two shows keeps
 // the shield strictly below the window (otherwise the two can land in the top layer in the wrong order).
 try{document.body.append(shield);shield.showPopover();void shield.getBoundingClientRect();this.setAttribute('popover','manual');this.setAttribute('data-studio-layered','');this.showPopover();void this.getBoundingClientRect();this.setAttribute('open','');this._studioShield=shield;}
 catch{shield.remove();this.removeAttribute('popover');this.removeAttribute('data-studio-layered');return nativeShowModal.call(this);}
 stack.push(this);
 const target=this.querySelector('[autofocus]')||this.querySelector('input:not([type=hidden]):not([disabled]),select:not([disabled]),textarea:not([disabled]),button:not([disabled]),[tabindex]:not([tabindex="-1"])');
 try{(target||this).focus({preventScroll:true});}catch{}
 raise();
};
proto.close=function(value){
 if(layered(this)){const i=stack.indexOf(this);if(i>=0)stack.splice(i,1);try{if(this.matches(':popover-open'))this.hidePopover();}catch{}this.removeAttribute('popover');this.removeAttribute('data-studio-layered');const shield=this._studioShield;this._studioShield=null;if(shield){try{if(shield.matches(':popover-open'))shield.hidePopover();}catch{}shield.remove();}}
 const result=nativeClose.call(this,value);const focus=this._studioReturnFocus;this._studioReturnFocus=null;if(focus?.isConnected&&!focus.closest('dialog:not([open])'))try{focus.focus({preventScroll:true});}catch{}return result;
};
// Dynamic feature pages may remove an open dialog; do not leave its shield behind.
new MutationObserver(()=>{for(const d of [...stack])if(!d.isConnected)d.close();}).observe(document.body,{childList:true,subtree:true});
// Escape closes the topmost layered window after a cancelable 'cancel' event, exactly like a native modal.
document.addEventListener('keydown',e=>{
 if(e.key!=='Escape'||e.defaultPrevented||e.isComposing||e.keyCode===229)return;
 const top=stack.filter(d=>d.isConnected&&d.open).at(-1);if(!top)return;
 // A pinned drawer owns its search/confirmation Escape; it must not close an unrelated dialog.
 if(pinned.some(el=>el.contains(e.target)))return;
 e.preventDefault();e.stopImmediatePropagation();if(top.dispatchEvent(new Event('cancel',{cancelable:true})))top.close();
},true);
window.addEventListener('keydown',e=>{
 const top=stack.filter(d=>d.isConnected&&d.open).at(-1);if(!top||pinned.some(el=>el.contains(e.target)))return;
 if((e.ctrlKey||e.metaKey)&&!top.classList.contains('uc-popup')){if(e.key.toLowerCase()==='s')e.preventDefault();e.stopImmediatePropagation();return;}
 if(e.key==='Tab'){
  const nodes=[...top.querySelectorAll('button,input,select,textarea,a[href],[tabindex]')].filter(el=>!el.disabled&&el.tabIndex>=0&&el.getClientRects().length);
  const at=nodes.indexOf(document.activeElement);if(!nodes.length){e.preventDefault();top.focus();return;}
  if(at<0||e.shiftKey&&at===0||!e.shiftKey&&at===nodes.length-1){e.preventDefault();nodes[e.shiftKey?nodes.length-1:0].focus();}
 }
},true);
// Clicking the backdrop of a layered window reaches the dialog element itself; nothing behind it.
window.STUDIO_LAYERING={keepOnTop(el){if(!pinned.includes(el))pinned.push(el);try{el.setAttribute('popover','manual');if(!el.matches(':popover-open'))el.showPopover();}catch{}raise();},release(el){const i=pinned.indexOf(el);if(i>=0)pinned.splice(i,1);try{if(el.matches(':popover-open'))el.hidePopover();}catch{}},raise,topmost:()=>stack.filter(d=>d.isConnected&&d.open).at(-1)||null};
})();
/* Software-drawn choices. Native selects remain the application's data interface. */
(()=>{
'use strict';
// pywebview exposes its bridge asynchronously; all libraries share this adapter.
function connectWindowsFolders(){
 if(!window.STUDIO_CHOOSE_ASSET_FOLDER&&window.pywebview?.api?.choose_folder)
  window.STUDIO_CHOOSE_ASSET_FOLDER=kind=>window.pywebview.api.choose_folder(kind);
}
connectWindowsFolders();window.addEventListener('pywebviewready',connectWindowsFolders);

if(window.StudentAgeUIControls)return;
// Keep Chinese IME text in its existing input until the candidate is committed.
// Rebuilding a search result panel during composition can discard the candidate.
const composingSearches=new WeakSet(),searchInput=node=>node?.matches?.('input[type="search"],input[id*="search"],input[placeholder*="搜索"]');
document.addEventListener('compositionstart',event=>{if(searchInput(event.target))composingSearches.add(event.target);},true);
window.addEventListener('keydown',event=>{if(searchInput(event.target)&&(event.isComposing||event.keyCode===229||composingSearches.has(event.target)))event.stopImmediatePropagation();},true);
document.addEventListener('input',event=>{if(searchInput(event.target)&&(event.isComposing||composingSearches.has(event.target)))event.stopImmediatePropagation();},true);
document.addEventListener('compositionend',event=>{const node=event.target;if(!searchInput(node))return;composingSearches.delete(node);node.dispatchEvent(new Event('input',{bubbles:true}));},true);
function trimSmallSearches(){
 for(const dialog of document.querySelectorAll('dialog[open]:not(.uc-popup)')){
  for(const input of dialog.querySelectorAll('input[type=search],input[id*=search],input[placeholder*=搜索]')){
   if(input.value.trim())continue;
   const container=input.closest('.character-picker-body,.condition-browser-catalog,.action-library,.warehouse-icon-picker,.wk-picker')||dialog;
   const list=container.querySelector('#wk-ref-rows,.character-choice-grid,.condition-library-results,.warehouse-grid,.character-media-grid');
   if(!list||/正在|加载/.test(list.textContent)&&!list.querySelector('button'))continue;
   const count=list.querySelectorAll(':scope>button').length;
   if(container.querySelector('[data-media-more]:not([hidden]),[data-picker-more]:not([hidden])'))continue;
   const hidden=!input.classList.contains('condition-library-search')&&count<10;if(input.hidden!==hidden)input.hidden=hidden;
  }
 }
}
let trimQueued=false;new MutationObserver(()=>{if(trimQueued)return;trimQueued=true;requestAnimationFrame(()=>{trimQueued=false;trimSmallSearches();});}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['open']});
const controls=new Map(),byButton=new WeakMap(),visible=new Set(),pending=new Set();
const PAGE=80;let serial=0,scheduled=false,active=null,popup=null,search=null,list=null,summary=null,previous=null,next=null;
const text=(value)=>String(value??'');
const isDisabled=select=>select.disabled||select.matches(':disabled');
const connected=info=>info.select.isConnected&&info.wrapper.isConnected&&info.wrapper.contains(info.select);
const isShown=info=>connected(info)&&!info.select.hidden&&info.button.getClientRects().length>0;

function labelText(node){
 if(node.nodeType===Node.TEXT_NODE)return node.textContent;
 if(node.nodeType!==Node.ELEMENT_NODE||node.matches('select,.uc-select,.uc-trigger'))return '';
 return Array.from(node.childNodes,labelText).join(' ');
}
function nameOf(select){
 const labelled=select.getAttribute('aria-labelledby');
 return select.getAttribute('aria-label')||(labelled?labelled.split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' '):'')||
  Array.from(select.labels||[],labelText).join(' ').replace(/\s+/g,' ').trim()||select.title||'选择一项';
}
function optionText(option){return window.StudentAgeRecordLabels?.text(option.dataset.labelId,option.label||option.textContent)||option.label||option.textContent||'';}
function selectionText(select){
 const selected=select.selectedOptions;
 if(!selected.length)return select.getAttribute('data-placeholder')||'请选择';
 if(!select.multiple)return optionText(selected[0])||'请选择';
 return Array.from(selected).slice(0,2).map(option=>optionText(option)).join('、')+(selected.length>2?' 等 '+selected.length+' 项':'');
}
function sync(info){
 if(!connected(info))return;
 const select=info.select,label=selectionText(select),name=nameOf(select),disabled=isDisabled(select);
 if(info.caption.textContent!==label)info.caption.textContent=label;
 if(info.button.disabled!==disabled)info.button.disabled=disabled;
 const title=name+'：'+label;
 if(info.button.getAttribute('aria-label')!==title)info.button.setAttribute('aria-label',title);
 if(info.button.title!==label)info.button.title=label;
 if(info.wrapper.hidden!==select.hidden)info.wrapper.hidden=select.hidden;
 info.button.setAttribute('aria-required',String(select.required));
}
const intersection=typeof IntersectionObserver==='function'?new IntersectionObserver(entries=>{
 for(const entry of entries){const info=byButton.get(entry.target);if(!info)continue;if(entry.isIntersecting){visible.add(info);sync(info)}else visible.delete(info)}
}):null;

function enhance(select){
 if(!(select instanceof HTMLSelectElement)||select.closest('.uc-popup'))return;
 const old=controls.get(select);if(old&&connected(old)){pending.add(old);return}
 const wrapper=document.createElement('span');wrapper.className='uc-select';
 const button=document.createElement('button');button.type='button';button.className='uc-trigger';button.setAttribute('role','combobox');button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');
 button.id='uc-trigger-'+(++serial);button.dataset.ucSelect=select.id||'';
 const caption=document.createElement('span');caption.className='uc-caption';
 const chevron=document.createElement('span');chevron.className='uc-chevron';chevron.setAttribute('aria-hidden','true');chevron.textContent='⌄';
 button.append(caption,chevron);select.before(wrapper);wrapper.append(select,button);
 select.classList.add('uc-native');select.setAttribute('aria-hidden','true');select.tabIndex=-1;
 const info={select,wrapper,button,caption};controls.set(select,info);byButton.set(button,info);sync(info);
 if(intersection)intersection.observe(button);else visible.add(info);
 button.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();open(info)});
 select.addEventListener('pointerdown',event=>{event.preventDefault();event.stopPropagation();open(info)});
 select.addEventListener('mousedown',event=>event.preventDefault());
 select.addEventListener('focus',()=>{if(!isDisabled(select))button.focus({preventScroll:true})});
}
function discover(root){
 if(root.nodeType!==Node.ELEMENT_NODE&&root.nodeType!==Node.DOCUMENT_NODE)return;
 if(root instanceof HTMLSelectElement)enhance(root);
 if(root.matches?.('option,optgroup')||root.closest?.('.uc-popup'))return;
 root.querySelectorAll?.('select').forEach(enhance);
}
function schedule(){
 if(scheduled)return;scheduled=true;
 queueMicrotask(()=>{
  scheduled=false;
  for(const [select,info] of controls){if(!connected(info)){controls.delete(select);visible.delete(info);intersection?.unobserve(info.button)}}
  for(const info of pending){if(connected(info)&&(visible.has(info)||isShown(info)))sync(info)}pending.clear();
  if(active&&(!isShown(active.info)||isDisabled(active.info.select)))close(false);
  else if(active&&active.stale){active.stale=false;readRows();filterRows(false)}
 });
}
function createPopup(){
 if(popup)return;
 popup=document.createElement('dialog');popup.className='uc-popup';popup.id='uc-choice-popup';popup.setAttribute('aria-label','选择内容');
 const head=document.createElement('div');head.className='uc-popup-head';
 const title=document.createElement('strong');title.className='uc-popup-title';title.id='uc-popup-title';
 const dismiss=document.createElement('button');dismiss.type='button';dismiss.className='uc-close';dismiss.setAttribute('aria-label','关闭选择菜单');dismiss.textContent='×';dismiss.onclick=()=>close();head.append(title,dismiss);
 search=document.createElement('input');search.type='search';search.className='uc-search';search.placeholder='搜索选项';search.autocomplete='off';search.setAttribute('aria-label','搜索选项');search.setAttribute('role','combobox');search.setAttribute('aria-expanded','true');search.setAttribute('aria-controls','uc-options');search.setAttribute('aria-autocomplete','list');
 list=document.createElement('div');list.id='uc-options';list.className='uc-options';list.setAttribute('role','listbox');list.setAttribute('aria-labelledby',title.id);
 const foot=document.createElement('div');foot.className='uc-popup-foot';summary=document.createElement('span');summary.className='uc-summary';summary.setAttribute('aria-live','polite');
 previous=document.createElement('button');previous.type='button';previous.textContent='上一页';previous.onclick=()=>changePage(-1);
 next=document.createElement('button');next.type='button';next.textContent='下一页';next.onclick=()=>changePage(1);foot.append(summary,previous,next);
 popup.append(head,search,list,foot);document.body.append(popup);
 search.addEventListener('input',()=>filterRows(false));
 popup.addEventListener('cancel',event=>{event.preventDefault();event.stopPropagation();close()});
 popup.addEventListener('close',()=>{if(active)close()});
 popup.addEventListener('pointerdown',event=>{
  const r=popup.getBoundingClientRect();if(event.clientX>=r.left&&event.clientX<=r.right&&event.clientY>=r.top&&event.clientY<=r.bottom)return;
  event.preventDefault();event.stopPropagation();const x=event.clientX,y=event.clientY;close(false);
  const button=document.elementFromPoint(x,y)?.closest('.uc-trigger');if(button)open(byButton.get(button));
 });
}
function readRows(){
 const {select}=active.info;
 active.rows=Array.from(select.options,(option,index)=>({option,index,label:optionText(option),hidden:option.hidden||option.parentElement.hidden,group:option.parentElement instanceof HTMLOptGroupElement?option.parentElement.label:'',disabled:option.disabled||(option.parentElement instanceof HTMLOptGroupElement&&option.parentElement.disabled)}));
 search.hidden=select.dataset.noSearch==='true'||active.rows.filter(row=>!row.hidden).length<10;if(search.hidden)search.value='';
}
function filterRows(initial){
 if(!active)return;const query=search.value.trim().toLocaleLowerCase();
 active.filtered=active.rows.filter(row=>!row.hidden&&(!query||StudentAgeSearch.matches(query,row.label,row.group,row.option.dataset.labelId)));
 const selected=initial?active.filtered.findIndex(row=>row.option.selected):-1;
 active.focused=selected>=0?selected:active.filtered.findIndex(row=>!row.disabled);active.page=Math.floor(Math.max(0,active.focused)/PAGE);renderRows();
}
function renderRows(){
 clearTip();if(!active)return;const start=active.page*PAGE,fragment=document.createDocumentFragment();let group=null;
 for(let index=start;index<Math.min(start+PAGE,active.filtered.length);index++){
  const row=active.filtered[index];if(row.group!==group){group=row.group;if(group){const heading=document.createElement('div');heading.className='uc-optgroup';heading.textContent=group;heading.setAttribute('role','presentation');fragment.append(heading)}}
  const item=document.createElement('button');item.type='button';item.className='uc-option'+(index===active.focused?' uc-focused':'');item.id='uc-option-'+row.index;item.tabIndex=-1;item.setAttribute('role','option');item.setAttribute('aria-selected',String(row.option.selected));item.disabled=row.disabled;item.dataset.ucIndex=String(row.index);
  const label=document.createElement('span');label.className='uc-option-label';label.textContent=row.label;
  const tick=document.createElement('span');tick.className='uc-check';tick.setAttribute('aria-hidden','true');tick.textContent=row.option.selected?'✓':'';item.append(label,tick);
  item.addEventListener('pointermove',()=>{if(active&&active.focused!==index&&!row.disabled){active.focused=index;paintFocus()}});
  if(row.option.dataset.hoverTip){item.addEventListener('pointerenter',()=>armTip(item,row.option.dataset.hoverTip));item.addEventListener('pointerleave',clearTip);}
  item.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();choose(row)});fragment.append(item);
 }
 if(!active.filtered.length){const empty=document.createElement('p');empty.className='uc-empty';empty.textContent='没有匹配的选项';fragment.append(empty)}
 list.replaceChildren(fragment);const pages=Math.max(1,Math.ceil(active.filtered.length/PAGE));summary.textContent=active.filtered.length+' 项'+(pages>1?' · '+(active.page+1)+' / '+pages:'');previous.hidden=next.hidden=pages<=1;previous.disabled=active.page===0;next.disabled=active.page>=pages-1;
 list.setAttribute('aria-multiselectable',String(active.info.select.multiple));paintFocus();position();
}
function paintFocus(){
 if(!active)return;const row=active.filtered[active.focused],id=row?'uc-option-'+row.index:'';
 for(const node of list.querySelectorAll('.uc-option'))node.classList.toggle('uc-focused',node.id===id);
 if(id&&document.getElementById(id))search.setAttribute('aria-activedescendant',id);else search.removeAttribute('aria-activedescendant');
}
function position(){
 if(!active||!popup.open)return;const rect=active.info.button.getBoundingClientRect(),view=window.visualViewport;
 const width=view?.width||innerWidth,height=view?.height||innerHeight,leftEdge=view?.offsetLeft||0,topEdge=view?.offsetTop||0,padding=12;
 const panelWidth=Math.min(Math.max(rect.width,340),width-padding*2);
 popup.style.width=panelWidth+'px';popup.style.maxHeight=Math.min(480,height-padding*2)+'px';
 const panelHeight=popup.getBoundingClientRect().height;
 const left=Math.max(leftEdge+padding,Math.min(rect.left,leftEdge+width-panelWidth-padding));
 let top=rect.bottom+7;if(top+panelHeight>topEdge+height-padding)top=rect.top-panelHeight-7;
 top=Math.max(topEdge+padding,Math.min(top,topEdge+height-panelHeight-padding));
 popup.style.left=left+'px';popup.style.top=top+'px';
}
function open(info,initialQuery=''){
 if(!info||!connected(info)||isDisabled(info.select))return;
 if(active?.info===info){close();return}if(active)close(false);sync(info);createPopup();
 active={info,rows:[],filtered:[],focused:-1,page:0,stale:false};popup.classList.toggle('uc-toolbar-popup',['studio-project','studio-feature'].includes(info.select.id));popup.querySelector('.uc-popup-title').textContent=nameOf(info.select);search.hidden=info.select.dataset.noSearch==='true';search.value=search.hidden?'':initialQuery;
 info.button.setAttribute('aria-expanded','true');info.button.setAttribute('aria-controls',list.id);
 popup.showModal();readRows();filterRows(!initialQuery);if(!search.hidden)search.focus({preventScroll:true});else list.querySelector('button:not(:disabled)')?.focus({preventScroll:true});
 const selected=list.querySelector('[aria-selected="true"]');selected?.scrollIntoView({block:'nearest'});
}
function focusBack(info){
 requestAnimationFrame(()=>{let replacement=info;if(!connected(info)&&info.select.id)replacement=controls.get(document.getElementById(info.select.id));if(replacement&&isShown(replacement)&&!isDisabled(replacement.select))replacement.button.focus({preventScroll:true})});
}
// Long hover on an option (e.g. a mod) reveals its full path after 2 s; leaving or switching resets the timer.
let tipTimer=null,tipNode=null;
function clearTip(){clearTimeout(tipTimer);tipTimer=null;if(tipNode){tipNode.remove();tipNode=null;}}
function armTip(item,text){clearTip();tipTimer=setTimeout(()=>{if(!active||!item.isConnected||!popup.open)return;tipNode=document.createElement('div');tipNode.className='uc-hover-tip';tipNode.setAttribute('role','tooltip');tipNode.textContent=text;popup.append(tipNode);const r=item.getBoundingClientRect(),p=popup.getBoundingClientRect();tipNode.style.left=Math.max(8,r.left-p.left)+'px';tipNode.style.top=(r.bottom-p.top+4)+'px';tipNode.style.maxWidth=Math.max(160,p.width-16)+'px';},2000);}
function close(restoreFocus=true){
 clearTip();if(!active)return;const info=active.info;active=null;info.button.setAttribute('aria-expanded','false');info.button.removeAttribute('aria-controls');if(popup.open)popup.close();if(restoreFocus)focusBack(info);
}
function choose(row){
 if(!active||row.disabled||!connected(active.info)||isDisabled(active.info.select))return;
 const info=active.info,select=info.select;if(row.option.parentElement?.closest('select')!==select)return;
 const changed=select.multiple||select.selectedIndex!==row.index;
 if(select.multiple)row.option.selected=!row.option.selected;else select.selectedIndex=row.index;
 const multiple=select.multiple;if(!multiple)close(false);sync(info);
 if(changed){select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}))}
 if(multiple&&active){if(connected(info)){readRows();filterRows(false);search.focus({preventScroll:true})}else close(false)}else focusBack(info);
}
function moveFocus(amount,edge){
 if(!active?.filtered.length)return;const count=active.filtered.length;let index=edge==='start'?0:edge==='end'?count-1:Math.min(count-1,Math.max(0,active.focused+amount)),step=edge==='end'||amount<0?-1:1;
 while(index>=0&&index<count&&active.filtered[index].disabled)index+=step;if(index<0||index>=count)return;
 active.focused=index;const page=Math.floor(index/PAGE);if(page!==active.page){active.page=page;renderRows()}else paintFocus();
 document.getElementById('uc-option-'+active.filtered[index].index)?.scrollIntoView({block:'nearest'});
}
function changePage(delta){if(!active)return;const page=Math.max(0,Math.min(Math.ceil(active.filtered.length/PAGE)-1,active.page+delta));active.focused=page*PAGE;active.page=page;renderRows();search.focus({preventScroll:true})}
window.addEventListener('keydown',event=>{
 // Let Chinese input methods finish composing before using Enter or Escape.
 if(event.isComposing||event.keyCode===229)return;
 if(active){
  if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();return}
  if(!popup.contains(event.target))return;
  const keys=['ArrowDown','ArrowUp','PageDown','PageUp','Enter'];if((event.key==='Home'||event.key==='End')&&(event.ctrlKey||event.metaKey))keys.push(event.key);
  if(!keys.includes(event.key)||event.target.closest('.uc-close,.uc-popup-foot'))return;
  event.preventDefault();event.stopImmediatePropagation();
  if(event.key==='Enter'){const row=active.filtered[active.focused];if(row)choose(row)}
  else moveFocus(event.key==='ArrowDown'?1:event.key==='ArrowUp'?-1:event.key==='PageDown'?PAGE:-PAGE,event.key==='Home'?'start':event.key==='End'?'end':null);
 }else{
  const info=byButton.get(event.target)||controls.get(event.target);if(!info||event.ctrlKey||event.metaKey||event.altKey&&event.key!=='ArrowDown')return;
  if(['ArrowDown','ArrowUp','Enter',' '].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();open(info)}
  else if(event.key.length===1){event.preventDefault();event.stopImmediatePropagation();open(info,event.key)}
 }
},true);
document.addEventListener('change',event=>{const info=controls.get(event.target);if(info){sync(info);if(active?.info===info){active.stale=true;schedule()}}},true);
document.addEventListener('input',event=>{const info=controls.get(event.target);if(info)sync(info)},true);
window.addEventListener('studio-record-labels-changed',()=>{for(const info of controls.values())if(isShown(info))sync(info);if(active){readRows();filterRows(false)}});
window.addEventListener('resize',position);window.visualViewport?.addEventListener('resize',position);
document.addEventListener('scroll',event=>{if(active&&!popup.contains(event.target)){if(isShown(active.info))position();else close(false)}},true);
const observer=new MutationObserver(records=>{
 for(const record of records){
  if(record.target.nodeType===Node.ELEMENT_NODE&&record.target.closest('.uc-popup'))continue;
  const element=record.target.nodeType===Node.ELEMENT_NODE?record.target:record.target.parentElement,select=element instanceof HTMLSelectElement?element:element?.closest('select'),info=controls.get(select);
  if(info){pending.add(info);if(active?.info===info)active.stale=true}
  if(record.type==='childList')for(const node of record.addedNodes)discover(node);
  if(record.type==='attributes'&&element?.matches('fieldset,select,[hidden]'))discover(element);
 }schedule();
});
function start(){discover(document);observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['disabled','selected','label','hidden','aria-label','aria-labelledby','required','multiple']});schedule()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
// Application code can assign .value without dispatching an event. Refresh only
// controls in the viewport; every popup also rereads options and selection on open.
setInterval(()=>{if(document.hidden)return;for(const info of visible)if(isShown(info))sync(info)},400);
window.StudentAgeUIControls={refresh(root=document){discover(root);for(const info of controls.values())if(isShown(info))sync(info);schedule()},open(select){const node=typeof select==='string'?document.querySelector(select):select;enhance(node);open(controls.get(node))},close};
})();
