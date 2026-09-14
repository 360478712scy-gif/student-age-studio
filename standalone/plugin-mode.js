(()=>{'use strict';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),clone=structuredClone;
async function prerequisites(data,api,project){
 const d=document.createElement('dialog');d.className='plugin-prerequisites';document.body.append(d);
 return new Promise(resolve=>{let pending=false;const close=value=>{d.close();d.remove();resolve(value);};
 d.innerHTML=`<header><h2>选择前置插件</h2><button data-cancel aria-label="关闭">×</button></header><p>选择此模组需要的插件。自建关卡和参数覆盖需要配套支持这些功能的新版 UP，玩家也需安装；编辑器不会替游戏安装插件。</p>${data.plugins.map(p=>`<label><input type="checkbox" value="${esc(p.id)}" ${data.enabled.includes(p.id)?'checked':''} ${data.readOnly?'disabled':''}><span><strong>${esc(p.name)}</strong><small>${esc(p.description)}</small></span></label>`).join('')}<p role="status"></p><footer><button data-cancel>取消</button><button data-enter class="primary">进入插件编辑</button></footer>`;
 d.onchange=e=>{if(e.target.checked){const p=data.plugins.find(p=>p.id===e.target.value);for(const id of p?.requires||[])d.querySelector(`input[value="${id}"]`).checked=true;}else for(const p of data.plugins)if(p.requires?.includes(e.target.value))d.querySelector(`input[value="${p.id}"]`).checked=false;};
 d.onclick=async e=>{if(pending)return;if(e.target.closest('[data-cancel]'))return close(null);const button=e.target.closest('[data-enter]');if(!button)return;pending=true;d.querySelectorAll('button,input').forEach(n=>n.disabled=true);try{const enabled=[...d.querySelectorAll('input:checked')].map(n=>n.value);if(!enabled.length)throw Error('请选择至少一个前置插件。');const result=data.readOnly||JSON.stringify(enabled)===JSON.stringify(data.enabled)?data:await api('/api/plugins',{projectId:project.id,revision:data.revision,enabled,groups:data.groups});close(result);}catch(error){d.querySelector('[role=status]').textContent=error.message;pending=false;d.querySelectorAll('button').forEach(n=>n.disabled=false);d.querySelectorAll('input').forEach(n=>n.disabled=data.readOnly);}};
 d.oncancel=e=>{e.preventDefault();if(!pending)close(null);};d.showModal();});
}
function create(root,options){
 const {api,project}=options;let state=null,saved='',selected=Number(options.selected)||9101,busy=false,undo=[],redo=[],dead=false,search='';
 const snapshot=()=>JSON.stringify({enabled:state?.enabled||[],groups:state?.groups||[],builtin:state?.builtin||[]});
 const dirty=()=>state!==null&&snapshot()!==saved;
 const notify=()=>options.onState?.({revision:state?.revision,readOnly:!!state?.readOnly,busy,canUndo:!!undo.length,canRedo:!!redo.length});
 const group=()=>state.groups.find(g=>g.id===selected)||state.builtin.find(g=>g.id===selected);
 const custom=()=>!!state.groups.find(g=>g.id===selected);
 function change(fn){if(state.readOnly||busy)return;undo.push(snapshot());if(undo.length>40)undo.shift();redo=[];fn();notify();}
 function render(){if(dead||!state)return;const campus=state.enabled.includes('studio.studentage.campusuno'),games=campus?[...state.builtin,...state.groups]:[],g=group(),template=g?.template,levels=g?.levels||[],readonly=busy||state.readOnly;
 const rows=(label,list,attr)=>`<h3>${label}</h3>${list.filter(r=>StudentAgeSearch.matches(search,r.name,r.id)).map(r=>`<button data-${attr}="${r.id}" class="${selected===r.id?'active':''}">[${r.id}] ${esc(r.name)}</button>`).join('')}`;
 root.innerHTML=`<section class="plugin-workbench"><header><h2>小游戏</h2></header><div class="plugin-columns"><aside class="wk-rows"><input data-plugin-search type="search" value="${esc(search)}" placeholder="搜索小游戏">${rows('游戏原有',options.nativeGames||[],'native-game')}${rows('插件',games,'group')}</aside><main>${g?`<header><h3>[${g.id}] ${esc(g.name)}</h3><button data-plugin="create" ${readonly?'disabled':''}>创建模组关卡</button>${custom()?`<button data-plugin="remove" class="danger-button" ${readonly?'disabled':''}>移除关卡组</button>`:''}</header>${custom()?`<label>关卡组名称<input data-name value="${esc(g.name)}" ${readonly?'disabled':''}></label>`:''}<section><header><h3>社交关卡</h3>${custom()?`<div><button data-plugin="add-level" ${readonly||levels.length>=Math.min(5,Object.values(state.catalog.stages).filter(r=>Math.floor(r.id/100)===template).length)?'disabled':''}>添加下一关</button><button data-plugin="remove-level" ${readonly||levels.length<=1?'disabled':''}>移除末关</button></div>`:''}</header><div class="plugin-stage-grid">${levels.map((row,i)=>`<article><h4>第 ${i+1} 关 <small>[${row.id}]</small></h4>${[['needRelation','所需关系等级'],['cost','精力消耗']].map(([k,label])=>`<label>${label}<input type="number" min="0" step="${k==='cost'?'0.1':'1'}" data-level="${i}" data-key="${k}" value="${row[k]??0}" ${readonly?'disabled':''}></label>`).join('')}${[['startTalk','开始对话'],['winTalk','获胜对话'],['loseTalk','失败对话']].map(([k,label])=>`<label>${label}<select data-level="${i}" data-key="${k}" ${readonly?'disabled':''}><option value="0">不绑定</option>${Object.values(state.talks||{}).map(t=>`<option value="${t.id}" ${row[k]===t.id?'selected':''}>[${t.id}] ${esc(String(t.content||'空白对话').slice(0,35))}</option>`).join('')}${row[k]&&!state.talks?.[row[k]]?`<option selected value="${row[k]}">[${row[k]}] 已绑定对话</option>`:''}</select></label>`).join('')}</article>`).join('')}</div></section><h3>玩法参数</h3><div class="plugin-tuning">${state.catalog.settings.filter(s=>s.section===state.sections[template]).map(s=>{const key=s.section+'.'+s.key;return `<label><span>${esc(s.desc)}</span><input type="number" data-tuning="${esc(key)}" min="${s.min}" max="${s.max}" step="${s.integer?'1':'any'}" value="${g.tuning?.[key]??''}" placeholder="${s.default}" title="留空沿用插件设置，默认 ${s.default}" ${readonly?'disabled':''}></label>`;}).join('')}</div>`:'<p>选择小游戏。</p>'}</main></div></section>`;notify();}
 async function load(){state=await api('/api/plugins?projectId='+encodeURIComponent(project.id));state.talks=(await api('/api/table?projectId='+encodeURIComponent(project.id)+'&name=TalkCfg')).rows;saved=snapshot();undo=[];redo=[];render();}
 async function save(){if(busy)throw Error('正在保存，请稍候。');if(!dirty())return;busy=true;root.querySelectorAll('button,input,select').forEach(n=>n.disabled=true);notify();try{
   let baseline=JSON.parse(saved);
   for(const item of state.builtin){if(JSON.stringify(item)===JSON.stringify(baseline.builtin.find(g=>g.id===item.id)))continue;
     const result=await api('/api/plugins',{projectId:project.id,revision:state.revision,builtin:item});state.revision=result.revision;baseline.builtin=result.builtin;saved=JSON.stringify(baseline);
   }
   if(JSON.stringify(state.groups)!==JSON.stringify(baseline.groups)){
     const result=await api('/api/plugins',{projectId:project.id,revision:state.revision,enabled:state.enabled,groups:state.groups});state={...result,talks:state.talks};
   }
   saved=snapshot();undo=[];redo=[];await options.onSaved?.();
 }finally{busy=false;render();notify();}}
 root.oninput=e=>{if(e.target.matches('[data-plugin-search]')){search=e.target.value;const at=e.target.selectionStart;render();const n=root.querySelector('[data-plugin-search]');n.focus();n.setSelectionRange?.(at,at);}};
 root.onchange=e=>{const n=e.target;if(n.matches('[data-name]'))change(()=>group().name=n.value);if(n.dataset.level!==undefined)change(()=>group().levels[Number(n.dataset.level)][n.dataset.key]=Number(n.value));if(n.dataset.tuning)change(()=>{if(n.value==='')delete group().tuning[n.dataset.tuning];else group().tuning[n.dataset.tuning]=Number(n.value);});};
 root.onclick=async e=>{const b=e.target.closest('button');if(!b||b.disabled||busy)return;try{
 if(b.dataset.nativeGame)return options.onNative?.(b.dataset.nativeGame);
 if(b.dataset.group){selected=Number(b.dataset.group);render();return;}
 switch(b.dataset.plugin){case 'create':{const ids=new Set([...state.builtin,...state.groups,...(options.nativeGames||[])].map(g=>g.id));let id;do{id=100000+crypto.getRandomValues(new Uint32Array(1))[0]%900000;}while(ids.has(id));const template=group().template;
 change(()=>state.groups.push({id,template,name:state.catalog.games[template].name+' · 自建关卡',levels:[{...clone(state.catalog.stages[template*100+1]),id:id*100+1}],tuning:{}}));selected=id;render();break;}
 case 'add-level':change(()=>{const g=group(),i=g.levels.length+1;g.levels.push({...clone(state.catalog.stages[g.template*100+i]),id:g.id*100+i});});render();break;
 case 'remove-level':change(()=>group().levels.pop());render();break;
 case 'remove':change(()=>state.groups=state.groups.filter(g=>g.id!==selected));selected=9101;render();break;}
 }catch(err){options.status(err.message,true);}};
 const history=(from,to)=>{if(busy||!from.length)return;to.push(snapshot());Object.assign(state,JSON.parse(from.pop()));render();};
 return {load,save,dirty,snapshot,discard(){if(busy||!state)return;Object.assign(state,JSON.parse(saved));undo=[];redo=[];render();},undo(){history(undo,redo);},redo(){history(redo,undo);},focusSearch(){root.querySelector('[data-plugin-search]')?.focus();},destroy(){dead=true;root.onclick=null;root.onchange=null;root.oninput=null;},pause(){},navigation:{capture:()=>({selected}),restore(v){selected=Number(v.selected);render();}}};
}
window.StudentAgePluginMode={create,prerequisites};
})();
