(() => {
'use strict';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kinds=[['background','背景'],['cg','CG 插画'],['portrait','人物立绘与表情'],['audio','声音']];
const dialog=document.createElement('dialog');dialog.id='reuse-assets';dialog.setAttribute('aria-labelledby','reuse-assets-title');document.body.append(dialog);
const R={context:null,projects:[],source:null,kind:'background',assets:[],query:'',loading:false,busy:false,apply:true,target:'new',sequence:0,imported:new Set()};
const token=()=>window.STUDIO_TOKEN;
async function api(path,data){const response=await fetch('/api/'+path,{method:data===undefined?'GET':'POST',headers:{'X-Studio-Token':token(),'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const result=await response.json();if(!response.ok||result.error)throw Error(result.error||'素材读取失败');return result;}
function context(){return window.STUDIO_REUSE_CONTEXT?.();}
function writable(project){return project&&String(project.id).startsWith('local:')&&!project.readOnly&&!project.readonly;}
function notice(text,error=false){const node=dialog.querySelector('[data-reuse-notice]');if(node){node.textContent=text;node.classList.toggle('error',error);}}
function stopAudio(){dialog.querySelectorAll('audio').forEach(audio=>audio.pause());}
function close(){if(R.busy)return;R.sequence++;stopAudio();dialog.close();}
function setBusy(value){R.busy=value;dialog.querySelectorAll('button,input,select').forEach(node=>node.disabled=value);if(!value){renderCards();const apply=dialog.querySelector('[data-reuse-apply]');if(apply)apply.disabled=!R.context?.selected;}}
function sourceLabel(project){return project.readOnly||project.source==='workshop'?'订阅模组':'本地模组';}
function assetURL(asset){return '/api/assets?projectId='+encodeURIComponent(R.source)+'&path='+encodeURIComponent(asset.assetPath||'')+'&token='+encodeURIComponent(token());}
function assetKey(asset){return [R.source,R.kind,asset.assetId].join('|');}
function details(asset){const parts=[];if(asset.kind==='portrait'){if(asset.sourceGrade)parts.push(asset.sourceGrade===1?'小学':'中学');if(asset.sourceCloth!==undefined&&Number(asset.sourceCloth)>0)parts.push('服装 '+(Number(asset.sourceCloth)+1));}if(asset.kind==='audio'&&asset.type)parts.push(({1:'背景音乐',2:'音效',3:'配音'})[asset.type]||'声音');return parts.join(' · ');}
function renderCards(){const list=dialog.querySelector('[data-reuse-assets]');if(!list)return;const query=R.query.trim().toLowerCase(),assets=R.assets.filter(asset=>(asset.name||'').toLowerCase().includes(query));
 list.innerHTML=R.loading?'<p class="reuse-empty">正在读取这个模组的素材…</p>':!assets.length?`<p class="reuse-empty">${R.projects.length===0?'没有其他已安装的模组。':query?'没有匹配的素材。':'这个模组没有提供这类素材。'}</p>`:assets.map(asset=>{const index=R.assets.indexOf(asset),used=R.imported.has(assetKey(asset)),available=asset.available!==false&&!!asset.assetPath,disabled=R.busy||!available||used,caption=`<strong>${esc(asset.name||'未命名素材')}</strong>${details(asset)?`<small>${esc(details(asset))}</small>`:''}`,label=used?'已加入当前模组':!available?'素材文件不可用':'使用此素材';return asset.kind==='audio'?`<article class="reuse-card reuse-audio">${caption}<audio controls preload="none" src="${esc(assetURL(asset))}" aria-label="试听 ${esc(asset.name||'声音')}"></audio><button data-reuse-import="${index}" ${disabled?'disabled':''}>${label}</button></article>`:`<button class="reuse-card" data-reuse-import="${index}" ${disabled?'disabled':''} title="${esc(label+'：'+(asset.name||''))}"><span class="reuse-image ${asset.kind==='portrait'?'reuse-portrait':''}"><img src="${esc(assetURL(asset))}" alt="${esc(asset.name||'素材预览')}" loading="lazy"><span class="reuse-image-error" hidden>预览不可用</span></span>${caption}<span class="reuse-use">${label}</span></button>`;}).join('');
 list.querySelectorAll('img').forEach(image=>image.addEventListener('error',()=>{image.hidden=true;image.nextElementSibling.hidden=false},{once:true}));
 list.querySelectorAll('[data-reuse-import]').forEach(button=>button.onclick=()=>useAsset(R.assets[Number(button.dataset.reuseImport)]));
 list.querySelectorAll('audio').forEach(audio=>audio.addEventListener('play',()=>{list.querySelectorAll('audio').forEach(other=>{if(other!==audio)other.pause()})}));
 const count=dialog.querySelector('[data-reuse-count]');if(count)count.textContent=R.loading?'':assets.length+' 项';
}
function render(){const currentRole=Number(R.context?.previewRole),hasRole=R.context?.previewRole!=null&&Number.isFinite(currentRole)&&currentRole>=0;
 dialog.innerHTML=`<header class="reuse-heading"><div><h2 id="reuse-assets-title">使用其他模组的素材</h2><p>加入：${esc(R.context?.project?.name||'当前本地模组')}</p></div><button data-reuse-close>关闭</button></header><div class="reuse-settings"><label>素材来源<select data-reuse-source>${R.projects.map(project=>`<option value="${esc(project.id)}" ${project.id===R.source?'selected':''}>${esc(project.name)} · ${sourceLabel(project)}</option>`).join('')}</select></label><label class="reuse-apply"><input type="checkbox" data-reuse-apply ${R.apply?'checked':''} ${R.context?.selected?'':'disabled'}>应用到当前对话</label></div><nav class="reuse-tabs" aria-label="素材类型">${kinds.map(([kind,label])=>`<button data-reuse-kind="${kind}" class="${kind===R.kind?'active':''}" aria-pressed="${kind===R.kind}">${label}</button>`).join('')}</nav><div class="reuse-toolbar"><input type="search" data-reuse-search placeholder="搜索素材名称" aria-label="搜索素材" value="${esc(R.query)}"><span data-reuse-count></span></div>${R.kind==='portrait'?`<label class="reuse-portrait-target">加入方式<select data-reuse-target><option value="new" ${R.target==='new'?'selected':''}>新增人物</option>${hasRole?`<option value="current" ${R.target==='current'?'selected':''}>当前人物的当前表情</option>`:''}</select></label><p class="reuse-help">${R.target==='current'?'所选图片会替换当前人物正在预览的表情。':'将这张图片加入本地模组，并新建一个可登场的人物。'}</p>`:''}<p class="reuse-notice" data-reuse-notice role="status" aria-live="polite">点击素材即可加入。文件会复制到当前模组，之后不依赖原模组。</p><div class="reuse-grid" data-reuse-assets></div>`;
 dialog.querySelector('[data-reuse-close]').onclick=close;
 dialog.querySelector('[data-reuse-source]').onchange=event=>{R.source=event.target.value;R.query='';loadAssets()};
 dialog.querySelectorAll('[data-reuse-kind]').forEach(button=>button.onclick=()=>{if(R.kind===button.dataset.reuseKind)return;stopAudio();R.kind=button.dataset.reuseKind;R.query='';loadAssets()});
 dialog.querySelector('[data-reuse-search]').oninput=event=>{R.query=event.target.value;stopAudio();renderCards()};
 dialog.querySelector('[data-reuse-apply]').onchange=event=>R.apply=event.target.checked;
 dialog.querySelector('[data-reuse-target]')?.addEventListener('change',event=>{R.target=event.target.value;render()});
 renderCards();
}
async function loadAssets(){const sequence=++R.sequence,source=R.source,kind=R.kind;stopAudio();R.loading=!!source;R.assets=[];render();if(!source)return;
 try{const data=await api('reuse-assets?projectId='+encodeURIComponent(source)+'&kind='+encodeURIComponent(kind));if(sequence!==R.sequence)return;R.assets=Array.isArray(data.assets)?data.assets:[];R.loading=false;renderCards();if(data.warnings?.length)notice(data.warnings.join('；'),true);}catch(error){if(sequence!==R.sequence)return;R.loading=false;renderCards();notice(error.message,true);}
}
async function useAsset(asset){if(R.busy||!asset||asset.available===false||R.imported.has(assetKey(asset)))return;const source=R.source,key=assetKey(asset),target=R.context?.project?.id,apply=R.apply,portraitTarget=R.target;let committed=false;setBusy(true);stopAudio();notice('正在复制素材到本地模组…');
 try{const prepared=await window.STUDIO_PREPARE_ASSET_REUSE?.();if(!prepared)return;if(prepared.project?.id!==target||!writable(prepared.project))throw Error('当前模组已变化，请关闭后重新选择素材。');const payload={projectId:target,revision:prepared.revision,sourceProjectId:source,kind:asset.kind,assetId:asset.assetId};
  if(asset.kind==='portrait'){if(portraitTarget==='current'){const person=Number(prepared.previewRole);if(prepared.previewRole==null||!Number.isFinite(person)||person<0)throw Error('请先选择要设置表情的人物。');payload.personId=person;payload.grade=Number(prepared.grade)+1;payload.cloth=Number(prepared.cloth)||0;payload.faceId=Number(prepared.face)||0;}else{payload.grade=Number(asset.sourceGrade)||2;payload.cloth=0;payload.faceId=0;}}
  const result=await api('reuse-asset',payload);committed=true;R.imported.add(key);const applied={...result,kind:asset.kind,projectId:target,grade:payload.grade,cloth:payload.cloth,faceId:payload.faceId,name:result.name||asset.name};await window.STUDIO_APPLY_REUSED_ASSET?.(applied,apply);R.context=context()||prepared;notice('已加入当前模组：'+(asset.name||'素材'));if(apply){setBusy(false);close();return;}
 }catch(error){notice((committed?'素材已复制，但应用到对话失败：':'')+error.message,true);}finally{setBusy(false);}
}
async function open(){if(R.busy)return;const current=context();R.context=current;if(!writable(current?.project)){dialog.innerHTML='<header class="reuse-heading"><h2 id="reuse-assets-title">选择本地模组</h2><button data-reuse-close>关闭</button></header><p class="reuse-notice">请先打开本地模组，或将订阅模组复制为本地模组，再加入素材。</p>';dialog.querySelector('[data-reuse-close]').onclick=close;if(!dialog.open)dialog.showModal();return;}
 R.apply=!!current.selected;R.target='new';R.imported.clear();R.projects=[];R.assets=[];R.loading=true;render();if(!dialog.open)dialog.showModal();const sequence=++R.sequence;
 try{const result=await api('projects');if(sequence!==R.sequence)return;R.projects=(Array.isArray(result)?result:result.projects||[]).filter(project=>project&&/^(local|workshop):/.test(String(project.id))&&project.id!==current.project.id);if(!R.projects.some(project=>project.id===R.source))R.source=(R.projects.find(project=>project.source==='workshop')||R.projects[0])?.id||null;await loadAssets();}catch(error){if(sequence!==R.sequence)return;R.loading=false;render();notice(error.message,true);}
}
 dialog.addEventListener('cancel',event=>{event.preventDefault();close()});dialog.addEventListener('close',stopAudio);
 window.STUDIO_REUSE_ASSETS={open};
})();
