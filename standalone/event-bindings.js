/* Native ActionEvtCfg / ActionCfg and InteractCfg bindings, edited beside event types. */
(()=>{'use strict';const UI=()=>StudentAgeCharacterUI,esc=v=>UI().esc(v),copy=v=>structuredClone(v);
async function actionPicker(projectId,rows,selected=[],settings={}){
 const d=document.createElement('dialog');d.className='character-picker action-library';document.body.append(d);let source='all',group='全部',q='';const chosen=new Set(selected.map(Number));
 const maps=(await UI().api('table?'+new URLSearchParams({projectId,name:'MapCfg'}))).rows;
 const category=r=>Number(r.type)===4?'兼职':Number(r.type)===3?'约会':/学习|复习|练习|作业|阅读|读书|上课/.test(r.name||'')?'学习':/聊天|社交|拜访|交谈|闲聊/.test(r.name||'')?'社交':/买|购物|休息|打扫|吃|做饭/.test(r.name||'')?'日常':'娱乐与其他';
 d.innerHTML='<header><h2>行动素材库</h2><button data-action-close>×</button></header><nav class="character-filters">'+['全部','学习','社交','约会','兼职','日常','娱乐与其他'].map(l=>`<button data-action-group="${l}">${l}</button>`).join('')+'</nav><div class="warehouse-search"><input data-action-search placeholder="搜索行动或地点"><select data-action-map><option value="all">全部地点</option>'+Object.values(maps).map(r=>`<option value="${r.id}">${esc(r.name)}</option>`).join('')+'</select></div><div class="character-choice-grid"></div><footer><span data-action-count></span><button data-action-confirm class="primary">确定</button></footer>';
 const paint=()=>{d.querySelector('.character-choice-grid').innerHTML=rows.filter(r=>(group==='全部'||category(r)===group)&&(source==='all'||String(r.map)===source)&&StudentAgeSearch.matches(q,r.name,r.id,maps[r.map]?.name)).map(r=>`<button data-action-id="${r.id}" class="${chosen.has(Number(r.id))?'active':''}"><strong>${esc(r.name)}</strong><small>${esc(maps[r.map]?.name||'其他地点')}</small></button>`).join('');d.querySelector('[data-action-count]').textContent='已选择 '+chosen.size+(settings.places?' 个地点':' 个行动');d.querySelectorAll('[data-action-group]').forEach(b=>b.classList.toggle('active',b.dataset.actionGroup===group));};let resolve;const promise=new Promise(r=>resolve=r),end=v=>{d.close();d.remove();resolve(v);};d.oncancel=e=>{e.preventDefault();end(null);};d.onclick=e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.actionGroup){group=b.dataset.actionGroup;paint();}if(b.dataset.actionId){const id=Number(b.dataset.actionId);if(settings.single){chosen.clear();chosen.add(id);}else chosen.has(id)?chosen.delete(id):chosen.add(id);paint();}if(b.hasAttribute('data-action-close'))end(null);if(b.hasAttribute('data-action-confirm'))end([...chosen]);};d.oninput=e=>{if(e.target.hasAttribute('data-action-search'))q=e.target.value;if(e.target.hasAttribute('data-action-map'))source=e.target.value;paint();};if(settings.places){d.querySelector('h2').textContent='选择社交地点';d.querySelector('nav').hidden=true;d.querySelector('[data-action-map]').hidden=true;d.querySelector('input').placeholder='搜索地点';}paint();d.showModal();return promise;
}
const socialNames={2:'社交触发事件',22:'恋爱话题事件',11:'约会事件',521:'约会事件',20:'关系事件',[-24]:'社交小游戏事件'};
const socialKinds={2:'favor',22:'topic',11:'date',521:'date',20:'relation',[-24]:'minigame'};
function displayType(e){return e?.studioSocial?.kind==='talk'?-2:e?.studioSocial?.kind==='minigame'?-24:e?.studioSocial?.kind==='date'||Number(e?.type)===521?11:Number(e?.type)||0;}
function socialDraft(event={}){const old=event.studioSocial||{},kind=old.kind||socialKinds[event.type];return {...old,kind,text:old.text||'',favor:old.favor??event.condition?.find(r=>r[0]===7&&r[1]===1&&r[2]===event.npc)?.[3]??0,title:event.title||'',maxcount:event.maxcount??1,repeat:(event.maxcount??1)>1,intimacy:old.intimacy??event.effect?.find(r=>r[0]===1&&r[1]===520)?.[2]??0,actionId:old.actionId||0,level:old.level||1};}
function socialCommands(event,draft,npc){
 const previous=event.studioSocial||{},same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 const condition=(event.condition||[]).filter(r=>!([...(previous.conditions||[]),...(previous.entryConditions||[])]).some(v=>same(v,r))),effect=(event.effect||[]).filter(r=>!(previous.effects||[]).some(v=>same(v,r)));
 const generatedConditions=[],generatedEffects=[];
 if(draft.kind==='favor')generatedConditions.push([7,1,npc,Number(draft.favor)||0]);
 if(['topic','loveTalk','date'].includes(draft.kind))generatedConditions.push([7,0,npc,520]);
 if(draft.kind==='topic'&&Number(draft.intimacy))generatedEffects.push([1,520,Number(draft.intimacy)]);
 for(const r of generatedConditions)if(!condition.some(v=>same(v,r)))condition.push(r);
 for(const r of generatedEffects)if(!effect.some(v=>same(v,r)))effect.push(r);
 return {condition,effect,studioSocial:{...draft,entryConditions:[],conditions:generatedConditions,effects:generatedEffects}};
}
function socialMount(node,state,parameters,options){
 const kind=socialKinds[options.type];if(!kind)return false;
 const r=state.social??=socialDraft(parameters.event);r.kind=kind;
 const count=()=>`<label>事件最多重复次数<input type="number" min="1" max="2147483647" step="1" data-social-field="maxcount" value="${r.maxcount}"></label>`;
 node.innerHTML=(kind==='talk'?`<label>闲聊进度文字<input data-social-field="text" placeholder="正在和谁一起……" value="${esc(r.text)}"></label><p class="helper">首次满足条件时播放一次剧情；之后闲聊使用这段进度文字，不再重复剧情。</p>`:'')+(kind==='loveTalk'?count():'')+(kind==='favor'?`<label>好感度大于等于<input type="number" min="0" step="any" data-social-field="favor" value="${r.favor}"></label><p class="helper">自动添加好感度条件；游戏闲聊入口会按原版规则提示红点。</p>`:'')+(kind==='topic'?`<label><input type="checkbox" data-social-field="repeat" ${r.repeat?'checked':''}>话题可以重复出现</label><label>话题名称<input data-social-field="title" value="${esc(r.title)}"></label><label>增加亲密度（可为负）<input type="number" step="any" data-social-field="intimacy" value="${r.intimacy}"></label>`:'')+(['date','relation'].includes(kind)?`<label>${kind==='date'?'约会行动（包括电影）':'事件结束后解锁行动'}<button data-social-action>${esc(parameters.actions?.[r.actionId]?.name||'打开行动目录')} ▾</button></label>${kind==='relation'?'<p class="helper">解锁一份独立的一次性行动，完成后消失。</p>':'<p class="helper">电影沿用原版剧情入口；小游戏约会需安装新版拾光工坊扩展，在活动前播放剧情。</p>'}`:'')+(kind==='minigame'?`<label>小游戏关卡<select data-social-field="level">${[1,2,3,4,5].map(n=>`<option value="${n}" ${r.level===n?'selected':''}>第 ${n} 关</option>`).join('')}</select></label><p class="helper">在所选人物的这一关开始前播放剧情；需要游戏安装新版拾光工坊扩展，其他角色保持原有剧情。</p>`:'');
 node.oninput=e=>{const key=e.target.dataset.socialField;if(!key)return;r[key]=e.target.type==='checkbox'?e.target.checked:['text','title'].includes(key)?e.target.value:Number(e.target.value);};
 node.onclick=async e=>{if(!e.target.closest('[data-social-action]'))return;try{const rows=Object.values(parameters.actions||{}).filter(a=>kind!=='date'||Number(a.type)===3),chosen=await actionPicker(options.projectId,rows,r.actionId?[r.actionId]:[],{single:true});if(chosen){r.actionId=chosen[0]||0;options.repaint();}}catch(error){options.error(error);}};
 return true;
}
function validateSocial(doc,event,state,refs){const r=state.social;if(!r)return;if(!Number.isInteger(event.maxcount)||event.maxcount<1||event.maxcount>2147483647)throw Error('重复次数应为正整数。');if(!Number.isFinite(Number(r.favor))||Number(r.favor)<0||!Number.isFinite(Number(r.intimacy)))throw Error('请填写有效的好感度和亲密度数值。');if(r.kind==='talk'&&!r.text.trim())throw Error('请填写正在和谁一起做什么。');if(['date','relation'].includes(r.kind)&&!({...refs.ActionCfg,...doc.actions})[r.actionId])throw Error('请选择行动。');if(r.kind==='date'){const a=({...refs.ActionCfg,...doc.actions})[r.actionId];if(Number(a.type)!==3)throw Error('请选择约会行动。');}
 if(r.kind==='minigame'){const grow=refs.PersonGrowCfg?.[event.npc],level=Number(grow?.minigame)*100+Number(r.level);if(!refs.MinigameActionCfg?.[level])throw Error('该角色尚未关联有效的社交小游戏或关卡。请先到人物属性成长中设置小游戏。');}
}
// Talk-based native events execute TalkCfg effects, not EvtCfg.effect.
// Keep owned native links current, including when dialogue roots change outside the event form.
function syncSocialEffects(doc){
 for(const event of Object.values(doc.events||{})){
  if(event.studioSocial?.kind==='favor')syncSocialEntry(event);

  if(event.studioGiftBindings?.length){
   const desired=giftsForEvent(doc,event).filter(r=>(event.studioGiftBindings||[]).some(v=>Number(v.id)===r.id&&Number(v.index)===r.index));
   applyGifts(doc,event,desired,desired,rows=>{let id=Math.max(1000000,...Object.keys(rows).map(Number))+1;while(rows[id])id++;return id;});
  }
 }
 const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b),talks=doc.talks||{};
 for(const t of Object.values(talks)){if(!t.studioSocialEffects)continue;
  for(const rows of Object.values(t.studioSocialEffects))for(const r of rows){const i=(t.effect||[]).findIndex(v=>same(v,r));if(i>=0)t.effect.splice(i,1);}t.studioSocialEffects={};
 }
 const append=(t,eventId,rows)=>{if(!t)return;t.effect??=[];t.studioSocialEffects??={};const added=rows.filter(r=>!t.effect.some(v=>same(v,r)));t.effect.push(...copy(added));(t.studioSocialEffects[eventId]??=[]).push(...copy(added));};
 for(const e of Object.values(doc.events||{})){
  const gift=e.studioGiftBindings?.length;
  // GiftEvtCfg enters ShowTalk directly: count entry, not completion, just like native ShowEvent.
  if(gift)for(const id of new Set(e.talkId||[]))append(talks[id],e.id,[[50,2,e.id,e.studioGiftCounterSlot,1]]);
  const effects=(e.studioSocial||gift)?e.effect:[];if(!effects?.length||e.content&&!gift)continue;
  const seen=new Set(),todo=[...(e.talkId||[])];while(todo.length){const id=todo.pop(),t=talks[id];if(!t||seen.has(id))continue;seen.add(id);
   const next=[...(t.nextTalk||[]),...(t.nextTalk2||[])].filter(v=>v>0),opts=(t.option||[]).map(id=>doc.options?.[id]).filter(Boolean);
   for(const o of opts)next.push(...(o.talkId||[]),...(o.talkId2||[]));
   if(!next.length&&!opts.length)append(t,e.id,effects);
   todo.push(...next.filter(v=>v>0));
  }
 }
}
function syncSocialEntry(event){
 const old=event.studioSocial.entryConditions||[],same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 event.condition=(event.condition||[]).filter(r=>!old.some(v=>same(v,r)));
 const rows=[];if(event.mapId>0&&event.npc>0)rows.push([7,101,event.npc,event.mapId]);
 if(Number.isFinite(event.rate)&&event.rate<1)rows.push([0,1,event.rate<=0?-1:event.rate]);
 const added=rows.filter(r=>!event.condition.some(v=>same(v,r)));event.condition.push(...added);event.studioSocial.entryConditions=copy(added);
}
function syncChat(doc,event){
 syncSocialEntry(event);
 event.type=2;event.maxcount=1;event.studioSocial.maxcount=1;
 const id=event.studioSocial.interactionId;if(!id)return;
 doc.interactions??={};
 doc.interactions[id]={...(doc.interactions[id]||{}),id,npc:event.npc,name:event.title,text:event.studioSocial.text||'',map:event.mapId?[event.mapId]:[],talkId:0,cond:[...copy((event.condition||[]).filter(r=>!(event.studioSocial.entryConditions||[]).some(v=>JSON.stringify(v)===JSON.stringify(r)))),[3,1,event.id,0,1]],effect:[]};
}
function giftConditions(doc,event){
 if(!Number.isInteger(event.studioGiftCounterSlot)){
  // Native event values are a dictionary; reserve an unused negative slot, independent of premise slots.
  const used=new Set();const visit=value=>{if(Array.isArray(value)){if((value[0]===111||value[0]===50&&[2,20].includes(value[1]))&&value[2]===event.id)used.add(value[3]);for(const v of value)visit(v);}else if(value&&typeof value==='object')for(const v of Object.values(value))visit(v);};visit(doc);
  let slot=-1;while(used.has(slot))slot--;event.studioGiftCounterSlot=slot;
 }
 const rows=copy(event.condition||[]),count=Math.max(0,Number(event.maxcount)||0);
 rows.push([111,-1,event.id,event.studioGiftCounterSlot,count-1]);
 if(Number.isFinite(event.rate)&&event.rate<1)rows.push([0,1,event.rate<=0?-1:event.rate]);
 return rows;
}
function clearSocialBindings(doc,event,keep={}){const old=event.studioSocial||{};
 if(old.interactionId&&keep.kind!=='talk')delete doc.interactions?.[old.interactionId];
 if(old.unlockedActionId&&(keep.kind!=='relation'||keep.actionId!==old.actionId))delete doc.actions?.[old.unlockedActionId];
 if(old.minigameActionId&&(keep.kind!=='minigame'||keep.minigameActionId!==old.minigameActionId)){const row=doc.minigameActions?.[old.minigameActionId];if(row&&event.talkId?.includes(row.startTalk))row.startTalk=old.previousStartTalk||0;}
}
function applySocial(doc,event,state,refs,allocate){const r=state.social,previous=event.studioSocial;
 const miniId=r?.kind==='minigame'?Number(refs.PersonGrowCfg[event.npc].minigame)*100+Number(r.level):0;
 clearSocialBindings(doc,event,{...r,minigameActionId:miniId});
 if(!r){event.studioSocial={};return;}
 const chosen=copy(r);Object.assign(event,socialCommands(event,chosen,event.npc));
 if(r.kind==='talk'){
  const id=previous?.interactionId||allocate('InteractCfg',doc.interactions);event.studioSocial.interactionId=id;syncChat(doc,event);
 }
 if(r.kind==='date'){
  const a=doc.actions[r.actionId]||refs.ActionCfg[r.actionId];const pooled=Number(a.evtType)>0&&!Number(a.minigameId)&&!Number(a.evtId);event.type=pooled?Number(a.evtType):4;event.studioSocial.nativeTrigger=pooled?'date-pool':'date-action';
 }
 if(r.kind==='relation'){
  const same=previous?.actionId===r.actionId,id=same&&previous.unlockedActionId||allocate('ActionCfg',doc.actions),source=copy(doc.actions[r.actionId]||refs.ActionCfg[r.actionId]);
  doc.actions[id]={...source,id,unlock:[],effect:[...(source.effect||[]),[40,-1,id]]};event.studioSocial.unlockedActionId=id;
  const unlock=[40,1,id];event.effect.push(unlock);event.studioSocial.effects.push(unlock);
 }
 if(r.kind==='minigame'){
  event.type=4;const id=refs.PersonGrowCfg[event.npc].minigame*100+r.level;
  event.studioSocial.minigameActionId=id;event.studioSocial.nativeTrigger='social-minigame';
 }
 if(previous?.interactionId&&r.kind!=='talk')delete doc.interactions[previous.interactionId];
}

function create(parameters){
 const state=copy(parameters.bindings||{actions:[],interactions:[]});state.actions??=[];state.interactions??=[];state.gifts??=[];let interactionIndex=0;
 function mount(host,options){if(!parameters.bindings)return;const type=Number(options.type),social=[2,21,22,522].includes(type);if(type!==4&&type!==110&&!social&&!socialKinds[type]){state.social=null;return;}
 const node=document.createElement('section');node.className='event-linked-settings';host.append(node);
 if(socialMount(node,state,parameters,options))return;
 state.social=null;
 if(type===110){
  if(!state.gifts.length)state.gifts.push({id:null,index:0,npc:0,item:0,type:0});
  node.innerHTML='<h3>送礼对话设置</h3>'+state.gifts.map((r,i)=>`<article><label>收礼人<button data-gift-person="${i}">${esc(parameters.persons?.[r.npc]?.name||parameters.refs?.PersonCfg?.[r.npc]?.name||(r.npc?'人物 '+r.npc:'选择收礼人'))} ▾</button></label><label>礼物物品<button data-gift-pick="${i}">${esc(r.itemName||parameters.refs?.ItemCfg?.[r.item]?.name||parameters.refs?.BookCfg?.[r.item]?.name||(r.item?'物品 '+r.item:'打开物品仓库'))} ▾</button></label>${r.sourceName?`<small>来自 ${esc(r.sourceName)} · 游戏中需同时启用该模组</small>`:''}</article>`).join('')+'<p class="helper">赠送指定物品给所选人物时，播放本事件的首句对话。应用后随模组一起保存。</p>';
  node.onclick=async e=>{const b=e.target.closest('button');if(!b)return;try{
   if(b.dataset.giftPerson!==undefined){const r=state.gifts[Number(b.dataset.giftPerson)],people={...parameters.refs?.PersonCfg,...parameters.persons};const chosen=await UI().choices('选择收礼人',Object.values(people).filter(p=>Number(p.id)>0),{selected:r.npc});if(chosen){r.npc=Number(chosen.id);options.repaint();}}
   if(b.dataset.giftPick!==undefined){const r=state.gifts[Number(b.dataset.giftPick)],chosen=await StudentAgeWarehouse.pick(options.projectId,r.item);if(chosen){r.item=Number(chosen.id);r.itemName=chosen.name;r.sourceName=chosen.sourceName;r.itemTable=chosen.table;options.repaint();}}
  }catch(error){options.error(error);}};return;
 }
 if(type===4){node.innerHTML='<h3>行动触发设置</h3><button data-bind-actions>选择行动 ▾</button>'+state.actions.map((r,i)=>`<article><strong>${esc(parameters.actions?.[r.id]?.name||'行动 '+r.id)}</strong><button data-bind-action-remove="${i}" aria-label="移除行动">×</button><label>触发方式<select data-bind-action-mode="${i}"><option value="pool" ${r.mode!=='direct'?'selected':''}>随机剧情池</option><option value="direct" ${r.mode==='direct'?'selected':''}>固定剧情</option></select></label>${r.mode!=='direct'?`<label>行动剧情池触发概率（%）<input type="number" min="0" max="100" step="any" data-bind-action-rate="${i}" value="${(r.rate??1)*100}"></label>`:''}</article>`).join('')+'<p class="helper">随机剧情池会保留该行动已有的其他事件；概率由同一行动共用。</p>';
 node.onclick=async e=>{try{if(e.target.closest('[data-bind-actions]')){const chosen=await actionPicker(options.projectId,Object.values(parameters.actions||{}),state.actions.map(r=>r.id));if(chosen){state.actions=chosen.map(id=>state.actions.find(r=>r.id===id)||{id,mode:'pool',rate:parameters.actionEvents?.[id]?.rate??1});options.repaint();}}const remove=e.target.closest('[data-bind-action-remove]');if(remove){state.actions.splice(Number(remove.dataset.bindActionRemove),1);options.repaint();}}catch(error){options.error(error);}};
 node.oninput=e=>{const el=e.target;if(el.dataset.bindActionRate!==undefined){const v=Number(el.value);el.setCustomValidity(!Number.isFinite(v)||v<0||v>100?'概率应为 0 到 100':'');if(!el.validationMessage)state.actions[Number(el.dataset.bindActionRate)].rate=v/100;}};
 node.onchange=e=>{if(e.target.dataset.bindActionMode!==undefined){state.actions[Number(e.target.dataset.bindActionMode)].mode=e.target.value;options.repaint();}};
 }else{interactionIndex=Math.min(interactionIndex,Math.max(0,state.interactions.length-1));const r=state.interactions[interactionIndex];node.innerHTML='<h3>社交进度与后续对话</h3><div class="character-filters">'+state.interactions.map((r,i)=>`<button data-bind-interaction="${i}" class="${i===interactionIndex?'active':''}">${esc(r.name||'互动 '+(i+1))}</button>`).join('')+'<button data-bind-add>＋ 添加互动</button><button data-bind-existing>已有互动</button></div>'+(r?`<label>备注<input data-bind-field="name" value="${esc(r.name)}"></label><label>进度条文字<input data-bind-field="text" value="${esc(r.text)}" placeholder="正在和某人一起……"></label><label>发生地点<button data-bind-places>${esc((r.map||[]).map(id=>parameters.refs?.MapCfg?.[id]?.name||id).join('、')||'不限地点')} ▾</button></label><label>进度结束后的对话<button data-bind-talk>${esc(parameters.talks?.[r.talkId]?.content||'使用本事件首句对话')} ▾</button></label><h4>互动出现条件</h4><div data-bind-cond></div><h4>互动结束效果</h4><div data-bind-effects></div><button data-bind-remove class="danger-text">删除这条互动</button>`:'<p class="helper">可为当前事件设置社交时显示的进度文字、地点、条件与效果。</p>');
 if(r){StudentAgeConditions.mount(node.querySelector('[data-bind-cond]'),{rows:r.cond||[],templates:parameters.conditionTemplates||[],refs:parameters.refs||{},localIds:parameters.localIds||{},projectId:options.projectId,onChange:rows=>r.cond=rows});StudentAgeEffects.mount(node.querySelector('[data-bind-effects]'),{rows:r.effect||[],templates:parameters.effectTemplates||[],refs:parameters.refs||{},getPremises:parameters.getPremises,onChange:rows=>r.effect=rows,onError:options.error});}
 node.oninput=e=>{if(e.target.dataset.bindField)r[e.target.dataset.bindField]=e.target.value;};node.onclick=async e=>{const b=e.target.closest('button');if(!b)return;try{if(b.dataset.bindInteraction!==undefined){interactionIndex=Number(b.dataset.bindInteraction);options.repaint();}if(b.hasAttribute('data-bind-add')){state.interactions.push({id:STUDIO_IDS.allocate('InteractCfg',{...parameters.interactions,...Object.fromEntries(state.interactions.map(r=>[r.id,r]))}),npc:options.npc,name:'',text:'',map:[],talkId:0,cond:[],effect:[]});interactionIndex=state.interactions.length-1;options.repaint();}if(b.hasAttribute('data-bind-existing')){const choice=await UI().choices('选择该角色已有的社交互动',Object.values(parameters.interactions||{}).filter(x=>Number(x.npc)===Number(options.npc)&&!state.interactions.some(v=>v.id===x.id)).map(x=>({...x,name:x.name||x.text||'互动 '+x.id})));if(choice){state.interactions.push(copy(parameters.interactions[choice.id]));interactionIndex=state.interactions.length-1;options.repaint();}}if(b.hasAttribute('data-bind-remove')){state.interactions.splice(interactionIndex,1);options.repaint();}if(b.hasAttribute('data-bind-talk')){const choice=await UI().choices('进度结束后播放的对话',[{id:0,name:'本事件首句对话'},...Object.values(parameters.eventTalks||{}).map(t=>({id:t.id,name:t.content||'空白对话 '+t.id}))],{selected:r.talkId});if(choice){r.talkId=choice.id;options.repaint();}}if(b.hasAttribute('data-bind-places')){const rows=Object.values(parameters.refs?.MapCfg||{}),selected=await actionPicker(options.projectId,rows.map(x=>({...x,map:x.id})),r.map||[],{places:true});if(selected){r.map=selected;options.repaint();}}}catch(error){options.error(error);}};
 }
 }
 return {mount,value:()=>copy(state)};
}
function giftsForEvent(doc,event){
 const roots=new Set((event.talkId||[]).map(Number));
 const owned=event.studioGiftBindings||[];
 return Object.values(doc.giftEvents||{}).flatMap(row=>(row.npc||[]).flatMap((npc,index)=>{
  const note=owned.find(v=>Number(v.id)===Number(row.id)&&Number(v.index)===index&&(!v.npc||Number(v.npc)===Number(npc)));
  if(!note&&!(row.talkId?.[index]||[]).some(id=>roots.has(Number(id))))return [];
  return [{id:Number(row.id),index,npc:Number(npc),item:Number(row.item),type:Number(row.type?.[index])||0,itemName:note?.itemName,sourceName:note?.sourceName,itemTable:note?.itemTable}];
 }));
}
function applyGifts(doc,event,before,desired,allocate){
 doc.giftEvents??={};const conditions=desired.length?giftConditions(doc,event):[],original=copy(doc.giftEvents),groups=new Map();
 for(const r of before){const key=String(r.id);if(!groups.has(key))groups.set(key,new Set());groups.get(key).add(r.index);}
 for(const [id,indices]of groups){const row=doc.giftEvents[id];if(!row)continue;
  // Slot indexes belong to all events sharing this native row.
  for(const other of Object.values(doc.events||{})){if(other===event||!other.studioGiftBindings)continue;other.studioGiftBindings=other.studioGiftBindings.filter(v=>String(v.id)!==id||!indices.has(Number(v.index))).map(v=>String(v.id)===id?{...v,index:Number(v.index)-[...indices].filter(i=>i<Number(v.index)).length}:v);}
  for(const field of ['npc','talkId','type'])row[field]=(row[field]||[]).filter((_,i)=>!indices.has(i));}
 const owned=[];
 for(const r of desired){
  let row=doc.giftEvents[r.id];
  if(!row||row.npc.length&&(Number(row.item)!==r.item||JSON.stringify(row.cond||[])!==JSON.stringify(conditions))){
   const id=allocate(doc.giftEvents);row={...(original[r.id]||{}),id,npc:[],talkId:[],type:[],redpoint:original[r.id]?.redpoint??1};doc.giftEvents[id]=row;
  }
  row.item=r.item;row.cond=copy(conditions);const index=row.npc.length;
  while(row.type.length<index)row.type.push(0);
  row.npc.push(r.npc);row.talkId.push(copy(event.talkId||[]));row.type.push(r.type||0);
  owned.push({id:row.id,index,npc:r.npc,itemName:r.itemName,sourceName:r.sourceName,itemTable:r.itemTable});
 }
 for(const id of groups.keys())if(doc.giftEvents[id]&&!doc.giftEvents[id].npc?.length)delete doc.giftEvents[id];
 event.studioGiftBindings=owned;
}
window.StudentAgeEventBindings={socialNames,socialKinds,displayType,socialDraft,socialCommands,validateSocial,applySocial,clearSocialBindings,syncSocialEffects,create,actionPicker,giftsForEvent,applyGifts};})();
