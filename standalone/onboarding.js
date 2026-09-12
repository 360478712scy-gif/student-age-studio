/* First-run setup plus non-blocking media cache progress. */
(()=>{'use strict';
const root=document.getElementById('studio-onboarding'),q=s=>root.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels=['准备资料','素材与缓存','偏好设置','认识工具栏','欢迎参加公测'];
const kinds=[['portrait','人物立绘','角色与服装'],['background','场景背景','故事发生的地方'],['cg','CG 插画','值得记住的瞬间'],['audio','音乐与音效','为故事添上声音'],['social','动态配图','企鹅空间的照片'],['avatar','人物头像','每个角色的面孔']];
const api=async(path,data)=>{const r=await fetch('/api/'+path,{method:data===undefined?'GET':'POST',headers:{'X-Studio-Token':STUDIO_TOKEN,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error||'操作未完成');return v;};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
let first=window.STUDIO_ONBOARDING_COMPLETE!==true,step=0,ready=false,working=false,folderState={folders:{}},drafts={},preferences={},locations={},cacheSettings={},cacheDraft='',prepared=null,initialized=false;
function notice(text){const e=q('[data-onboarding-notice]');if(e)e.textContent=text||'';}
function controls(){if(!q('[data-guide-next]'))return;q('[data-guide-next]').disabled=working||step===0&&!ready;q('[data-guide-back]').disabled=working;q('[data-guide-skip]').disabled=working;}
function shell(){
 root.dataset.first=String(first);root.classList.remove('brand-only');
 root.innerHTML=`<div class="guide-shell"><aside class="guide-identity"><img class="guide-logo" src="/icon.png" alt="拾光工坊图标"><h1>拾光工坊</h1><p>学生时代模组编辑器</p><span class="guide-version">BETA 1.2.3</span><ol>${labels.map((v,i)=>`<li data-guide-step="${i}" ${i===step?'aria-current="step"':''}><span>${String(i+1).padStart(2,'0')}</span>${v}</li>`).join('')}</ol><small>拾起灵感，写下你的学生时代。</small></aside><section class="guide-content"><div class="guide-page" id="guide-page" tabindex="-1"></div><p class="guide-notice" data-onboarding-notice role="status" aria-live="polite"></p><footer class="guide-footer"><button data-guide-back>上一步</button><span></span><button data-guide-skip>暂时跳过</button><button class="primary" data-guide-next>继续 <span aria-hidden="true">→</span></button></footer></section></div>`;
 q('[data-guide-back]').onclick=()=>{if(step>0){step--;render();}};
 q('[data-guide-next]').onclick=()=>advance(false);
 q('[data-guide-skip]').onclick=()=>advance(true);
 render();
}
function render(){
 root.dataset.step=String(step+1);root.querySelectorAll('[data-guide-step]').forEach(n=>{if(Number(n.dataset.guideStep)===step)n.setAttribute('aria-current','step');else n.removeAttribute('aria-current');n.classList.toggle('done',Number(n.dataset.guideStep)<step);});
 const page=q('#guide-page');page.classList.remove('guide-enter');
 q('[data-guide-back]').hidden=step===0;q('[data-guide-skip]').hidden=true;q('[data-guide-next]').innerHTML=step===4?'进入拾光工坊 <span aria-hidden="true">→</span>':'继续 <span aria-hidden="true">→</span>';
 if(step===0){page.innerHTML='<span class="guide-eyebrow">从这里开始</span><h2>先把创作资料准备好</h2><p class="guide-description">正在读取模组目录。素材缓存会在后台继续，可以先完成设置并开始编辑。</p><div class="guide-preparation"><div class="guide-orbit"><img src="/icon.png" alt=""></div><h3 data-prepare-phase>正在准备…</h3><progress data-prepare-progress aria-label="素材准备进度"></progress><p data-prepare-count></p></div><p class="guide-caption">原版素材与可用预览保存在本机。原版和模组素材会自动在后台准备，素材发生变化时只更新变化部分。</p><div class="guide-preparation-issues" data-prepare-issues></div>';updateProgress(prepared);}
 if(step===1){page.innerHTML=`<span class="guide-eyebrow">给灵感安个家</span><h2>你的素材，放在哪里？</h2><p class="guide-description">缓存路径必须设置；素材文件夹可选，之后也能在素材仓库添加。</p><div class="guide-folders">${cacheField()}${kinds.map(([kind,title,hint])=>`<label class="guide-folder"><span><strong>${title}</strong><small>${hint}</small></span><div><input data-guide-folder="${kind}" aria-label="${title}文件夹路径" placeholder="尚未设置 · 可粘贴完整路径" value="${esc(drafts[kind]??folderState.folders[kind]?.path??'')}"><button type="button" data-guide-browse="${kind}">选择</button></div></label>`).join('')}</div>`;bindCache(page);page.querySelectorAll('[data-guide-folder]').forEach(n=>n.oninput=()=>{drafts[n.dataset.guideFolder]=n.value;});page.querySelectorAll('[data-guide-browse]').forEach(n=>n.onclick=()=>chooseFolder(n.dataset.guideBrowse));}
 if(step===2){const options=[['saveOnExit','退出时自动保存','开启后退出编辑器会先保存；关闭时，有未保存内容会询问你。'],['backupCleanup','自动清理旧备份','每个模组保留最近 5 份完整备份，较旧备份自动删除。'],['logCleanup','自动清理错误日志','保留最近 20 份错误日志，方便定位问题。'],['showRecordIds','显示编号 ID','在事件、对话、人物和物品旁显示游戏编号。']];page.innerHTML=`<span class="guide-eyebrow">按你的习惯来</span><h2>选择适合你的工作方式</h2><p class="guide-description">这些设置保存在本机，之后仍可在顶部工具栏或工坊设置中调整。</p><div class="guide-preferences">${options.map(([key,title,hint])=>`<label class="guide-preference"><span><strong>${title}</strong><small>${hint}</small></span><input type="checkbox" data-guide-pref="${key}" role="switch" ${preferences[key]?'checked':''}><span class="guide-switch" aria-hidden="true"></span></label>`).join('')}</div>`;page.querySelectorAll('[data-guide-pref]').forEach(n=>n.onchange=()=>{preferences[n.dataset.guidePref]=n.checked;});}
 if(step===3){const items=[['↶ ↷','后退与前进','返回浏览过的页面，不撤销内容。'],['▣','模组选择 / 刷新','切换本地或订阅模组，重新读取目录。'],['⌂','工坊主页','回到功能入口与收藏。'],['＋','新建模组','创建自己的独立作品。'],['▧','创建副本','复制当前模组，保留原作。'],['↶ ↷','撤销 / 重做','撤销或恢复编辑修改。'],['↓','保存模组','保存当前修改；支持 Ctrl / ⌘ + S。'],['✓','自动保存','离开编辑页面时自动保存。退出设置在工坊设置中。'],['▱','手动备份','先保存，再备份完整模组。'],['#','显示 ID','显示或隐藏游戏编号。'],['?','操作说明','查看编辑功能的使用方法。'],['⚙','工坊设置','游戏与模组目录、退出保存、备份和错误日志。']];page.innerHTML=`<span class="guide-eyebrow">认识你的创作桌面</span><h2>常用操作，都在顶部</h2><p class="guide-description">不同页面共用一套工具栏。不可用的操作会自动变灰。</p><div class="guide-toolbar-map">${items.map(([icon,title,hint])=>`<article><span aria-hidden="true">${icon}</span><div><strong>${title}</strong><p>${hint}</p></div></article>`).join('')}</div>`;}
 if(step===4){page.innerHTML='<span class="guide-eyebrow">BETA 1.2.3 · 公测邀请</span><h2>欢迎，一起拾起这段时光。</h2><p class="guide-description">感谢你参加拾光工坊 Beta 公测。无论是遇到 Bug、提出建议，还是交流模组创作，都欢迎告诉我们。</p><div class="guide-welcome-mark"><img src="/icon.png" alt="拾光工坊"></div><div class="guide-contacts"><div><span>反馈与编辑器讨论 QQ 群</span><strong>1121725122</strong><button data-guide-copy="1121725122">复制群号</button></div><div><span>也可以通过邮箱反馈</span><strong>360478712scy@gmail.com</strong><button data-guide-copy="360478712scy@gmail.com">复制邮箱</button></div></div><p class="guide-caption">反馈问题时，附上软件版本、操作步骤和错误日志，会更容易找到原因。</p>';page.querySelectorAll('[data-guide-copy]').forEach(n=>n.onclick=async()=>{try{await navigator.clipboard.writeText(n.dataset.guideCopy);notice('已复制。');}catch{notice('请复制：'+n.dataset.guideCopy);}});}
 void page.offsetWidth;page.classList.add('guide-enter');controls();notice('');page.focus({preventScroll:true});
}
function updateProgress(state){if(!state)return;prepared=state;const phase=q('[data-prepare-phase]'),progress=q('[data-prepare-progress]'),count=q('[data-prepare-count]');if(phase)phase.textContent=state.phase;if(progress){if(state.total){progress.max=state.total;progress.value=state.done||0;}else progress.removeAttribute('value');}if(count)count.textContent=[state.projectCount!=null?state.projectCount+' 个模组':'',state.assets?state.assets+' 条素材记录':'',state.total?`${state.done} / ${state.total}`:''].filter(Boolean).join(' · ');const issues=q('[data-prepare-issues]');if(issues&&state.warnings?.length)issues.innerHTML='<details><summary>部分素材的准备说明</summary>'+state.warnings.map(s=>'<p>'+esc(s)+'</p>').join('')+'</details>';}
let cachePromise=null,cacheHideTimer;
const cacheBall=document.createElement('button');
cacheBall.id='studio-cache-progress';cacheBall.type='button';cacheBall.hidden=true;
cacheBall.setAttribute('aria-live','polite');document.body.append(cacheBall);
const cacheDetails=document.createElement('section');cacheDetails.id='studio-cache-details';cacheDetails.hidden=true;
cacheDetails.innerHTML='<strong data-cache-phase></strong><p data-cache-description></p><button type="button" data-cache-retry>重试缓存</button><button type="button" data-cache-close>收起</button>';
document.body.append(cacheDetails);
cacheBall.onclick=()=>{cacheDetails.hidden=!cacheDetails.hidden;};
cacheDetails.querySelector('[data-cache-close]').onclick=()=>{cacheDetails.hidden=true;cacheBall.focus();};
cacheDetails.querySelector('[data-cache-retry]').onclick=()=>prepare();
const cacheTasks=new Map();
function summarizeCache(){
 const running=[...cacheTasks.values()].filter(s=>s.status==='running');
 if(running.length){const percent=Math.floor(running.reduce((v,s)=>v+(Number(s.percent)||0),0)/running.length);paintCache({status:'running',phase:running.map(s=>s.phase).join('；'),percent,warnings:[],abandoned:running.flatMap(s=>s.abandoned||[])});}
 else{const problem=[...cacheTasks.values()].find(s=>s.status==='error'||s.warnings?.length);paintCache(problem||{status:'complete',phase:'后台缓存完成',percent:100,warnings:[]});}
}
function showCache(state){if(state.status==='running'||state.status==='error'||state.warnings?.length)cacheTasks.set('startup',state);else cacheTasks.delete('startup');summarizeCache();}
window.STUDIO_CACHE_TASKS={
 update(key,phase,percent=0){cacheTasks.set(key,{status:'running',phase,percent,warnings:[]});summarizeCache();},
 finish(key){if(cacheTasks.delete(key))summarizeCache();}
};
// Native modal dialogs occupy the top layer, above every ordinary z-index.
// Move the same small indicator into the latest open dialog, keeping it visible.
function placeCache(){const dialogs=[...document.querySelectorAll('dialog[open]')],parent=dialogs.at(-1)||document.body;for(const node of [cacheBall,cacheDetails])if(node.parentNode!==parent)parent.append(node);}
new MutationObserver(placeCache).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});
async function watchBackground(){
 try{if(!document.hidden){const result=await api('background-status'),seen=new Set();for(const task of result.tasks||[]){const key='server:'+task.id;seen.add(key);cacheTasks.set(key,{status:task.status||'running',phase:task.phase,percent:task.percent,warnings:task.warnings||[],abandoned:task.abandoned||[]});summarizeCache();}for(const key of [...cacheTasks.keys()])if(key.startsWith('server:')&&!seen.has(key))window.STUDIO_CACHE_TASKS.finish(key);}}
 catch{/* Poll again without blocking an editor or discarding existing progress. */}
 setTimeout(watchBackground,1500);
}
watchBackground();
function paintCache(state){
 clearTimeout(cacheHideTimer);
 const running=state.status==='running',issue=state.status==='error'||!!state.warnings?.length;
 const percent=Math.max(0,Math.min(100,Math.floor(Number(state.percent)||0)));
 const label=issue?'缓存部分未完成':running?'后台缓存中':'缓存完成';
 placeCache();cacheBall.hidden=false;cacheBall.textContent=percent+'%';cacheBall.dataset.status=issue?'error':state.status;
 cacheBall.style.setProperty('--cache-progress',percent+'%');
 cacheBall.title=label+' · '+state.phase+'（点击查看）';cacheBall.setAttribute('aria-label',label+'，'+percent+'%，点击查看详情');
 cacheDetails.querySelector('[data-cache-phase]').textContent=state.phase;
 const abandoned=state.abandoned?.length?`已放弃 ${state.abandoned.length} 项连续多次失败的素材（改动文件或点“重试”会再次尝试）：${state.abandoned.join('；')}`:'';
 cacheDetails.querySelector('[data-cache-description]').textContent=[issue?(state.warnings||[]).join('；'):'可以继续编辑。尚未缓存的素材会在准备完成后可用。',abandoned].filter(Boolean).join('\n');
 cacheDetails.querySelector('[data-cache-retry]').hidden=!issue;
 if(!running&&!issue)cacheHideTimer=setTimeout(()=>{cacheBall.hidden=true;cacheDetails.hidden=true;},4000);
}
function prepare(){
 if(cachePromise)return cachePromise;
 let release;
 cachePromise=new Promise(resolve=>{release=resolve;});
 const readyPromise=cachePromise;
 // Keep monitoring after releasing the startup gate. Finishing/retrying must
 // never reload the project or replace an editor containing an unsaved draft.
 (async()=>{try{
   let state=await api('startup-preparation',{});
   while(true){
     updateProgress(state);showCache(state);
     if(state.editorReady||state.status!=='running')release(state);
     if(state.status!=='running')break;
     await pause(700);state=await api('startup-preparation');
   }
 }catch(e){
   const state={status:'error',editorReady:true,phase:'缓存暂时中断',percent:prepared?.percent||0,warnings:[e.message]};
   updateProgress(state);showCache(state);release(state);
 }finally{cachePromise=null;}})();
 return readyPromise;
}
async function chooseFolder(kind){try{let path;if(window.pywebview?.api?.choose_folder)path=await window.pywebview.api.choose_folder(kind);else if(window.STUDIO_CHOOSE_ASSET_FOLDER)path=await window.STUDIO_CHOOSE_ASSET_FOLDER(kind);else{q(`[data-guide-folder="${kind}"]`).focus();notice('请粘贴文件夹的完整路径。');return;}if(path){drafts[kind]=path;q(`[data-guide-folder="${kind}"]`).value=path;}}catch(e){notice(e.message);}}
async function saveFolders(){let changed=false;folderState=await api('asset-folders');for(const [kind,path] of Object.entries(drafts)){if(path===(folderState.folders[kind]?.path||''))continue;folderState=await api('asset-folders',{kind,path,settingsRevision:folderState.revision});changed=true;}drafts={};if(changed)notice('素材文件夹已保存，将在后台自动缓存。');}
async function advance(skip){if(working)return;working=true;controls();notice('');try{if(step===1){await saveCache();await saveFolders();await prepare();}if(step===2){await STUDIO_NAV.setSaveOnExit(preferences.saveOnExit);await StudentAgeRecordLabels.setVisible(preferences.showRecordIds);if(preferences.backupCleanup!==(locations.backups?.autoCleanup!==false))locations.backups=await api('backup-settings',{autoCleanup:preferences.backupCleanup});if(preferences.logCleanup!==(locations.errorLogs?.autoCleanup!==false))locations.errorLogs=await api('error-log-settings',{autoCleanup:preferences.logCleanup});}if(step===4){await api('display-settings',{onboardingComplete:true});window.STUDIO_ONBOARDING_COMPLETE=true;await reveal();return;}step++;render();}catch(e){notice(e.message);}finally{working=false;controls();}}
async function initialize(){if(initialized)return;let initializationError=null;try{await window.STUDIO_INITIALIZE();}catch(e){initializationError=e;}if(window.STUDIO_CURRENT_PROJECT?.()){await window.STUDIO_OPEN_WORKSHOP();}else{const empty=document.createElement('section');empty.id='studio-empty-home';empty.innerHTML='<img src="/icon.png" alt=""><h1>你的故事，从这里开始。</h1><p>创建第一个模组，或在工坊设置中选择已有的模组目录。</p><div><button class="primary" data-empty-create>新建模组</button><button data-game-location>工坊设置</button></div>';if(initializationError){empty.querySelector('h1').textContent='暂时无法打开模组';empty.querySelector('p').textContent=initializationError.message;const retry=document.createElement('button');retry.textContent='重试读取';retry.onclick=()=>location.reload();empty.querySelector('div').append(retry);}document.body.append(empty);empty.querySelector('[data-empty-create]').onclick=()=>window.STUDIO_NEW_PROJECT(false);window.addEventListener('studio-project-ready',()=>empty.remove(),{once:true});}initialized=true;}
async function reveal(){await initialize();window.STUDIO_BOOTSTRAPPING=false;document.documentElement.removeAttribute('data-booting');root.classList.add('guide-leaving');await pause(matchMedia('(prefers-reduced-motion: reduce)').matches?0:200);root.hidden=true;root.classList.remove('guide-leaving');window.STUDIO_NAV?.changed();window.dispatchEvent(new Event('studio-startup-complete'));}
function cacheField(){return `<label class="guide-folder cache-folder-setting"><span><strong>缓存文件夹 · 必填</strong><small>更新版本继续复用；内容随素材和编辑状态自动更新。</small></span><div><input data-cache-folder aria-label="缓存文件夹路径" placeholder="请选择专用缓存文件夹" value="${esc(cacheDraft)}" required><button type="button" data-cache-browse>选择</button></div></label><p class="guide-caption">已有缓存时请选择原来的 Cache 文件夹。此处只存可重新生成的缓存，素材与模组仍保留在原位置。</p>`;}
function bindCache(parent){const input=parent.querySelector('[data-cache-folder]');input.oninput=()=>{cacheDraft=input.value;};parent.querySelector('[data-cache-browse]').onclick=async()=>{try{let path;if(window.pywebview?.api?.choose_folder)path=await window.pywebview.api.choose_folder('cache');else if(window.STUDIO_CHOOSE_ASSET_FOLDER)path=await window.STUDIO_CHOOSE_ASSET_FOLDER('cache');else{input.focus();notice('请粘贴缓存文件夹的完整路径。');return;}if(path){cacheDraft=path;input.value=path;}}catch(e){notice(e.message);}};}
async function saveCache(){if(!cacheDraft.trim())throw Error('缓存路径必须设置，请先选择缓存文件夹。');if(cacheSettings.required||cacheDraft!==cacheSettings.path)cacheSettings=await api('cache-settings',{path:cacheDraft});if(cacheSettings.required)throw Error(cacheSettings.error||'请设置可用的缓存目录。');}
function cacheUpgrade(){root.dataset.first='false';root.innerHTML=`<section class="cache-upgrade"><img src="/icon.png" alt=""><h1>设置一次，更新继续用</h1><p>请补设缓存路径。以后更新编辑器会沿用此目录，缓存仍会随当前素材与编辑内容更新。</p>${cacheField()}<p data-onboarding-notice role="status">${esc(cacheSettings.error||'缓存路径必须设置，保存后即可进入工坊。')}</p><button class="primary" data-cache-continue>保存并进入工坊</button></section>`;bindCache(root);q('[data-cache-continue]').onclick=async()=>{const b=q('[data-cache-continue]');b.disabled=true;try{await saveCache();await prepare();await reveal();}catch(e){notice(e.message);b.disabled=false;}};}
async function boot(){try{
 await pause(380);if(first)shell();else{root.dataset.first='false';root.innerHTML='<div class="startup-brand"><img src="/icon.png" alt="拾光工坊图标"><h1>拾光工坊</h1><p>学生时代模组编辑器</p><p data-prepare-phase>正在准备创作资料…</p><progress data-prepare-progress aria-label="素材准备进度"></progress><p data-prepare-count></p><p data-onboarding-notice role="status"></p></div>';}
 [folderState,locations,preferences,cacheSettings]=await Promise.all([api('asset-folders'),api('game-locations'),api('display-settings'),api('cache-settings')]);
 cacheDraft=cacheSettings.path||'';
 preferences={...preferences,backupCleanup:locations.backups?.autoCleanup!==false,logCleanup:locations.errorLogs?.autoCleanup!==false};ready=true;controls();
 if(cacheSettings.required){if(!first)cacheUpgrade();else updateProgress({phase:'目录已就绪，请继续设置素材与缓存',done:0,total:0});return;}
 const state=await prepare();if(state.status==='error')notice('可以继续进入工坊，稍后在工坊设置检查目录。');if(!first)await reveal();
 }catch(e){ready=true;notice('准备未完成：'+e.message+'。请检查缓存与游戏目录。');controls();if(!first){const retry=document.createElement('button');retry.textContent='重试启动';retry.onclick=boot;root.append(retry);}}}
window.STUDIO_ONBOARDING={get step(){return step;},get ready(){return ready;},get active(){return !root.hidden;},get first(){return first;}};
boot();
})();
