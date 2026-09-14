/* Selection is UI-only. Each editor supplies its own atomic deletion transaction. */
(()=>{'use strict';
function create(o){
 const host=o.host,chosen=new Set(),originalPressed=new WeakMap();let active=false,scope=null,anchor=null,disposed=false,pending=null,removing=false;
 const cards=()=>Array.from(host.querySelectorAll(o.selector)),id=n=>Number(n.getAttribute(o.attribute));
 const signature=()=>o.signature(),writable=()=>!disposed&&o.editable();
 function reset(){active=false;chosen.clear();anchor=null;}
 function render(){
  const key=o.scope();if(key!==scope){reset();scope=key;}
  const allowed=new Set(o.allowed().map(Number));for(const n of chosen)if(!allowed.has(n))chosen.delete(n);
  if(!writable())reset();
  const target=o.toolbar();if(!target)return;
  let bar=target.querySelector(':scope > .dialogue-selection-tools');
  if(!bar){bar=document.createElement('div');bar.className='dialogue-selection-tools';target.prepend(bar);}
  bar.innerHTML=active?`<span role="status">已选 ${chosen.size} 句</span><button data-dialogue-select="all">全选本页</button><button data-dialogue-select="delete" class="danger-text" ${chosen.size?'':'disabled'}>删除所选</button><button data-dialogue-select="close">取消多选</button>`:`<button data-dialogue-select="open" ${writable()&&allowed.size?'':'disabled'}>多选</button>`;
  for(const card of cards()){
   if(active&&!originalPressed.has(card))originalPressed.set(card,card.getAttribute('aria-pressed'));
   if(!active&&originalPressed.has(card)){const v=originalPressed.get(card);if(v===null)card.removeAttribute('aria-pressed');else card.setAttribute('aria-pressed',v);originalPressed.delete(card);}
   card.classList.toggle('dialogue-selectable',active);card.classList.toggle('dialogue-batch-selected',active&&chosen.has(id(card)));
   card.querySelector(':scope > .dialogue-selection-mark')?.remove();
   if(active){const mark=document.createElement('span');mark.className='dialogue-selection-mark';mark.setAttribute('aria-hidden','true');mark.textContent=chosen.has(id(card))?'☑':'☐';card.prepend(mark);card.setAttribute('aria-pressed',String(chosen.has(id(card))));card.setAttribute('draggable','false');}
   else if(o.draggable)card.setAttribute('draggable',String(writable()));
  }
 }
 async function remove(){
  if(!writable()||!chosen.size||pending||removing)return;
  const selection=[...chosen],key=o.scope(),before=signature();
  const dialog=document.createElement('dialog');dialog.className='save-review-dialog dialogue-delete-confirm';
  dialog.innerHTML=`<h2>删除选中的 ${selection.length} 句对话？</h2><p>删除后可以撤销。</p><footer><button data-batch-cancel>取消</button><button class="danger-button" data-batch-confirm>删除 ${selection.length} 句</button></footer>`;
  document.body.append(dialog);
  const confirmed=await new Promise(resolve=>{
   pending=value=>{dialog.close();dialog.remove();pending=null;resolve(value);};
   dialog.querySelector('[data-batch-cancel]').onclick=()=>pending?.(false);
   dialog.querySelector('[data-batch-confirm]').onclick=()=>pending?.(true);
   dialog.oncancel=e=>{e.preventDefault();pending?.(false);};dialog.showModal();dialog.querySelector('[data-batch-cancel]').focus();
  });
  if(!confirmed)return;
  removing=true;
  try{
   if(!writable()||key!==o.scope()||before!==signature())throw Error('对话已变化，未执行删除，请重新选择。');
   const result=await o.remove(selection);if(result===false)return;reset();render();
  }catch(error){o.error(error);}finally{removing=false;}
 }
 function click(e){
  const button=e.target.closest('[data-dialogue-select]');
  if(button&&host.contains(button)){
   e.preventDefault();e.stopImmediatePropagation();if(button.disabled)return;
   const action=button.dataset.dialogueSelect;
   if(action==='delete'){void remove();return;}
   if(action==='open')active=true;if(action==='close')reset();if(action==='all')for(const card of cards())chosen.add(id(card));render();return;
  }
  const card=e.target.closest(o.selector);if(!card||!host.contains(card)||!writable()||e.target.closest('input,textarea'))return;
  if(!active&&!e.ctrlKey&&!e.metaKey)return;
  e.preventDefault();e.stopImmediatePropagation();active=true;
  const current=id(card),list=cards().map(id),from=list.indexOf(anchor),to=list.indexOf(current);
  if(e.shiftKey&&from>=0)for(const n of list.slice(Math.min(from,to),Math.max(from,to)+1))chosen.add(n);
  else {if(chosen.has(current))chosen.delete(current);else chosen.add(current);anchor=current;}
  render();card.focus();
 }
 function context(e){
  const card=e.target.closest(o.selector);if(!active||!card||!writable())return;
  e.preventDefault();e.stopImmediatePropagation();if(!chosen.has(id(card))){chosen.clear();chosen.add(id(card));render();}
  StudentAgeContextMenu(e,[{label:`删除所选 ${chosen.size} 句对话`,danger:true,action:()=>void remove()},{label:'取消多选',action:()=>{reset();render();}}]);
 }
 function keydown(e){
  if(!active||e.target.closest('input,textarea,[contenteditable="true"]')||document.querySelector('dialog[open]'))return;
  if(!e.target.closest(o.selector+', .dialogue-selection-tools'))return;
  if(['Delete','Backspace'].includes(e.key)){e.preventDefault();e.stopImmediatePropagation();void remove();}
  if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();reset();render();}
 }
 function doubleClick(e){if(active&&e.target.closest(o.selector)){e.preventDefault();e.stopImmediatePropagation();}}
 for(const [name,fn]of Object.entries({click,contextmenu:context,keydown,dblclick:doubleClick}))host.addEventListener(name,fn,true);
 return {render,remove,reset,destroy(){disposed=true;pending?.(false);for(const [name,fn]of Object.entries({click,contextmenu:context,keydown,dblclick:doubleClick}))host.removeEventListener(name,fn,true);},get active(){return active;},get size(){return chosen.size;}};
}
window.StudentAgeDialogueSelection={create};})();
