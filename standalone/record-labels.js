/* Editor labels only. Never write display prefixes into game records. */
(()=>{
'use strict';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const valid=id=>id!==null&&id!==undefined&&/^\d+$/.test(String(id));
let shown=window.STUDIO_DISPLAY_IDS!==false,busy=false;
function apply(){
 document.documentElement.classList.toggle('hide-record-ids',!shown);
 const button=document.querySelector('[data-display-ids]');
 if(button){button.setAttribute('aria-pressed',String(shown));button.classList.toggle('active',shown);button.disabled=busy;button.title=shown?'隐藏名称前的编号':'显示名称前的编号';}
 window.dispatchEvent(new Event('studio-record-labels-changed'));
}
function prefix(id){return valid(id)?`<span class="record-id-prefix">[${esc(id)}] </span>`:'';}
function html(id,name){return prefix(id)+esc(name);}
function text(id,name){return (shown&&valid(id)?`[${id}] `:'')+String(name??'');}
// Options keep their raw label; the software dropdown formats it on display.
function option(id){return valid(id)?`data-label-id="${esc(id)}"`:'';}
async function setVisible(value){
 if(busy)return false;
 const previous=shown;busy=true;shown=!!value;apply();
 try{
  const response=await fetch('/api/display-settings',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':window.STUDIO_TOKEN},body:JSON.stringify({showRecordIds:shown})});
  const result=await response.json();if(!response.ok)throw Error(result.error||'显示设置保存失败');
  shown=result.showRecordIds;return true;
 }catch(error){shown=previous;throw error;}finally{busy=false;apply();}
}
window.StudentAgeRecordLabels={html,prefix,text,option,setVisible,apply,get visible(){return shown;},get busy(){return busy;}};
apply();
})();
