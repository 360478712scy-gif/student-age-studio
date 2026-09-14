/* Updates only editor code. Save all drafts before the managed host restarts. */
(()=>{
'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(action='',body){const r=await fetch('/api/updates'+action,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Studio-Token':window.STUDIO_TOKEN},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||data.message||'更新操作未完成');return data;}
function mount(host){
 let state=null,busy=false,timer;
 function paint(){
  if(!host.isConnected){clearTimeout(timer);return;}
  host.innerHTML=`<h3>版本更新</h3><p>当前版本：${esc(state?.currentDisplayVersion||state?.currentVersion||'读取中…')}${state?.version?' → '+esc(state.displayVersion||state.version):''}</p><p class="location-help" role="status">${esc(state?.message||'正在读取更新状态…')}</p>${state?.notice?`<p class="location-help">${esc(state.notice)}</p>`:''}${state?.status==='downloading'?`<progress max="100" value="${Number(state.progress)||0}" aria-label="更新下载进度"></progress>`:''}${state?.notes?`<details><summary>版本说明</summary><p style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto">${esc(state.notes)}</p></details>`:''}<div class="location-path-row"><button data-update-check ${busy?'disabled':''}>检查更新</button>${state?.managed&&state.status==='available'?'<button class="primary" data-update-download>下载更新</button>':''}${state?.managed&&state.status==='ready'?'<button class="primary" data-update-restart>保存并重启更新</button>':''}${state?.managed&&state.canRollback?'<button data-update-rollback>恢复上一版本</button>':''}</div><p class="location-help">${state?.managed?'联网后自动检查并下载 GitHub 轻量更新，下载期间可继续编辑。更新不会替换模组、素材缓存或偏好设置。':'当前为源码预览。在线安装需要带更新功能的客户端。'}</p>`;
  if(busy)host.querySelectorAll('button').forEach(b=>b.disabled=true);
 }
 async function refresh(){try{state=await api();paint();if(state.status==='downloading'&&host.isConnected)timer=setTimeout(refresh,600);}catch(e){state={...state,message:e.message};paint();}}
 host.onclick=async e=>{
  const button=e.target.closest('button');if(!button||busy)return;
  const action=button.hasAttribute('data-update-check')?'/check':button.hasAttribute('data-update-download')?'/download':button.hasAttribute('data-update-restart')?'/restart':button.hasAttribute('data-update-rollback')?'/rollback':null;if(!action)return;
  busy=true;paint();
  try{
   if(action==='/restart'||action==='/rollback'){
    if(!window.STUDIO_NAV?.saveAll)throw Error('当前页面尚未准备好，请稍后重试。');
    const saved=await window.STUDIO_NAV.saveAll();if(saved===false)throw Error('草稿尚未保存，已取消重启。');
    if(window.STUDIO_HAS_UNSAVED_CHANGES?.())throw Error('仍有未保存的内容，已取消重启。');
   }
   state=await api(action,{});
   if(state.status==='activating'){paint();return;}
  }catch(e){state={...state,message:e.message};}
  finally{if(state?.status!=='activating')busy=false;paint();}
  if(state.status==='downloading'){clearTimeout(timer);timer=setTimeout(refresh,300);}
 };
 paint();refresh();
}
window.STUDIO_UPDATES={mount};
window.addEventListener('load',()=>{
 api('/healthy',{}).catch(()=>{});
 // Download verified code in the background; activation still requires saving all drafts.
 setTimeout(async()=>{try{const status=await api();if(!status.managed)return;const s=await api('/check',{});if(s.status==='available'){await api('/download',{});window.STUDIO_NOTIFY?.('正在后台下载 '+(s.displayVersion||s.version)+'，完成后可在工坊设置 → 版本与反馈中保存并重启更新。');}}catch{}},12000);
},{once:true});
})();
