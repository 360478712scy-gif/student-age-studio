/* 夜幕 · 剧场: the theatre's moving parts. Only active while this theme is chosen; all decoration is
   pointer-transparent and removed when another theme is picked. Motion runs on transform and opacity so the
   compositor carries it.
   - the house curtain gathers into the wings when the show starts and whenever the scene changes;
   - a follow spot glides after the pointer;
   - tickets and playbills lean toward the pointer, with a glare that follows it;
   - the story stage is dressed with its own drapes, valance, tie-backs and footlights (beside the stage element,
     so the editor's own stage animations and fullscreen preview are untouched), and they open on cue;
   - a newly selected script line is marked with a highlighter stroke;
   - saving is the curtain call: the footlights flare and roses are thrown. */
(()=>{'use strict';
const THEME='glass-noir';
const active=()=>document.documentElement.dataset.theme===THEME;
const calm=matchMedia('(prefers-reduced-motion: reduce)');
let house=null,curtain=null,spot=null,observer=null,view='',lastRaise=0,chasing=0,dressing=null,resize=null,selectedTalk=null,shownEvent=null;
const pointer={x:innerWidth/2,y:innerHeight/3},lamp={...pointer};

function build(){
 if(house)return;
 house=document.createElement('div');house.id='noir-house';house.setAttribute('aria-hidden','true');
 house.innerHTML='<div class="noir-beam noir-beam-l"></div><div class="noir-beam noir-beam-r"></div><div class="noir-spot"></div><div class="noir-dust"></div>';
 curtain=document.createElement('div');curtain.id='noir-curtain';curtain.setAttribute('aria-hidden','true');
 curtain.innerHTML='<div class="noir-curtain-dim"></div><div class="noir-curtain-glow"></div><div class="noir-curtain-half noir-curtain-l"></div><div class="noir-curtain-half noir-curtain-r"></div><div class="noir-curtain-valance"></div>';
 curtain.addEventListener('animationend',event=>{if(event.target.classList.contains('noir-curtain-dim'))curtain.classList.remove('noir-raise','noir-front');});
 document.body.append(house,curtain);spot=house.querySelector('.noir-spot');follow();
 observer=new MutationObserver(schedule);
 observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','class','open']});
 view='';schedule();
}
function teardown(){
 observer?.disconnect();observer=null;resize?.disconnect();resize=null;cancelAnimationFrame(chasing);chasing=0;
 for(const node of [house,curtain,dressing])node?.remove();house=curtain=spot=dressing=null;view='';selectedTalk=shownEvent=null;
 document.body.classList.remove('noir-flare');document.querySelectorAll('.noir-petals,.noir-ink').forEach(n=>n.classList.contains('noir-petals')?n.remove():n.classList.remove('noir-ink'));
}

// The follow spot eases toward the pointer every frame and rests once it arrives.
function follow(){
 chasing=0;if(!spot)return;
 lamp.x+=(pointer.x-lamp.x)*.12;lamp.y+=(pointer.y-lamp.y)*.12;
 spot.style.transform=`translate3d(${lamp.x.toFixed(1)}px,${lamp.y.toFixed(1)}px,0)`;
 if(Math.abs(pointer.x-lamp.x)+Math.abs(pointer.y-lamp.y)>.4)chasing=requestAnimationFrame(follow);
}
addEventListener('pointermove',event=>{
 pointer.x=event.clientX;pointer.y=event.clientY;
 if(spot&&!chasing&&!calm.matches)chasing=requestAnimationFrame(follow);
 tilt(event);
},{passive:true});

// Which scene is on stage: the fullscreen preview, help, the event programme, a workshop feature, or the story.
function scene(){
 if(document.body.classList.contains('story-fullscreen'))return 'preview';
 if(document.querySelector('#studio-help:not([hidden])'))return 'help';
 const events=document.querySelector('#story-events');if(events&&!events.hidden)return 'events';
 const workshop=document.querySelector('#workshop');
 if(workshop&&!workshop.hidden)return 'workshop:'+[...workshop.classList].filter(c=>c.startsWith('wk-')).sort().join('.')+':'+(document.querySelector('#wk-main>*')?.className||'');
 return 'story';
}
function raise(front){
 if(!curtain||calm.matches)return;
 const now=performance.now();if(now-lastRaise<700)return;lastRaise=now;
 curtain.classList.remove('noir-raise');curtain.classList.toggle('noir-front',!!front);void curtain.offsetWidth;curtain.classList.add('noir-raise');
}
let pending=0;
function schedule(){if(!pending)pending=requestAnimationFrame(check);}
function check(){
 pending=0;if(!active()||document.documentElement.hasAttribute('data-booting'))return;
 const next=scene();
 dressStage();
 if(next!==view){view=next;raise(next==='preview');if(next==='story')openStage(true);}
 const event=document.querySelector('#event-select')?.value??null;
 if(view==='story'&&shownEvent!==null&&event!==shownEvent)openStage(false);
 shownEvent=view==='story'?event:null;
 ink();playbill();
}

// The story stage's own dressing sits beside the stage element and follows its box.
function dressStage(){
 const stage=document.querySelector('#scene-panel>#large-scene');
 if(!stage){if(dressing){dressing.remove();dressing=null;resize?.disconnect();resize=null;}return;}
 if(dressing?.previousElementSibling!==stage){
  dressing?.remove();resize?.disconnect();
  dressing=document.createElement('div');dressing.className='noir-dressing';dressing.setAttribute('aria-hidden','true');
  dressing.innerHTML='<i class="noir-glow"></i><i class="noir-drape noir-drape-l"></i><i class="noir-drape noir-drape-r"></i><i class="noir-valance"></i><i class="noir-tie noir-tie-l"></i><i class="noir-tie noir-tie-r"></i><i class="noir-footlights"></i>';
  stage.after(dressing);
  resize=new ResizeObserver(place);resize.observe(stage);resize.observe(stage.parentElement);
 }
 place();
}
function place(){
 const stage=dressing?.previousElementSibling;if(!stage)return;
 const style=dressing.style;
 for(const [name,value] of [['top',stage.offsetTop],['left',stage.offsetLeft],['width',stage.offsetWidth],['height',stage.offsetHeight]])if(style[name]!==value+'px')style[name]=value+'px';
}
function openStage(afterCurtain){
 if(!dressing||calm.matches)return;
 dressing.style.setProperty('--noir-cue',afterCurtain?'.42s':'0s');
 dressing.classList.remove('noir-opening');void dressing.offsetWidth;dressing.classList.add('noir-opening');
}

// A newly selected script line gets a highlighter stroke; re-renders of the same line stay still.
function ink(){
 const card=document.querySelector('#talk-list .talk-card.selected'),id=card?.dataset.id??null;
 if(id===selectedTalk)return;
 const moved=selectedTalk!==null;selectedTalk=id;
 if(card&&moved&&!calm.matches)card.classList.add('noir-ink');
}

// The marquee names tonight's production: the mod being edited.
function playbill(){
 const heading=document.querySelector('#workshop.wk-home .wk-home-heading>div');if(!heading)return;
 const id=window.STUDIO_CURRENT_PROJECT?.(),project=(window.STUDIO_PROJECTS?.()||[]).find(p=>p.id===id);
 const name=project?.name||'';if(heading.dataset.noirShow!==name)heading.dataset.noirShow=name;
}

// Tickets and playbills lean toward the pointer; the glare follows it.
let tilted=null;
function tilt(event){
 if(!active()||calm.matches)return;
 const card=event.target instanceof Element?event.target.closest('#workshop.wk-home .wk-feature-card,#story-events .event-card'):null;
 if(tilted&&tilted!==card){for(const name of ['--noir-rx','--noir-ry','--noir-mx','--noir-my'])tilted.style.removeProperty(name);tilted.classList.remove('noir-tilt');tilted=null;}
 if(!card)return;
 const box=card.getBoundingClientRect(),x=(event.clientX-box.left)/box.width,y=(event.clientY-box.top)/box.height,lean=card.classList.contains('event-card')?.7:1;
 card.style.setProperty('--noir-rx',((.5-y)*10*lean).toFixed(2)+'deg');card.style.setProperty('--noir-ry',((x-.5)*12*lean).toFixed(2)+'deg');
 card.style.setProperty('--noir-mx',(x*100).toFixed(1)+'%');card.style.setProperty('--noir-my',(y*100).toFixed(1)+'%');
 card.classList.add('noir-tilt');tilted=card;
}

// Saving is the curtain call: the footlights flare and a handful of roses land on the stage.
function roses(){
 if(calm.matches)return;
 const shower=document.createElement('div');shower.className='noir-petals';shower.setAttribute('aria-hidden','true');
 for(let i=0;i<22;i++){
  const petal=document.createElement('i'),fall=2+Math.random()*1.4;
  petal.style.cssText=`--x:${(Math.random()*100).toFixed(1)}vw;--drift:${(Math.random()*180-90).toFixed(0)}px;--spin:${(Math.random()*720-360).toFixed(0)}deg;--size:${(10+Math.random()*10).toFixed(0)}px;--fall:${fall.toFixed(2)}s;--delay:${(Math.random()*.7).toFixed(2)}s`;
  shower.append(petal);
 }
 document.body.append(shower);setTimeout(()=>shower.remove(),4600);
}
addEventListener('click',event=>{
 if(!active())return;
 const save=event.target instanceof Element&&event.target.closest('[data-nav=save]');
 if(!save||save.disabled)return;
 document.body.classList.remove('noir-flare');void document.body.offsetWidth;document.body.classList.add('noir-flare');
 setTimeout(()=>document.body.classList.remove('noir-flare'),1700);
 roses();
},true);

function sync(){if(active())build();else teardown();}
addEventListener('studio-theme-change',sync);
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',sync);else sync();
})();
