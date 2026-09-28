/* 夜幕 · 剧场: the theatre's moving parts. Only active while this theme is chosen; all decoration is
   pointer-transparent and removed when another theme is picked.
   - the house curtain parts whenever the scene changes (a page, a workshop feature, the story stage);
   - a follow spot trails the pointer across the house;
   - tickets on the home page tilt toward the pointer with a sweep of gold foil;
   - the stage's own drapes open when the story editor comes on;
   - saving is the curtain call: the footlights flare and roses are thrown. */
(()=>{'use strict';
const THEME='glass-noir';
const active=()=>document.documentElement.dataset.theme===THEME;
const calm=matchMedia('(prefers-reduced-motion: reduce)');
let house=null,curtain=null,spot=null,observer=null,view='',lastRaise=0,frame=0,pointer=[innerWidth/2,innerHeight/3];

function build(){
 if(house)return;
 house=document.createElement('div');house.id='noir-house';house.setAttribute('aria-hidden','true');
 house.innerHTML='<div class="noir-beam noir-beam-l"></div><div class="noir-beam noir-beam-r"></div><div class="noir-spot"></div><div class="noir-dust"></div>';
 curtain=document.createElement('div');curtain.id='noir-curtain';curtain.setAttribute('aria-hidden','true');
 curtain.innerHTML='<div class="noir-curtain-half noir-curtain-l"></div><div class="noir-curtain-half noir-curtain-r"></div><div class="noir-curtain-valance"></div>';
 document.body.append(house,curtain);spot=house.querySelector('.noir-spot');aim();
 observer=new MutationObserver(schedule);
 observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','class','open']});
 view='';schedule();
}
function teardown(){
 observer?.disconnect();observer=null;house?.remove();curtain?.remove();house=curtain=spot=null;view='';
 document.body.classList.remove('noir-flare');document.querySelectorAll('.noir-petals').forEach(n=>n.remove());
}

// The follow spot moves with a transform, so the browser only recomposites a single layer.
function aim(){frame=0;if(spot)spot.style.transform=`translate3d(${pointer[0]}px,${pointer[1]}px,0)`;}
addEventListener('pointermove',event=>{
 pointer=[event.clientX,event.clientY];
 if(spot&&!frame)frame=requestAnimationFrame(aim);
 tilt(event);
},{passive:true});

// Which scene is on stage: help, the event programme, a workshop feature, or the story itself.
function scene(){
 if(document.querySelector('#studio-help:not([hidden])'))return 'help';
 const events=document.querySelector('#story-events');if(events&&!events.hidden)return 'events';
 const workshop=document.querySelector('#workshop');
 if(workshop&&!workshop.hidden)return 'workshop:'+[...workshop.classList].filter(c=>c.startsWith('wk-')).sort().join('.')+':'+(document.querySelector('#wk-main>*')?.className||'');
 return 'story';
}
function raise(){
 if(!curtain||calm.matches)return;
 const now=performance.now();if(now-lastRaise<700)return;lastRaise=now;
 curtain.classList.remove('noir-raise');void curtain.offsetWidth;curtain.classList.add('noir-raise');
}
function openStage(){
 const stage=document.querySelector('#large-scene');if(!stage||calm.matches)return;
 stage.classList.remove('noir-opening');void stage.offsetWidth;stage.classList.add('noir-opening');
}
let pending=0;
function schedule(){if(!pending)pending=requestAnimationFrame(check);}
function check(){
 pending=0;if(!active()||document.documentElement.hasAttribute('data-booting'))return;
 const next=scene();
 if(next!==view){const first=!view;view=next;if(!first)raise();if(next==='story')setTimeout(openStage,first?0:380);}
 playbill();
}
// The marquee names tonight's production: the mod being edited.
function playbill(){
 const heading=document.querySelector('#workshop.wk-home .wk-home-heading>div');if(!heading)return;
 const id=window.STUDIO_CURRENT_PROJECT?.(),project=(window.STUDIO_PROJECTS?.()||[]).find(p=>p.id===id);
 const name=project?.name||'';if(heading.dataset.noirShow!==name)heading.dataset.noirShow=name;
}

// Tickets lean toward the pointer; the foil highlight follows it.
let tilted=null;
function tilt(event){
 if(!active()||calm.matches)return;
 const card=event.target instanceof Element?event.target.closest('#workshop.wk-home .wk-feature-card'):null;
 if(tilted&&tilted!==card){for(const name of ['--noir-rx','--noir-ry','--noir-mx','--noir-my'])tilted.style.removeProperty(name);tilted.classList.remove('noir-tilt');tilted=null;}
 if(!card)return;
 const box=card.getBoundingClientRect(),x=(event.clientX-box.left)/box.width,y=(event.clientY-box.top)/box.height;
 card.style.setProperty('--noir-rx',((.5-y)*10).toFixed(2)+'deg');card.style.setProperty('--noir-ry',((x-.5)*12).toFixed(2)+'deg');
 card.style.setProperty('--noir-mx',(x*100).toFixed(1)+'%');card.style.setProperty('--noir-my',(y*100).toFixed(1)+'%');
 card.classList.add('noir-tilt');tilted=card;
}

// Saving is the curtain call: the footlights flare and a handful of roses land on the stage.
function roses(){
 if(calm.matches)return;
 const shower=document.createElement('div');shower.className='noir-petals';shower.setAttribute('aria-hidden','true');
 for(let i=0;i<18;i++){
  const petal=document.createElement('i');
  petal.style.cssText=`--x:${(Math.random()*100).toFixed(1)}vw;--drift:${(Math.random()*160-80).toFixed(0)}px;--spin:${(Math.random()*720-360).toFixed(0)}deg;--size:${(10+Math.random()*10).toFixed(0)}px;animation-delay:${(Math.random()*.6).toFixed(2)}s;animation-duration:${(1.8+Math.random()*1.2).toFixed(2)}s`;
  shower.append(petal);
 }
 document.body.append(shower);setTimeout(()=>shower.remove(),3800);
}
addEventListener('click',event=>{
 if(!active())return;
 const save=event.target instanceof Element&&event.target.closest('[data-nav=save]');
 if(!save||save.disabled)return;
 document.body.classList.remove('noir-flare');void document.body.offsetWidth;document.body.classList.add('noir-flare');
 setTimeout(()=>document.body.classList.remove('noir-flare'),1600);
 roses();
},true);

function sync(){if(active())build();else teardown();}
addEventListener('studio-theme-change',sync);
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',sync);else sync();
})();
