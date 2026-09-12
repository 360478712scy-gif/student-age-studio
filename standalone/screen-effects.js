/* Native TalkCfg.screenEffect; the game accepts one screen command per line. */
(()=>{'use strict';
const entries=[
 {id:4001,name:'屏幕抖动',value:.15,label:'持续秒数',min:.01,max:5,step:.01},
 {id:4002,name:'背景模糊'},{id:4003,name:'清除背景效果'},
 {id:4004,name:'展示物品',table:'ItemCfg',label:'物品'},
 {id:4006,name:'稍后转场'}, {id:4009,name:'旧照片色调'},{id:4010,name:'背景反色'},
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
window.StudentAgeScreenEffects={entries,state,draw,duration};})();
