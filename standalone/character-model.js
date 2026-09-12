/* PersonCfg geometry: CfgExtension.GetUrlParm/GetBubblePos, RoleMgr.GetRoleL2dParm. */
(()=>{'use strict';
const esc=StudentAgeCharacterUI.esc,copy=v=>structuredClone(v);
function effectiveMode(p,grade,mode,gender=1){return mode==='live'&&!p?.[grade?'l2d2':'l2d']?.[p.id===0&&gender===2?1:0]?'static':mode;}
function geometry(p,grade,mode,gender=1){
 mode=effectiveMode(p,grade,mode,gender);
 const female=p.id===0&&gender===2,index=female?1:0;
 const young=mode==='live'?grade===0:(grade===0?!!p.url?.length:!p.url2?.length);
 const key=(mode==='live'?'l2dParm':'urlParm')+(young?'':'2'),offset=female?3:0;
 const row=mode==='live'?p[key]?.[index]:p[key]?.slice(offset,offset+3);
 return {key,index,offset,scale:Number(row?.[mode==='live'?0:2]??(mode==='live'?1500:1)),x:Number(row?.[mode==='live'?1:0]??0),y:Number(row?.[mode==='live'?2:1]??0),flip:mode==='live'&&row?.[3]===1};
}
function writeGeometry(p,grade,mode,gender,value){
 mode=effectiveMode(p,grade,mode,gender);
 const g=geometry(p,grade,mode,gender),row=mode==='live'?[value.scale,value.x,value.y,value.flip?1:0]:[value.x,value.y,value.scale];
 if(!row.every(Number.isFinite)||!(value.scale>0))throw Error('大小必须大于零，位置需要是有效数字。');
 if(mode==='live'){p[g.key]=copy(p[g.key]||[]);while(p[g.key].length<=g.index)p[g.key].push([1500,0,0,0]);p[g.key][g.index]=[...row,...p[g.key][g.index].slice(4)];}
 else{const arr=copy(p[g.key]||[]);while(arr.length<g.offset+3)arr.push(arr.length%3===2?1:0);arr.splice(g.offset,3,...row);p[g.key]=arr;}
}
// Match the visible bounds in native game units; retain each image's aspect ratio.
function linkedGeometry(p,grade,gender,mode,value,metrics){
 writeGeometry(p,grade,mode,gender,value);
 if(!metrics?.size?.[1]||!metrics?.bounds?.[3]||effectiveMode(p,grade,'live',gender)!=='live')return;
 const [bx,by,bw,bh]=metrics.bounds,H=metrics.size[1];
 if(mode==='static'){
  const old=geometry(p,grade,'live',gender),scale=H*value.scale/bh;
  writeGeometry(p,grade,'live',gender,{...old,scale,x:value.x-(old.flip?-1:1)*(bx+bw/2)*scale,y:50+value.y-H*value.scale/2-by*scale});
 }else{
  const height=bh*value.scale;
  writeGeometry(p,grade,'static',gender,{scale:height/H,x:value.x+(value.flip?-1:1)*(bx+bw/2)*value.scale,y:value.y+by*value.scale+height/2-50});
 }
}
function bubbleKey(p,grade){if(grade===0){if(p.url?.length)return 'bubbleParm';if(p.url2?.length)return 'bubbleParm2';return 'bubbleParm';}if(p.url2?.length)return 'bubbleParm2';if(p.url?.length)return 'bubbleParm';return p.bubbleParm2?.length?'bubbleParm2':'bubbleParm';}
function writeBubble(p,grade,gender,height){if(!Number.isFinite(height))throw Error('气泡高度无效。');const key=bubbleKey(p,grade),idx=p.id===0&&gender===2?1:0;const arr=copy(p[key]||[]);while(arr.length<=idx)arr.push(StudentAgeScene.bubbleY(p,grade,false));arr[idx]=height;p[key]=arr;}
function referenceRows(rows,grade,mode='live'){const key=mode==='live'?(grade?'l2d2':'l2d'):(grade?'url2':'url');return Object.values(rows).flatMap(p=>{const paths=mode==='live'?(p[key]?.length?p[key]:(p[grade?'url2':'url']?.length?p[grade?'url2':'url']:p[grade?'url':'url2'])):(p[key]?.length?p[key]:p[grade?'url':'url2']);return p.id===0?[1,2].filter(g=>paths?.[g-1]).map(g=>({person:p,gender:g,label:g===1?'男主 · 白雨':'女主 · 白雨'})):paths?.[0]?[{person:p,gender:p.gender,label:p.name}]:[];});}
function create(ctx){const {S,host,person,change,options,imageURL,readonly}=ctx;
 const V={mode:'live',gender:1,reference:105,referenceGender:2,emoji:11};let epoch=0,resize=null,stages=[],dialogs=new Set(),timer=null,dead=false,drag=null;
 const pendingGeometry=new Map();
 const q=s=>host.querySelector(s),native=()=>S.data?.tables.PersonCfg.referenceRows||{};
 const atlas='/api/social-emojis?'+new URLSearchParams({token:options.token});
 const talkUi={manifest:'/api/talk-ui?'+new URLSearchParams({token:options.token}),resource:name=>'/api/talk-ui?'+new URLSearchParams({resource:name,token:options.token})};
 function writeOwn(mode,value){const stage=stages[0];if(stage&&!stage.metrics)pendingGeometry.set([person().id,S.grade,V.gender].join(':'),{mode,value:copy(value)});linkedGeometry(person(),S.grade,V.gender,mode,value,stage?.metrics);}
 function stop(){epoch++;dead=true;resize?.disconnect();resize=null;clearTimeout(timer);timer=null;drag=null;for(const s of stages){clearTimeout(s.timer);clearTimeout(s.linkTimer);if(s.request)window.STUDIO_CACHE_TASKS?.finish('model:'+JSON.stringify(s.request));s.live?.destroy();if(s.renderer)s.renderer.disposed=true;}stages=[];for(const d of dialogs){d.close();d.remove();}dialogs.clear();}
 function modal(title,html,handler){const d=document.createElement('dialog');d.className='social-dialog model-picker';d.innerHTML=`<header><h2>${title}</h2><button data-model-close>关闭</button></header>${html}`;document.body.append(d);dialogs.add(d);const close=()=>{d.close();d.remove();dialogs.delete(d);};d.onclick=e=>{const b=e.target.closest('button');if(!b)return;if(b.hasAttribute('data-model-close'))close();else handler(b,close,d);};d.oncancel=e=>{e.preventDefault();close();};d.showModal();return d;}
 function chooseReference(){const rows=referenceRows(native(),S.grade,V.mode);let filter='all';const d=modal('选择原版人物参考',`<nav class="model-reference-tabs"><button data-model-filter="all">全部</button><button data-model-filter="1">男性</button><button data-model-filter="2">女性</button></nav><input data-model-search placeholder="搜索角色"><div data-model-reference-list></div>`,(b,close)=>{if(b.dataset.modelFilter){filter=b.dataset.modelFilter;paint();}if(b.dataset.modelRef){const [id,g]=b.dataset.modelRef.split(':').map(Number);V.reference=id;V.referenceGender=g;close();render();}});
 const paint=()=>{const term=d.querySelector('input').value;d.querySelector('[data-model-reference-list]').innerHTML=rows.filter(r=>(filter==='all'||r.gender===Number(filter))&&StudentAgeSearch.matches(term,r.label)).map(r=>`<button data-model-ref="${r.person.id}:${r.gender}"><img loading="lazy" src="${esc('/api/space-head?'+new URLSearchParams({projectId:options.project.id,personId:r.person.id,gender:r.gender,token:options.token}))}" alt=""><strong>${esc(r.label)}</strong></button>`).join('')||'<p>该学段没有匹配的参考角色。</p>';};d.oninput=paint;paint();}
 function chooseEmoji(){modal('选择参考气泡的 emoji',`<div class="social-emoji-grid">${StudentAgeSocialMedia.glyphs.map((_,i)=>`<button data-model-emoji="${i}" aria-label="表情 ${i}">${StudentAgeSocialMedia.renderText('<sprite='+i+'>',atlas)}</button>`).join('')}</div>`,(b,close)=>{if(b.dataset.modelEmoji!==undefined){V.emoji=Number(b.dataset.modelEmoji);close();paintAll();}});}
 function render(){stop();dead=false;const p=person();if(!p)return;host.classList.add('character-model-mode');const form=q('#character-form');q('#character-preview').innerHTML='';
 const refs=referenceRows(native(),S.grade,V.mode);let ref=refs.find(r=>r.person.id===V.reference&&r.gender===V.referenceGender);if(!ref){ref=refs.find(r=>r.person.id===105)||refs[0];if(ref){V.reference=ref.person.id;V.referenceGender=ref.gender;}}
 form.innerHTML=`<div class="model-heading"><div><h2>模型调整</h2><p>两边使用同一比例尺。原版人物只作参考。</p></div><div class="model-switches"><div>${[0,1].map(g=>`<button data-model-grade="${g}" aria-pressed="${S.grade===g}">${g?'中学':'小学'}</button>`).join('')}</div><div>${[['static','静态'],['live','Live2D']].map(([m,l])=>`<button data-model-mode="${m}" aria-pressed="${V.mode===m}">${l}</button>`).join('')}</div>${p.id===0?`<div><button data-model-gender="1" aria-pressed="${V.gender===1}">男主</button><button data-model-gender="2" aria-pressed="${V.gender===2}">女主</button></div>`:''}</div></div><div class="model-comparison">${[{p,label:p.name,editable:true,gender:V.gender,mode:V.mode},{p:ref?.person,label:ref?.label||'没有可用的参考',editable:false,gender:V.referenceGender,mode:'live'}].map(r=>`<section class="model-card"><header><strong>${esc(r.label)}</strong>${r.editable?'<span>正在编辑</span>':'<button data-model-reference>更换参考</button>'}</header><div class="model-stage" data-model-stage="${r.editable?'own':'reference'}"><div class="model-origin"></div><div class="model-art" ${r.editable?'data-model-drag="move"':''}><img draggable="false" alt="${esc(r.label)}">${r.editable?'<button class="model-size-handle" data-model-drag="size" aria-label="拖动调整人物大小">↗</button>':''}</div><div class="scene-actor-emoji" ${r.editable?'data-model-drag="bubble" title="上下拖动调整气泡高度"':''}></div><p class="model-load-status" role="status">正在读取…</p></div></section>`).join('')}</div><div class="model-tools"><button data-model-emoji-open>选择气泡 emoji</button><button data-model-flip ${effectiveMode(p,S.grade,V.mode,V.gender)!=='live'||readonly()?'disabled':''}>左右翻转</button><span>${V.mode==='live'?'朝向写入当前学段模型参数':'静态朝向由剧情动作控制，本页保持原版方向'}</span></div><div class="model-values">${[['scale','大小'],['x','左右偏移'],['y','上下偏移'],['bubble','气泡高度']].map(([k,l])=>`<label>${l}<input data-model-value="${k}" aria-label="${l}" type="range" min="${k==='scale'?0.01:-2400}" max="${k==='scale'?5:2400}" step="${k==='scale'?0.01:1}" ${readonly()?'disabled':''}><output data-model-output="${k}"></output></label>`).join('')}</div><p class="helper">拖动人物移动，拖动右上角手柄缩放，滚轮也可缩放；拖动当前人物的气泡调整高度。气泡与 emoji 保持原版尺寸，所选 emoji 仅用于对照，不会写入剧情。Live2D 实时预览支持鼠标跟随、眨眼和原版待机、头发物理动态；鼠标停留约三秒后恢复正视。</p><p class="helper">拍照用图片是游戏拍照界面中「表情选择按钮」的小图；实际合影仍使用人物立绘或 Live2D。未填写时，原版会回退到人物头像。</p>`;
 stages=[{node:q('[data-model-stage="own"]'),p,gender:V.gender,mode:V.mode,editable:!readonly()},{node:q('[data-model-stage="reference"]'),p:ref?.person,gender:V.referenceGender,mode:V.mode,editable:false}];const stamp=epoch;for(const s of stages){loadArt(s,stamp);prepareLinked(s,stamp);}resize=new ResizeObserver(paintAll);stages.forEach(s=>resize.observe(s.node));bind();values();paintAll();}
 async function prepareLinked(s,stamp){
 const p=s.p,index=p.id===0&&s.gender===2?1:0,model=p[S.grade?'l2d2':'l2d']?.[index];if(!model)return;
 const path=(S.grade?p.url2?.length?p.url2:p.url:p.url?.length?p.url:p.url2)?.[index];if(!path)return;
 const resource=/^(Mods|Textures|StudentAgeStudio)[\\/]/i.test(path)?path:'role_full/'+path;
 const donor=referenceRows(native(),S.grade).find(r=>r.person[S.grade?'l2d2':'l2d']?.[r.person.id===0&&r.gender===2?1:0]===model);if(!donor)return;
 try{
  const request={projectId:options.project.id,role:donor.person.id,grade:S.grade,gender:donor.gender};
  const [sizes,result]=await Promise.all([options.api('/api/portrait-dimensions',{projectId:options.project.id,paths:[resource]}),StudentAgeLivePreview.prepare(request,()=>options.api('/api/live-model',request))]);
  if(stamp!==epoch)return;
  if(!result.profile?.bounds){if(['queued','rendering'].includes(result.status))s.linkTimer=setTimeout(()=>prepareLinked(s,stamp),600);return;}
  s.metrics={size:sizes[resource],bounds:result.profile.bounds};if(!s.metrics.size)return;
  // The game uses Live2D whenever present. Initialize its static counterpart to the same native bounds.
  const key=[p.id,S.grade,s.gender].join(':'),candidate=s.editable?pendingGeometry.get(key):null,current=candidate?geometry(p,S.grade,candidate.mode,s.gender):null,pending=candidate&&['x','y','scale','flip'].every(k=>current[k]===candidate.value[k])?candidate:null;const before=JSON.stringify(p);const next=copy(p);linkedGeometry(next,S.grade,s.gender,pending?.mode||'live',pending?.value||geometry(p,S.grade,'live',s.gender),s.metrics);if(s.editable)pendingGeometry.delete(key);
  if(JSON.stringify(next)!==before){if(s.editable)change(()=>Object.assign(p,next),'model-align:'+p.id+':'+S.grade);else s.p=next;}
  paintAll();values();
 }catch(e){s.node.querySelector('[role=status]').textContent='尺寸联动读取失败：'+e.message;}
 }
 async function loadArt(s,stamp){if(!s.p)return;const p=s.p,img=s.node.querySelector('.model-art img'),status=s.node.querySelector('[role=status]');s.ready=false;
 s.mode=effectiveMode(p,S.grade,s.mode,s.gender);
 try{if(s.mode==='live'){const model=p[S.grade?'l2d2':'l2d']?.[p.id===0&&s.gender===2?1:0];if(!model)throw Error('这个人物在此学段没有 Live2D 模型。可切换静态立绘。');const donor=referenceRows(native(),S.grade).find(r=>r.person[S.grade?'l2d2':'l2d']?.[r.person.id===0&&r.gender===2?1:0]===model);if(!donor)throw Error('当前模型尚不能通过原版模型读取入口预览。');
 const poll=async()=>{if(stamp!==epoch)return;const request={projectId:options.project.id,role:donor.person.id,grade:S.grade,gender:donor.gender};s.request=request;const result=await StudentAgeLivePreview.prepare(request,()=>options.api('/api/live-model',request));if(stamp!==epoch)return;if(result.status==='ready'){s.bounds=result.profile?.bounds;if(!s.bounds)throw Error('模型几何数据尚未就绪。');s.ready=true;paint(s);s.live=await StudentAgeLivePreview.mount(s.node.querySelector('.model-art'),s.node,result,{token:options.token,cloth:S.cloth,face:S.previewFace,geometry:()=>s.draft||geometry(s.p,S.grade,s.mode,s.gender),cancelled:()=>stamp!==epoch});if(stamp!==epoch){s.live?.destroy();return;}status.textContent='';s.live?.resize();}else if(['queued','rendering'].includes(result.status)){status.textContent=result.message;s.timer=setTimeout(()=>poll().catch(fail),400);}else throw Error(result.message||'模型读取失败。');};await poll();
 }else{const young=S.grade===0?!!p.url?.length:!p.url2?.length,index=p.id===0&&s.gender===2?1:0;const f=ctx.all('ModFaceCfg')[p.id*1000+S.cloth*100+S.previewFace]||ctx.all('ModFaceCfg')[p.id*1000+S.cloth*100];const path=f?.[S.grade?'icon':'icon_xx']||(young?p.url:p.url2)?.[index];if(!path)throw Error('此学段没有静态立绘，请先在人物资料中选择图片。');s.path=/^(Mods|Textures|StudentAgeStudio)[\\/]/i.test(path)?path:'role_full/'+path;
 if(!StudentAgeScene.portraitSizes.has(s.path)||/^(Mods|Textures|StudentAgeStudio)[\\/]/i.test(s.path)){const sizes=await options.api('/api/portrait-dimensions',{projectId:options.project.id,paths:[s.path]});if(stamp!==epoch)return;for(const [key,size]of Object.entries(sizes))StudentAgeScene.portraitSizes.set(key,size);}
 img.onload=()=>{if(stamp!==epoch)return;s.size=StudentAgeScene.staticPortraitSize(img,s.path);s.ready=true;status.textContent='';paint(s);};img.onerror=()=>fail(Error('静态图片读取失败，请点击重试。'));img.src=imageURL(s.path);}
 }catch(e){fail(e);}function fail(e){if(stamp!==epoch)return;status.textContent=e.message;status.onclick=()=>loadArt(s,stamp);}}
 function paint(s){if(dead||!s.p||!s.node.isConnected)return;const node=s.node,H=node.clientHeight,W=node.clientWidth,u=H/2400,g=s.draft||geometry(s.p,S.grade,s.mode,s.gender),art=node.querySelector('.model-art');let box;
 if(s.ready){if(s.mode==='live'){const [x,y,w,h]=s.bounds;box={x:g.x+(g.flip?-1:1)*(x+w/2)*g.scale,y:g.y+y*g.scale,w:w*g.scale,h:h*g.scale};}else{box={x:g.x,y:50+g.y-s.size[1]*g.scale/2,w:s.size[0]*g.scale,h:s.size[1]*g.scale};}Object.assign(art.style,{left:(W/2+(box.x-box.w/2)*u)+'px',top:((1400-box.y-box.h)*u)+'px',width:box.w*u+'px',height:box.h*u+'px',visibility:'visible'});art.querySelector('img').style.transform=`scaleX(${g.flip?-1:1})`;s.live?.resize();}
 const bubblePerson=s.bubbleDraft===undefined?s.p:copy(s.p);if(s.bubbleDraft!==undefined)writeBubble(bubblePerson,S.grade,s.gender,s.bubbleDraft);
 s.renderer??={options:{talkUi},artBox:()=>({x:0,bottom:-1000,width:W/u,height:2400}),drawVersion:0,drawOptions:{animate:false},state:true,refreshPortraits:paintAll};s.renderer.artBox=()=>({x:0,bottom:-1000,width:W/u,height:2400});s.renderer.doc={persons:{[s.p.id]:bubblePerson},protagonistGender:s.gender};
 // Reuse the production native bubble layout and TMP sprite metrics.
 const role={id:s.p.id,grade:S.grade,emoji:V.emoji};if(s.p.id===0)s.renderer.doc.playerGender=s.gender;
 StudentAgeScene.Renderer.prototype.positionEmoji.call(s.renderer,node,role);
 }
 function paintAll(){if(dead)return;for(const s of stages)paint(s);}
 function values(){const p=person(),g=geometry(p,S.grade,V.mode,V.gender);for(const [k,v]of Object.entries({...g,bubble:StudentAgeScene.bubbleY(p,S.grade,p.id===0&&V.gender===2)})){const el=q('[data-model-value="'+k+'"]');if(el){if(k==='scale'){const live=effectiveMode(p,S.grade,V.mode,V.gender)==='live';el.min=live?1:.01;el.max=live?5000:5;el.step=live?1:.01;}el.min=Math.min(Number(el.min),v);el.max=Math.max(Number(el.max),v);el.value=v;const output=q('[data-model-output="'+k+'"]');if(output)output.textContent=String(Math.round(v*10000)/10000);}}}
 function bind(){const root=q('#character-form');root.onclick=e=>{const b=e.target.closest('button');if(!b||b.disabled)return;if(b.dataset.modelGrade!==undefined){S.grade=Number(b.dataset.modelGrade);render();}else if(b.dataset.modelMode){V.mode=b.dataset.modelMode;render();}else if(b.dataset.modelGender){V.gender=Number(b.dataset.modelGender);render();}else if(b.hasAttribute('data-model-reference'))chooseReference();else if(b.hasAttribute('data-model-emoji-open'))chooseEmoji();else if(b.hasAttribute('data-model-flip')){const g=geometry(person(),S.grade,V.mode,V.gender);change(()=>writeOwn(V.mode,{...g,flip:!g.flip}));paintAll();values();}};
 root.oninput=e=>{const key=e.target.dataset.modelValue;if(!key||readonly())return;const v=Number(e.target.value);if(!e.target.value.trim()||!Number.isFinite(v)||key==='scale'&&v<=0){e.target.setAttribute('aria-invalid','true');return;}e.target.removeAttribute('aria-invalid');change(()=>key==='bubble'?writeBubble(person(),S.grade,V.gender,v):writeOwn(V.mode,{...geometry(person(),S.grade,V.mode,V.gender),[key]:v}),'model:'+S.selected+':'+S.grade+':'+V.mode+':'+key);paintAll();values();};
 const own=stages[0],node=own.node;node.onpointerdown=e=>{const target=e.target.closest('[data-model-drag]');if(!target||!own.editable||!own.ready||e.button!==0)return;e.preventDefault();const g=geometry(person(),S.grade,own.mode,V.gender);drag={kind:target.dataset.modelDrag,x:e.clientX,y:e.clientY,g,height:StudentAgeScene.bubbleY(person(),S.grade,person().id===0&&V.gender===2),u:node.clientHeight/2400};node.setPointerCapture(e.pointerId);};
 node.onpointermove=e=>{if(!drag)return;const dx=(e.clientX-drag.x)/drag.u,dy=-(e.clientY-drag.y)/drag.u;if(drag.kind==='bubble')own.bubbleDraft=drag.height+dy;else own.draft=drag.kind==='size'?{...drag.g,scale:Math.max(.001,drag.g.scale*Math.exp((e.clientX-drag.x-e.clientY+drag.y)/220))}:{...drag.g,x:drag.g.x+dx,y:drag.g.y+dy};paint(own);};
 node.onpointerup=()=>{if(!drag)return;drag=null;if(own.draft){const value=own.draft;change(()=>writeOwn(V.mode,value));}if(own.bubbleDraft!==undefined){const value=own.bubbleDraft;change(()=>writeBubble(person(),S.grade,V.gender,value));}delete own.draft;delete own.bubbleDraft;paintAll();values();};node.onpointercancel=()=>{drag=null;delete own.draft;delete own.bubbleDraft;paintAll();};
 node.onwheel=e=>{if(!own.editable||!own.ready||!e.target.closest('.model-art'))return;e.preventDefault();const g=geometry(person(),S.grade,V.mode,V.gender);change(()=>writeOwn(V.mode,{...g,scale:Math.max(.001,g.scale*Math.exp(-e.deltaY*.001))}),'model-wheel:'+S.selected+':'+S.grade+':'+V.mode);paintAll();values();};}
 return {render,stop,state:V};
}
window.StudentAgeCharacterModel={effectiveMode,create,geometry,writeGeometry,linkedGeometry,bubbleKey,writeBubble,referenceRows};
})();
