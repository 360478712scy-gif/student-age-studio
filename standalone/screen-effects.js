/* Native TalkCfg.screenEffect; the game accepts one screen command per line. */
(()=>{'use strict';
const entries=[
 {id:4001,name:'屏幕抖动',value:.15,label:'持续秒数',min:.01,max:5,step:.01},
 {id:4002,name:'背景模糊'},{id:4003,name:'清除背景效果'},
 {id:4004,name:'展示物品',table:'ItemCfg',label:'物品'},
 {id:4006,name:'稍后转场'}, {id:4007,name:'打电话'}, {id:4008,name:'挂电话'}, {id:4009,name:'旧照片色调'},{id:4010,name:'背景反色'},
 {id:4011,name:'闭眼 / 睁眼',value:1,label:'闭合程度',min:0,max:1,step:.01},
 {id:4012,name:'闪白',value:1,label:'次数（0 为单次无震动）',min:0,max:10,step:1},
 {id:4013,name:'彩纸飘落'},{id:4018,name:'展示图片',table:'BgCfg',label:'图片'}
];
function state(prior,talk,transition){const screen=talk.screenEffect||[],code=Number(screen[0]),out={filter:transition?'':prior?.filter||'',eyes:prior?.eyes||0,command:screen.slice(),previousEyes:prior?.eyes||0};
 if(code===4002)out.filter='blur(8px)';if(code===4009)out.filter='sepia(1)';if(code===4010)out.filter='invert(1)';if(code===4003)out.filter='';if(code===4011)out.eyes=Math.max(0,Math.min(1,Number(screen[1])||0));return out;}
function draw(renderer,doc,scene,animate){const root=renderer.container;for(const animation of renderer.screenShakeAnimations||[])animation.cancel();renderer.screenShakeAnimations=[];root.querySelector('.scene-backdrop').style.filter=scene.screen?.filter||'';
 let layer=root.querySelector('.scene-screen-effects');if(!layer){layer=document.createElement('div');layer.className='scene-screen-effects';root.append(layer);}layer.getAnimations({subtree:true}).forEach(a=>a.cancel());layer.replaceChildren();
 const add=(cls,css={})=>{const el=document.createElement('div');el.className=cls;Object.assign(el.style,css);layer.append(el);return el;};
 const fx=scene.screen?.command||[],code=Number(fx[0]),eyes=scene.screen?.eyes||0;
 if(eyes||animate&&code===4011&&scene.screen.previousEyes){const top=add('screen-eyelid',{top:'0',height:eyes*50+'%'}),bottom=add('screen-eyelid',{bottom:'0',height:eyes*50+'%'});if(animate&&code===4011)for(const n of [top,bottom])n.animate([{height:(scene.screen.previousEyes||0)*50+'%'},{height:eyes*50+'%'}],{duration:400});}
 if([4004,4018].includes(code)){const record=(code===4004?renderer.options.screenRefs?.().ItemCfg:doc.backgrounds)?.[fx[1]],path=code===4004?record?.icon:record?.url;const card=add('screen-item');if(path){const img=document.createElement('img');img.src=renderer.options.assetUrl(path);img.alt=record.name||'';card.append(img);}else card.textContent=record?.name||'物品 '+fx[1];if(animate)card.animate([{transform:'translate(-50%,-50%) scale(0)'},{transform:'translate(-50%,-50%) scale(1)'}],{duration:200,easing:'ease-out'});}
 if(!animate)return;
 const shake=duration=>{const frames=[{translate:'0 0'},{translate:'-6px 3px'},{translate:'6px -3px'},{translate:'0 0'}],timing={duration:100,iterations:Math.max(1,Math.round(duration*10))};for(const n of root.children){if(n===layer||n.classList.contains('scene-guides'))continue;renderer.screenShakeAnimations.push(n.animate(frames,timing));}};
 if(code===4001)shake(Number(fx[1])||.15);
 if(code===4012){const n=add('screen-flash');n.animate([{opacity:0},{opacity:1,offset:.5},{opacity:0}],{duration:200,iterations:Math.max(1,Math.min(10,Number(fx[1])||1))});if(fx[1])shake(.2*fx[1]);}
 if(code===4013)for(let i=0;i<36;i++){const n=add('screen-confetti',{left:(i*37%100)+'%',background:['#f6c85f','#ef6f9f','#66cbb2','#99b5f8'][i%4]});n.animate([{transform:'translateY(-20px) rotate(0deg)',opacity:1},{transform:`translateY(${root.clientHeight}px) rotate(${i%2?540:-540}deg)`,opacity:0}],{duration:4000,delay:i%9*100,fill:'both'});}
 if(code===4006){const n=add('screen-transition');n.textContent='稍后……';n.animate([{opacity:0},{opacity:1,offset:.143},{opacity:1,offset:.857},{opacity:0}],{duration:2800});}
 const tr=scene.transition;
 if(tr?.kind==='wipe'){const n=add('screen-transition',{opacity:'1',clipPath:'inset(100% 0 0 0)'});n.animate([{clipPath:'inset(0 0 100% 0)'},{clipPath:'inset(0 0 0 0)',offset:1/3},{clipPath:'inset(0 0 0 0)',offset:2/3},{clipPath:'inset(100% 0 0 0)'}],{duration:1200});}
 else if(tr?.kind==='mosaic'){const url=renderer.options.assetUrl(window.StudentAgeScene.backgroundPath(doc,{background:tr.from,roles:scene.roles})),W=root.clientWidth,H=root.clientHeight;for(let i=0;i<48;i++){const x=i%8,y=Math.floor(i/8),n=add('screen-transition-cell',{left:x*12.5+'%',top:y*100/6+'%',width:'12.6%',height:'16.8%',backgroundImage:`url("${url}")`,backgroundSize:`${W}px ${H}px`,backgroundPosition:`${-x*W/8}px ${-y*H/6}px`});n.animate([{clipPath:'inset(0)'},{clipPath:'inset(50%)'}],{duration:500,delay:(i*17%200),fill:'forwards'});}}
}
function duration(scene){const row=scene?.screen?.command||[],id=Number(row[0]);return Math.max(scene?.transition?.kind==='wipe'?1200:scene?.transition?750:0,id===4006?2800:id===4013?5000:id===4001?(row[1]||.15)*1000:id===4012?Math.max(1,row[1]||1)*200:id===4011?400:0);}
async function edit({projectId,api,talk,persons={},allowPaper=false}){
 const UI=StudentAgeCharacterUI,esc=UI.esc,current=structuredClone(talk),items=[...entries,...(allowPaper?[{id:'paper',name:'纸条'}]:[]),{id:'clear',name:'移除本句屏幕效果'}];
 const selected=await UI.choices('屏幕效果',items,{selected:current.screenEffect?.[0]});if(!selected)return null;
 if(selected.id==='paper')return {paper:true};if(selected.id==='clear')return {screenEffect:[]};
 const config=entries.find(r=>r.id===selected.id),value=current.screenEffect?.[0]===config.id?current.screenEffect.slice():[config.id];
 if(config.id===4007){
  const [bgData,personData]=await Promise.all([api('/api/table?'+new URLSearchParams({projectId,name:'BgCfg'})),Object.keys(persons).length?{rows:persons}:api('/api/table?'+new URLSearchParams({projectId,name:'PersonCfg'}))]);
  const backgrounds=bgData.rows||{},people=personData.rows||{};let background=Number(value[1])||0,remote=new Set(value.slice(2).map(Number));
  return new Promise(resolve=>{const d=document.createElement('dialog');d.className='character-picker screen-phone-editor';let closed=false;const end=v=>{closed=true;d.close();d.remove();resolve(v);};
   const personName=id=>people[id]?.name||(id===0?'白雨':'人物 '+id);
   const paint=()=>{d.innerHTML=`<header><h2>打电话</h2><button data-phone-cancel>关闭</button></header><div class="character-picker-body"><label>对方所在背景<button data-phone-bg>${backgrounds[background]?StudentAgeRecordLabels.html(background,window.StudentAgeAssetNames?.name(backgrounds[background],'background')||'背景'):'选择背景'}</button></label><h3>电话另一端的人物</h3><div class="screen-phone-people">${[...remote].map(id=>`<button data-phone-remove="${id}">${StudentAgeRecordLabels.html(id,personName(id))} ×</button>`).join('')}<button data-phone-add>＋ 添加人物</button></div><p class="helper">通话背景与本地背景分屏。另一端可添加多个人物；后续对话沿用通话，选择“挂电话”结束。本地站位沿用已有登场与高亮设置。位移、表情等在人物动作中编辑；这里不会更改说话人。</p><p class="helper">${!(current.roleIds||[]).length?'这句尚未设置说话人，原版不会启动电话。请先设置说话人，再预演通话。':''}</p><p role="status"></p><button data-phone-apply class="primary">应用</button></div>`;};
   d.onclick=async e=>{const b=e.target.closest('button');if(!b)return;try{if(b.hasAttribute('data-phone-cancel'))return end(null);if(b.hasAttribute('data-phone-bg')){const r=await UI.choices('对方所在背景',Object.values(backgrounds),{selected:background,table:'BgCfg',projectId});if(closed)return;if(r)background=Number(r.id);paint();}if(b.hasAttribute('data-phone-add')){const r=await UI.choices('电话另一端的人物',Object.values(people).filter(r=>!remote.has(Number(r.id))),{table:'PersonCfg',projectId});if(closed)return;if(r)remote.add(Number(r.id));paint();}if(b.dataset.phoneRemove!==undefined){remote.delete(Number(b.dataset.phoneRemove));paint();}if(b.hasAttribute('data-phone-apply')){if(!backgrounds[background]||!remote.size){d.querySelector('[role=status]').textContent='请选择有效背景和至少一位电话另一端人物。';return;}end({screenEffect:[4007,background,...remote]});}}catch(error){if(!closed)d.querySelector('[role=status]').textContent=error.message;}};
   d.oncancel=e=>{e.preventDefault();end(null);};paint();document.body.append(d);d.showModal();
  });
 }
 if(config.table){const data=await api('/api/table?'+new URLSearchParams({projectId,name:config.table}));const r=await UI.choices('选择'+config.label,Object.values(data.rows),{selected:value[1],table:config.table,projectId});return r?{screenEffect:[config.id,Number(r.id)]}:null;}
 if(config.value!==undefined)return new Promise(resolve=>{const d=document.createElement('dialog');d.className='character-picker';const end=v=>{d.close();d.remove();resolve(v);};d.innerHTML=`<header><h2>${esc(config.name)}</h2><button data-screen-cancel>取消</button></header><div class="character-picker-body"><label>${esc(config.label)}<input data-screen-value type="range" min="${config.min}" max="${config.max}" step="${config.step}" value="${value[1]??config.value}"><output>${value[1]??config.value}</output></label><button data-screen-apply class="primary">应用</button></div>`;d.oninput=e=>{if(e.target.matches('input'))d.querySelector('output').textContent=e.target.value;};d.onclick=e=>{if(e.target.closest('[data-screen-cancel]'))end(null);if(e.target.closest('[data-screen-apply]'))end({screenEffect:[config.id,Number(d.querySelector('input').value)]});};d.oncancel=e=>{e.preventDefault();end(null);};document.body.append(d);d.showModal();});
 return {screenEffect:[config.id]};
}

window.StudentAgeScreenEffects={entries,state,draw,duration,edit};})();
