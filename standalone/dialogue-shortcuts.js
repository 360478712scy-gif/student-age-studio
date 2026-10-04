/* Dialogue stepping is a selection operation; the editor owns order and draft safety. */
(()=>{
'use strict';
const defaults={previous:'Alt+ArrowUp',next:'Alt+ArrowDown'},labels={previous:'上一句',next:'下一句'};
const isMac=/Mac|iPhone|iPad/.test(navigator.platform),reservedMod=new Set(['KeyA','KeyC','KeyV','KeyX','KeyZ','KeyY','KeyS','KeyF','KeyR','KeyP','KeyL','KeyU','KeyW','KeyQ','KeyT','KeyN','KeyH','KeyJ','KeyK','KeyI','Digit0','Equal','Minus']);
let bindings={...defaults,...window.STUDIO_DIALOGUE_SHORTCUTS},stepping=false,composing=false;
const names={ArrowUp:'↑',ArrowDown:'↓',ArrowLeft:'←',ArrowRight:'→',PageUp:'Page Up',PageDown:'Page Down'};
const display=value=>value?value.split('+').map(v=>v==='Mod'?(isMac?'⌘':'Ctrl'):names[v]||v.replace(/^(Key|Digit)/,'')).join(' + '):'已禁用';
function chord(e){if(e.ctrlKey&&e.metaKey||e.getModifierState?.('AltGraph'))return '';return [e.ctrlKey||e.metaKey?'Mod':'',e.altKey?'Alt':'',e.shiftKey?'Shift':'',e.code].filter(Boolean).join('+');}
function invalid(value){if(!/^(?:Mod\+)?(?:Alt\+)?(?:Shift\+)?(?:Arrow(?:Up|Down|Left|Right)|Key[A-Z]|Digit[0-9]|F(?:[1-9]|1[0-2])|Home|End|PageUp|PageDown|Equal|Minus)$/.test(value)||!value.includes('+'))return '请使用 Ctrl / ⌘、Alt 或 Shift 加方向键、字母、数字等组合。';const parts=value.split('+'),key=parts.at(-1);if((parts.includes('Mod')&&reservedMod.has(key))||key==='F5'||key==='F11'||parts.includes('Alt')&&['ArrowLeft','ArrowRight','F4'].includes(key))return '此组合已用于编辑器、系统或浏览器操作，请换一个。';return '';}
function conflict(value,action,choices=bindings){return value&&(invalid(value)||Object.keys(labels).some(k=>k!==action&&choices[k]===value)&&'上一句和下一句不能使用相同的快捷键。')||'';}
document.addEventListener('compositionstart',()=>composing=true,true);document.addEventListener('compositionend',()=>composing=false,true);window.addEventListener('blur',()=>composing=false);
// Record before global browser-command blockers; settings keystrokes never reach editing actions.
window.addEventListener('keydown',e=>e.target._studioRecordShortcut?.(e),true);
document.addEventListener('keydown',async e=>{
 if(e.defaultPrevented||e.repeat||e.isComposing||e.keyCode===229||composing||stepping||document.querySelector('dialog[open]'))return;
 if(e.target.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"],[role="combobox"]'))return;
 const value=chord(e),action=Object.keys(labels).find(k=>bindings[k]&&bindings[k]===value);if(!action||typeof window.STUDIO_STEP_DIALOGUE!=='function')return;
 // Claim matching keys while a selection is pending, preventing browser scrolling.
 e.preventDefault();stepping=true;try{await window.STUDIO_STEP_DIALOGUE(action==='previous'?-1:1);}catch(error){window.STUDIO_REPORT_ERROR?.(error);}finally{stepping=false;}
});
function mount(body){
 const section=document.createElement('section');section.className='location-section';section.dataset.settingsGroup='preferences';
 section.innerHTML='<h3>对话切换快捷键</h3><p class="location-help">在剧情编辑中按列表顺序切换上一句或下一句。输入文字、输入法选字、弹窗和预览期间不切换。点击快捷键输入框，再按新的组合键；清除可禁用。</p>'+Object.keys(labels).map(k=>`<label class="location-path-label" for="dialogue-shortcut-${k}">${labels[k]}</label><div class="location-path-row"><input id="dialogue-shortcut-${k}" data-dialogue-shortcut="${k}" readonly aria-label="${labels[k]}快捷键" placeholder="按下组合键"><button data-shortcut-clear="${k}">清除</button></div>`).join('')+'<div class="location-actions"><button data-shortcut-reset>恢复默认</button><span class="location-help" data-shortcut-status role="status" aria-live="polite"></span></div>';body.append(section);
 const status=section.querySelector('[data-shortcut-status]');let saving=false;
 const paint=()=>{section.querySelectorAll('[data-dialogue-shortcut]').forEach(input=>input.value=display(bindings[input.dataset.dialogueShortcut]));};
 const save=async next=>{if(saving)return;saving=true;section.querySelectorAll('input,button').forEach(e=>e.disabled=true);status.textContent='正在保存…';try{const r=await fetch('/api/display-settings',{method:'POST',headers:{'X-Studio-Token':window.STUDIO_TOKEN,'Content-Type':'application/json'},body:JSON.stringify({dialogueShortcuts:next})}),data=await r.json();if(!r.ok)throw Error(data.error||'快捷键保存失败');bindings={...data.dialogueShortcuts};window.STUDIO_DIALOGUE_SHORTCUTS={...bindings};status.textContent='已保存，立即生效，下次启动保留。';}catch(error){status.textContent=error.message;}finally{saving=false;paint();section.querySelectorAll('input,button').forEach(e=>e.disabled=false);}};
 section.querySelectorAll('[data-dialogue-shortcut]').forEach(input=>{input.onfocus=()=>{if(!saving)status.textContent='请按组合键，Esc 取消；也可以按 Tab 移到下一项。';};input._studioRecordShortcut=e=>{if(e.key==='Tab')return;e.stopImmediatePropagation();e.preventDefault();if(e.key==='Escape'){paint();input.blur();return;}if(e.repeat||e.isComposing||e.keyCode===229||['Control','Meta','Alt','Shift'].includes(e.key))return;const action=input.dataset.dialogueShortcut,value=chord(e),error=conflict(value,action)||(!value?'请使用单个 Ctrl / ⌘ 与其他按键组合。':'');if(error){status.textContent=error;return;}save({...bindings,[action]:value});};});
 section.querySelectorAll('[data-shortcut-clear]').forEach(b=>b.onclick=()=>save({...bindings,[b.dataset.shortcutClear]:''}));section.querySelector('[data-shortcut-reset]').onclick=()=>save({...defaults});paint();
}
window.STUDIO_DIALOGUE_KEYS={mount,display};
})();
