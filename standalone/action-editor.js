'use strict';
(() => {
const h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const actions={1001:'滑动登场',1002:'渐显登场',2001:'滑动退场',2002:'渐隐退场',3000:'切换表情',3001:'跳跃',3002:'摇晃',3004:'水平位移',3008:'竖直位移',3005:'有动画翻转',3007:'无动画翻转',3006:'更换服装',3009:'气泡表情'};
const presets={};
const names={...actions,1003:'从下方登场',3003:'强调放大',3004:'拖动位移（水平）',3007:'无动画翻转',3008:'拖动位移（垂直）',3009:'气泡表情',3012:'剪影',3013:'取消剪影',3014:'更换发型'};
// Positions are native command argument indexes, excluding role and action IDs.
const delays={1001:2,1002:2,1003:2,2001:1,2002:0,3001:1,3002:1,3003:1,3004:1,3005:0,3007:0,3008:1,3009:1};
const glyphs=()=>window.StudentAgeSocialMedia?.glyphs||[];
let active=null;
function open(options){
 active?.close();const initial=options.context();if(!initial)return;
 const dialog=document.createElement('dialog');dialog.className='action-editor';dialog.id='action-editor';
 dialog.innerHTML=`<header><h2>${h(initial.name)} · 人物动作</h2><button data-action-close aria-label="关闭动作设置">关闭</button></header><div class="action-layout"><nav aria-label="可添加动作"></nav><main><div id="action-preview" aria-label="动作预览"></div><div class="action-preview-bar"><button data-action-play>播放</button><button class="primary" data-action-add>添加</button></div><p class="action-status" role="status" aria-live="polite"></p><div class="action-settings"></div></main><aside class="action-added"><header><h3>本句已添加动作 <span data-action-count></span></h3><button class="primary" data-actions-play>播放全部</button></header><p class="helper">延迟从本句开始时计算，单位为秒。</p><div class="action-added-list"></div><p class="helper action-effects-note">播放全部会合并人物动作与本句声音。数值、奖励等游戏效果不在这里执行。</p></aside></div>`;
 document.body.append(dialog);dialog.showModal();
 const token=encodeURIComponent(new URL(options.assetUrl(''),location.href).searchParams.get('token')||'');
 const talkUi=options.talkUi||{manifest:'/api/talk-ui?token='+token,resource:name=>'/api/talk-ui?resource='+encodeURIComponent(name)+'&token='+token};
 const q=s=>dialog.querySelector(s),stage=q('#action-preview'),renderer=new StudentAgeScene.Renderer(stage,{assetUrl:options.assetUrl,talkUi,portraitModelPending:options.portraitModelPending}),audio=options.createAudio?.();
 let code=3001,preset=null,selected=null,draft=[],timer=null,frame=null,closed=false,playing=false;
 const atlas=(()=>{try{return '/api/social-emojis?token='+encodeURIComponent(new URL(options.assetUrl(''),location.href).searchParams.get('token')||'');}catch{return '';}})();
 const context=()=>options.context(),existing=()=>selected===null?null:context()?.row.roles?.[selected],role=()=>Number(existing()?.[0]??initial.role),args=()=>existing()?.slice(2)||draft;
 const status=text=>q('[role=status]').textContent=text,name=id=>context()?.doc.persons?.[id]?.name||(Number(id)===0?'白雨':'人物 '+id),actionName=c=>names[c]||'扩展动作';
 function defaults(value){const c=context(),actor=c.after.roles[initial.role]||c.before.roles[initial.role]||{};return ({1001:[1,actor.axis||3,0],1002:[1,actor.axis||3,0],2001:[actor.x<0?1:2,0],2002:[0],3000:[actor.face||0],3001:[1,0,1],3002:[.4,0],3005:[0],3007:[0],3006:[actor.cloth||0],3004:[0,0],3008:[0,0,0],3009:[0,0]})[value]?.slice()||[];}
 draft=defaults(code);
 function stop(){clearTimeout(timer);clearTimeout(frame);timer=frame=null;playing=false;audio?.stop();stage.getAnimations?.({subtree:true}).forEach(a=>a.cancel());q('[data-action-play]').textContent='播放';q('[data-actions-play]').textContent='播放全部';}
 function draw(){const c=context();if(c)renderer.draw(c.doc,c.after,{edit:false});}
 function select(value){stop();selected=null;preset=presets[value]?value:null;code=preset?presets[value].code:Number(value);draft=preset?presets[value].args.slice():defaults(code);render();draw();}
 function choose(index){if(!context()?.row.roles?.[index])return;stop();selected=index;preset=null;code=Number(existing()[1]);render();draw();}
 function range(index,label,min,max,step,unit='秒') {const value=args()[index]??0;return `<label class="action-param"><span>${h(label)}<output>${h(value)}${unit}</output></span><input type="range" data-action-arg="${index}" min="${min}" max="${Math.max(max,Number(value)||0)}" step="${step}" value="${h(value)}" data-unit="${h(unit)}"></label>`;}
 function renderList(){const c=context();if(!c)return;q('[data-action-count]').textContent=c.row.roles?.length||0;q('.action-added-list').innerHTML=(c.row.roles||[]).map((row,index)=>{const kind=Number(row[1]),delay=delays[kind],value=Number(row[2+delay])||0,title=kind===3009?'气泡表情 '+(Number(row[2])||0):actionName(kind);return `<article class="action-added-row ${index===selected?'active':''}" data-added-row="${index}"><div class="action-added-title"><button data-action-existing="${index}" aria-pressed="${index===selected}"><strong>${h(title)}</strong><span>${h(name(row[0]))}</span></button><button class="danger-text" data-action-delete="${index}" aria-label="删除${h(name(row[0])+'的'+actionName(kind))}">×</button></div>${delay!==undefined?`<label class="action-delay"><span>延迟</span><input type="number" min="0" max="3600" step="0.1" value="${value}" data-added-delay="${index}" aria-label="${h(name(row[0])+' '+actionName(kind))}延迟"><span>秒</span></label>`:`<span class="action-immediate">${names[kind]?'立即生效':'保留原有参数'}</span>`}</article>`;}).join('')||'<p class="helper">尚未添加动作。在左侧选择动作，预览后点击添加。</p>';}
 function renderSettings(){
  const c=context();if(!c)return;const values=args(),details=options.appearance?.(role())||c;
  let html=`<div class="action-settings-heading"><h3>${h(preset&&selected===null?presets[preset].label:actionName(code))}</h3><span>${selected===null?'待添加 · '+h(initial.name):'编辑已添加动作 · '+h(name(role()))}</span></div>`;
  if([1001,1002,1003,2001].includes(code)){const index=code===2001?0:1;html+=`<label class="action-param"><span>${code===2001?'退场方向':'登场位置'}</span><select data-action-arg="${index}">${(code===2001?[[1,'向左滑出'],[2,'向右滑出']]:[[1,'左侧'],[3,'中间'],[2,'右侧']]).map(([n,s])=>`<option value="${n}" ${Number(values[index])===n?'selected':''}>${s}</option>`).join('')}</select></label>`;}
  if(code===3001)html+=range(0,'跳跃次数',1,5,1,'次')+range(2,'跳跃力度',.2,5,.1,'');
  if(code===3002)html+=range(0,'摇晃时长',.1,3,.1);
  if(code===3000)html+=`<label class="action-param"><span>表情</span><select data-action-arg="0">${details.faces.map(f=>`<option value="${f.id}" ${Number(values[0])===f.id?'selected':''}>${h(f.name)}</option>`).join('')}</select></label>`;
  if(code===3006)html+=`<label class="action-param"><span>服装</span><select data-action-arg="0">${details.clothes.map(n=>`<option value="${n}" ${Number(values[0])===n?'selected':''}>${n?'服装 '+(n+1):'默认服装'}</option>`).join('')}</select></label>`;
  if(code===3004||code===3008){const v=Number(values[0])||0;html+=`<label class="action-param"><span>${code===3004?'水平位移（右为正）':'竖直位移（上为正）'}<output>${h(v)}</output></span><input type="range" data-action-arg="0" min="${Math.min(-1500,v)}" max="${Math.max(1500,v)}" step="5" value="${h(v)}" data-unit=""></label><label class="action-param action-param-number"><span>精确数值</span><input type="number" data-action-arg="0" step="1" value="${h(v)}"></label><p class="helper">也可以直接在舞台上拖动人物设置位移；点“播放”预览。</p>`;}
  if(code===3009){const index=Number(values[0])||0;html+=`<p class="helper">气泡按原版 img_bubble_face 素材显示在人物头顶（位置取自人物的 bubbleParm）。</p><div class="action-param action-emoji-param"><span>气泡表情</span><div class="action-emoji-current">${window.StudentAgeSocialMedia?.renderText?.('<sprite='+index+'>',atlas)||''}<span>表情 ${index}</span><button type="button" data-action-emoji>选择表情</button></div></div>`;}
  if(delays[code]!==undefined)html+=range(delays[code],'延迟',0,10,.1);
  else html+='<p class="helper">'+(names[code]?'此设置在本句开始时立即生效。':'此扩展动作的原有参数会完整保留。')+'</p>';
  if(!names[code])html+=StudentAgeConditions.parameterHTML(values,'data-action-raw','float');q('.action-settings').innerHTML=html;q('[data-action-add]').disabled=selected!==null;q('[data-action-add]').textContent=selected===null?'添加':'已添加';
 }
 function render(){const entries=[...Object.entries(actions).filter(([id])=>!options.blocked?.includes(Number(id))),...(options.blocked?.includes(3008)?[]:Object.entries(presets).map(([key,p])=>[key,p.label]))];q('nav').innerHTML=entries.map(([id,label])=>{const active=selected===null&&(presets[id]?preset===id:!preset&&Number(id)===code);return `<button data-action-code="${id}" class="${active?'active':''}" aria-pressed="${active}">${label}</button>`;}).join('');renderList();renderSettings();status('');}
 function add(){if(selected!==null)return;stop();const label=preset?presets[preset].label:actionName(code);const index=options.add(code,draft.slice());if(!Number.isInteger(index))return;selected=index;preset=null;render();draw();status('已添加 '+label);}
 function pickEmoji(){const d=document.createElement('dialog');d.className='social-dialog social-emoji-dialog';const close=()=>{d.close();d.remove();};d.innerHTML=`<header><h2>选择气泡表情</h2><button data-emoji-close aria-label="关闭表情选择">×</button></header><div class="social-emoji-grid">${glyphs().map((g,i)=>`<button data-emoji-pick="${i}" title="表情 ${i}">${window.StudentAgeSocialMedia.renderText('<sprite='+i+'>',atlas)}</button>`).join('')||'<p class="helper">表情资源尚未读取。</p>'}</div>`;
  d.onclick=e=>{const b=e.target.closest('[data-emoji-pick]');if(b){const values=args().slice();values[0]=Number(b.dataset.emojiPick);close();stop();if(selected===null)draft=values;else options.update(selected,values);renderSettings();renderList();draw();status(selected===null?'表情已选择，点击添加写入本句。':'气泡表情已更新');}else if(e.target.closest('[data-emoji-close]'))close();};d.oncancel=e=>{e.preventDefault();close();};document.body.append(d);d.showModal();}
 function schedule(c,before,after,all){
  playing=true;q(all?'[data-actions-play]':'[data-action-play]').textContent=all?'停止全部':'停止';status(all?'正在播放本句全部动作与声音':'正在预览：'+actionName(code));
  renderer.draw(c.doc,after,{edit:false,animate:true,fromState:before});if(all)audio?.enter(c.row.id);
  const duration=Math.max(650,...after.motions.map(m=>(Math.max(0,m.delay||0)+Math.max(.4,m.duration||0,m.shake||0))*1000+100));
  const finish=()=>{if(closed||!playing)return;if(all&&audio?.sfx.some(a=>!a.ended&&!a.paused&&!a.error)){timer=setTimeout(finish,200);return;}audio?.stop();timer=frame=null;playing=false;q('[data-action-play]').textContent='播放';q('[data-actions-play]').textContent='播放全部';status('播放结束');};timer=setTimeout(finish,duration);
 }
 function play(all=false){
  if(playing){stop();draw();status('已停止');return;}stop();const c=context();if(!c)return;
  if(all){schedule(c,c.before,c.after,true);return;}
  const id=role(),before=JSON.parse(JSON.stringify(c.after)),actor=before.roles[id]||c.before.roles[id];
  if(actor){before.roles[id]=JSON.parse(JSON.stringify(actor));before.roles[id].visible=![1001,1002,1003].includes(code);}
  if((code===3000||code===3006)&&c.before.roles[id])before.roles[id][code===3000?'face':'cloth']=c.before.roles[id][code===3000?'face':'cloth'];
  if((code===3004||code===3008)&&before.roles[id])before.roles[id][code===3004?'x':'y']-=Number(args()[0])||0;
  const row={...c.row,roles:[[id,code,...args()]],bg:0,screenEffect:[],effect:[],effect2:[],miniGame:[]};schedule(c,before,StudentAgeScene.apply(c.doc,before,row,c.grade),false);
 }
 function close(){if(closed)return;closed=true;stop();renderer.dispose();dialog.close();dialog.remove();active=null;options.onClose?.();}
 dialog.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.hasAttribute('data-action-emoji')){pickEmoji();return;}if(b.hasAttribute('data-action-close'))close();else if(b.dataset.actionCode)select(b.dataset.actionCode);else if(b.hasAttribute('data-action-existing'))choose(Number(b.dataset.actionExisting));else if(b.hasAttribute('data-action-play'))play();else if(b.hasAttribute('data-actions-play'))play(true);else if(b.hasAttribute('data-action-add'))add();else if(b.hasAttribute('data-action-delete')){stop();const index=Number(b.dataset.actionDelete);options.update(index,null);if(selected===index){selected=null;preset=null;code=3001;draft=defaults(code);}else if(selected>index)selected--;render();draw();}});
 function change(e){const input=e.target;if(e.isComposing)return;if(input.hasAttribute('data-action-raw')){const r=StudentAgeConditions.readParameterInput(input);if(!r.error){stop();if(selected===null)draft=r.values;else options.update(selected,r.values);draw();}return;}
  if(input.hasAttribute('data-added-delay')){if(e.type!=='input')return;if(input.value===''||!input.validity.valid)return;const value=Number(input.value);if(!Number.isFinite(value)||value<0||value>3600)return;const index=Number(input.dataset.addedDelay),row=context()?.row.roles?.[index],arg=delays[Number(row?.[1])];if(arg===undefined)return;stop();const values=row.slice(2);while(values.length<=arg)values.push(0);values[arg]=value;options.update(index,values);if(selected===index)renderSettings();draw();status('已调整动作延迟');return;}
  if(!input.hasAttribute('data-action-arg')||(e.type==='input'&&input.tagName==='SELECT')||(e.type==='change'&&input.tagName!=='SELECT'))return;
  const value=Number(input.value);if(!Number.isFinite(value))return;stop();const values=args().slice();values[Number(input.dataset.actionArg)]=value;if(selected===null)draft=values;else{options.update(selected,values);renderList();}
  const out=input.parentElement.querySelector('output');if(out)out.textContent=input.value+(input.dataset.unit||'');draw();status(selected===null?'参数已准备，点击添加写入本句。':'动作参数已更新');
 }
 dialog.addEventListener('compositionend',change);dialog.addEventListener('input',change);dialog.addEventListener('change',change);dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
 active={close,refresh:()=>{renderer.invalidateAssets();if(!playing)draw();}};render();draw();q('nav button.active')?.focus();return active;
}
window.StudentAgeActionEditor={open,close:()=>active?.close(),refresh:()=>active?.refresh()};
})();

// Shared TalkCfg stage controls for non-event workbenches. Commands use the
// same planner, native reconstruction and action editor as the story stage.
(()=>{'use strict';
const clone=structuredClone,esc=v=>StudentAgeCharacterUI.esc(v);
function create(o){
 let selected=null,disposed=false,ownsActions=false,menu=null;
 const valid=()=>!disposed&&o.editable()&&o.talk(),doc=()=>o.doc();
 function state(before=false,document=doc()){const ctx=o.context();return StudentAgeScene.reconstruct(document,o.talk()?.id,{...ctx,trace:before?ctx.trace.slice(0,-1):ctx.trace});}
 const name=id=>doc().persons[id]?.name||(Number(id)===0?'白雨':'人物 '+id);
 function actors(){const current=state(),previous=state(true),ids=new Set([...Object.values(current.roles).filter(r=>r.visible).map(r=>r.id),...Object.values(previous.roles).filter(r=>r.visible).map(r=>r.id),...(doc().talks[o.talk()?.id]?.roles||[]).map(r=>Number(r[0]))]);return [...ids].map(id=>current.roles[id]||previous.roles[id]||{id,visible:false});}
 function choose(id){selected=Number(id);o.select?.(selected);render();}
 function entry(role){
  const e=StudentAgeScene.roleEntry(doc(),state(),role);if(!e)return null;
  const rows=e.implicit?.length?clone(e.implicit):clone(doc().talks[e.talkId]?.roles||[]);
  if(e.index<0&&!e.implicit?.length)rows.unshift([Number(role),1001,e.layer||1,e.axis,0]);
  const index=rows.findIndex(r=>Number(r[0])===Number(role)&&[1001,1002,1003].includes(Number(r[1])));if(index<0)return null;
  return {id:e.talkId,index,axis:Number(rows[index][3])||e.axis,rows};
 }
 function position(axis){if(!valid()||![1,2,3].includes(axis))return;const e=entry(selected);if(!e||e.axis===axis)return;const roles=clone(e.rows);roles[e.index][3]=axis;o.edit(e.id,t=>t.roles=roles);render();}
 function drag(role,dx,dy,c){if(!valid()||Number(c?.talkId)!==Number(o.talk().id))return;try{const d=doc(),id=o.talk().id,s=state(false,d),actor=s.roles[role];if(!actor?.visible)return;const target={x:Math.round((c?.x??actor.x)+dx),y:Math.round((c?.y??actor.y)+dy)};const roles=StudentAgeScene.planSceneDrag(d.talks[id],s,role,target,roles=>state(false,{...d,talks:{...d.talks,[id]:{...d.talks[id],roles}}}));o.edit(id,t=>t.roles=roles);choose(role);}catch(e){o.status(e.message,true);}}
 function appearance(id){const d=doc(),actor=state().roles[id]||state(true).roles[id],person=d.persons[id],grade=actor?.grade??o.context().grade,cloth=actor?.cloth||0;return {faces:StudentAgeExpressions.choices({person,faces:d.faces,roleId:id,grade,cloth,metadata:o.metadata?.(id,grade,cloth)}),clothes:[...new Set([0,cloth,...(person?.[grade?'url2':'url']||[]).map((v,i)=>v?i:0),...(person?.[grade?'l2d2':'l2d']||[]).map((v,i)=>v?i:0)])].sort((a,b)=>a-b)};}
 function actions(){if(!valid())return;const id=o.talk().id,role=selected??actors()[0]?.id;if(role==null)return;const current=()=>valid()&&o.talk().id===id;
  ownsActions=true;StudentAgeActionEditor.open({assetUrl:o.assetUrl,appearance,context:()=>current()?{doc:doc(),grade:o.context().grade,before:state(true),after:state(),row:doc().talks[id],role,name:name(role),...appearance(role)}:null,
   add:(code,args)=>{if(!current())return null;const rows=clone(doc().talks[id].roles||[]),group=[1001,1002,1003].includes(code)?[1001,1002,1003]:[2001,2002].includes(code)?[2001,2002]:[code];const kept=rows.filter(r=>!(Number(r[0])===role&&group.includes(Number(r[1]))));kept.push([role,code,...args]);o.edit(id,t=>t.roles=kept);return kept.length-1;},
   update:(index,args)=>{if(!current())return;const roles=clone(doc().talks[id].roles||[]),r=roles[index];if(!r)return;if(args)roles[index]=[r[0],r[1],...args];else roles.splice(index,1);o.edit(id,t=>t.roles=roles);},onClose:()=>{ownsActions=false;if(!disposed){o.draw();render();}}});
 }
 function render(){const el=o.host();if(!el||!o.talk())return;const list=actors();if(!list.some(r=>r.id===selected))selected=list[0]?.id??null;const e=selected===null?null:entry(selected),disabled=!valid();el.innerHTML=`<div class="dialogue-cast" role="group" aria-label="本句人物">${list.map(r=>`<button data-stage-role="${r.id}" aria-pressed="${selected===r.id}">[${r.id}] ${esc(name(r.id))}${r.visible?'':' · 已退场'}</button>`).join('')}</div><div class="dialogue-position"><span>初始站位</span>${[[1,'左'],[3,'中'],[2,'右']].map(([axis,label])=>`<button data-stage-axis="${axis}" aria-pressed="${e?.axis===axis}" ${disabled||!e?'disabled':''}>${label}</button>`).join('')}<button data-stage-actions ${disabled||selected===null?'disabled':''}>人物动作</button></div>`;
 el.onclick=event=>{const b=event.target.closest('button');if(!b||b.disabled)return;event.stopPropagation();if(b.dataset.stageRole!==undefined)choose(b.dataset.stageRole);if(b.dataset.stageAxis)position(Number(b.dataset.stageAxis));if(b.hasAttribute('data-stage-actions'))actions();};
 }
 return {render,choose,rendererOptions:{onBeforeInteract:()=>!!valid(),onDrag:drag,onSelectRole:choose,onContextMenu:(id,x,y)=>{if(!valid())return;choose(id);StudentAgeContextMenu({target:o.host(),clientX:x,clientY:y,preventDefault(){},stopPropagation(){}},[{label:'人物动作',action:actions},...[[1,'左'],[3,'中'],[2,'右']].map(([axis,label])=>({label:'初始站位 · '+label,action:()=>position(axis)}))]);menu=document.querySelector('.studio-delete-menu');}},dispose(){disposed=true;menu?._dismiss?.();if(ownsActions)StudentAgeActionEditor.close();}};
}
// NewTalkView keeps the previous cast and adds movement deltas to its targets.
// A continuation inherits that state through nextTalk, not by replaying commands.
function continuation(previous,id){return {...clone(previous||{}),id,content:'',roles:[],bg:0,audio:0,screenEffect:[],nextTalk:[],nextTalk2:[],option:[],check:[],effect:[],effect2:[]};}
window.StudentAgeDialogueStage={create,continuation};})();
