/* Shared WebGL optical material for editor chrome. The texture is the editor's
   wallpaper, not a stale screenshot of editable data. Native previews are excluded.
   Rendering is invalidation-driven: no idle RAF loop and only one GPU context. */
(()=>{'use strict';
// The atelier theme is flat paper: no optical renderer.
const enabled=()=>window.STUDIO_THEME!=='classic'&&window.STUDIO_THEME!=='glass-atelier'&&window.STUDIO_GLASS_MATERIAL!=='frosted';
function start(){if(!enabled()||window.STUDIO_GLASS)return;
const reduce=matchMedia('(prefers-reduced-motion: reduce)'),opaque=matchMedia('(prefers-reduced-transparency: reduce)');
const source=document.createElement('canvas'),ink=source.getContext('2d'),gpu=document.createElement('canvas');
const gl=gpu.getContext('webgl',{alpha:true,premultipliedAlpha:false,antialias:false,preserveDrawingBuffer:true,powerPreference:'low-power'});
const stats={renderer:'fallback',panes:0,draws:0,frames:0,lastDrawMs:0,texture:'editor-wallpaper'};window.STUDIO_GLASS={stats};
if(!gl)return;
const vs=`attribute vec2 a;varying vec2 uv;void main(){uv=a*.5+.5;gl_Position=vec4(a,0.,1.);}`;
const fs=`precision mediump float;
varying vec2 uv;uniform sampler2D tex;uniform vec2 size,origin,screen,light;uniform vec4 radii;uniform float edge,hover;uniform vec3 material;uniform float shine,layer,selected;uniform vec3 accent;
float sd(vec2 p){float radius=p.y<0.?(p.x<0.?radii.x:radii.y):(p.x<0.?radii.w:radii.z);vec2 q=abs(p)-(size*.5-vec2(radius));return length(max(q,0.))+min(max(q.x,q.y),0.)-radius;}
vec3 sampleAt(vec2 p){return texture2D(tex,clamp(p/screen,vec2(.001),vec2(.999))).rgb;}
void main(){vec2 p=vec2(uv.x,1.-uv.y)*size;vec2 c=p-size*.5;float d=sd(c);if(d>edge)discard;
float bevel=min(22.,min(size.x,size.y)*.29);float depth=clamp(-d/bevel,0.,1.);
vec2 n=normalize(vec2(sd(c+vec2(.65,0.))-sd(c-vec2(.65,0.)),sd(c+vec2(0.,.65))-sd(c-vec2(0.,.65)))+vec2(.0001));
float bend=pow(1.-depth,2.)*(bevel*1.05);vec2 point=origin+p-n*bend+c*.025;
vec2 dispersion=n*pow(1.-depth,3.)*1.6;
vec3 col=vec3(sampleAt(point+dispersion).r,sampleAt(point).g,sampleAt(point-dispersion).b);
col=mix(col,material,min(.82,.34+layer*.16));col=mix(col,accent,selected*.72);
float rim=exp(-abs(d+1.2)*1.8);vec2 lighting=normalize(light-p+vec2(.001));
float spec=pow(max(0.,dot(n,lighting)),5.)*pow(1.-depth,2.);
col+=(vec3(.20)*rim+vec3(.32,.35,.4)*spec*(.7+hover*.5))*shine;
col-=vec3(.12,.10,.07)*pow(max(0.,dot(n,-lighting)),3.)*pow(1.-depth,2.);
float gleam=exp(-pow((p.x/size.x+p.y/size.y-0.45-hover*.12)*3.,2.))*.055;
col+=gleam*shine;gl_FragColor=vec4(col,1.-smoothstep(-edge,edge,d));}`;
function shader(type,src){const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
let program;try{program=gl.createProgram();const v=shader(gl.VERTEX_SHADER,vs),f=shader(gl.FRAGMENT_SHADER,fs);gl.attachShader(program,v);gl.attachShader(program,f);gl.linkProgram(program);gl.deleteShader(v);gl.deleteShader(f);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));}catch(e){stats.error=String(e);return;}
gl.useProgram(program);const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);const attr=gl.getAttribLocation(program,'a');gl.enableVertexAttribArray(attr);gl.vertexAttribPointer(attr,2,gl.FLOAT,false,0,0);
const uni=Object.fromEntries(['size','origin','screen','light','radii','edge','hover','material','shine','layer','selected','accent'].map(n=>[n,gl.getUniformLocation(program,n)]));
const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
let width=0,height=0,raf=0,scanTimer=0,scrollTimer=0,pointerTimer=0,scrolling=false,allDirty=true,lost=false;
const panes=new Map();
function wallpaper(){width=innerWidth;height=innerHeight;source.width=width;source.height=height;
const tone=window.STUDIO_THEME;const dusk=tone==='glass-dusk',moon=tone==='glass-moon';
const g=ink.createLinearGradient(0,0,width,height);g.addColorStop(0,dusk?'#332238':moon?'#0b1429':'#c9def4');g.addColorStop(.45,dusk?'#67465e':moon?'#243556':'#d5e1f0');g.addColorStop(1,dusk?'#bd806c':moon?'#424268':'#e8d3e1');ink.fillStyle=g;ink.fillRect(0,0,width,height);
// Broad satin folds provide a recognisable continuous scene on both sides of the lens.
for(const [y,colour] of (dusk?[[.18,'#674668'],[.46,'#9e6978'],[.82,'#42314d']]:moon?[[.18,'#192b49'],[.46,'#344b69'],[.82,'#252b48']]:[[.18,'#72abd9'],[.46,'#a1bce5'],[.82,'#b5a3d2']])){
 const grad=ink.createLinearGradient(0,height*(y-.3),width,height*(y+.5));grad.addColorStop(0,dusk?'#dca99a88':moon?'#869bc444':'#ffffffbb');grad.addColorStop(.24,colour);grad.addColorStop(.6,dusk?'#4c354b':moon?'#111c33':'#edf5fc');grad.addColorStop(1,colour);
 ink.beginPath();ink.moveTo(-80,height*y);ink.bezierCurveTo(width*.3,height*(y+.58),width*.62,height*(y-.55),width+80,height*(y+.12));ink.lineTo(width+80,height+50);ink.lineTo(-80,height+50);ink.closePath();ink.fillStyle=grad;ink.fill();
 ink.beginPath();ink.moveTo(-80,height*y);ink.bezierCurveTo(width*.3,height*(y+.58),width*.62,height*(y-.55),width+80,height*(y+.12));ink.strokeStyle=dusk?'#dcb5ba44':moon?'#a4b9e333':'#ffffff70';ink.lineWidth=1.4;ink.stroke();
}
document.documentElement.style.setProperty('--liquid-wallpaper',`url("${source.toDataURL('image/png')}")`);
gl.bindTexture(gl.TEXTURE_2D,texture);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,source);
const scale=Math.min(devicePixelRatio||1,1.5);gpu.width=Math.min(2048,Math.ceil(width*scale));gpu.height=Math.min(1536,Math.ceil(height*scale));allDirty=true;
}
const targets='button,#studio-toolbar,.wk-feature-card,.wk-rows,.guide-shell,.guide-folder,.guide-preference,.guide-toolbar-map article,.guide-contacts>div,.cache-upgrade,dialog[open],#studio-corner-tools button,.toast:not([hidden]),.character-list-panel,.character-content,.social-list,.social-settings-card,.space-list,.space-form,.messages-sidebar,.messages-settings,.goal-list,.goal-settings,.ap-preview,dialog[open] .location-section,dialog[open] .workshop-settings-tabs,dialog[open] .condition-browser-catalog,dialog[open] .condition-browser-selected,dialog[open] .event-parameter-panel,dialog[open] .ap-folder,dialog[open] .ap-card,dialog[open] .condition-library-entry,dialog[open] .character-choice-grid>button,dialog[open] .minigame-detail,dialog[open] .minigame-list,dialog[open] .wk-command,dialog[open] .wk-array,dialog[open] .warehouse-command-grid>section';
const native='#editor-music,.story-scene,#story-history,#scene-modal,.goal-native-canvas,.message-native-phone,.social-feed-card,#space-preview,.model-art,.goal-preview-zoom,.messages-preview-dialog';
const ro=new ResizeObserver(()=>request());
function discover(){scanTimer=0;if(lost||!enabled())return;for(const [el,p]of panes){if(!el.isConnected||!el.matches(targets)){ro.unobserve(el);p.canvas.remove();el.classList.remove('liquid-pane','liquid-relative','liquid-ready');panes.delete(el);}else if(p.canvas.parentElement!==el){el.append(p.canvas);p.key='';}}
// Read styles together before attaching canvases: alternating reads and writes
// forces a complete layout for every button in a large list.
const additions=[...document.querySelectorAll(targets)].filter(el=>!panes.has(el)&&!el.closest(native)&&el.id!=='studio-cache-details'&&el.id!=='studio-cache-progress').map(el=>[el,getComputedStyle(el).position]);
for(const [el,position] of additions){const canvas=document.createElement('canvas');canvas.width=1;canvas.height=1;canvas.className='liquid-optics';canvas.setAttribute('aria-hidden','true');if(position==='static')el.classList.add('liquid-relative');el.classList.add('liquid-pane');el.append(canvas);panes.set(el,{canvas,ctx:null,key:'',light:[-100,-100],hover:0});ro.observe(el);}
stats.panes=panes.size;request();}
function request(){if(enabled()&&!raf&&!document.hidden&&!opaque.matches&&!lost)raf=requestAnimationFrame(draw);}
// A pane that scrolls carries its glass along; the glass must never reach past the real content,
// otherwise it would extend the scroll range and the pane could be scrolled into empty glass.
function placeCanvas(el,canvas){canvas.style.transform='none';const x=Math.min(el.scrollLeft,Math.max(0,el.scrollWidth-el.clientWidth)),y=Math.min(el.scrollTop,Math.max(0,el.scrollHeight-el.clientHeight));canvas.style.transform=x||y?`translate(${x}px,${y}px)`:'';}
// Decoration can update at 30 Hz; editor input and native previews are independent.
function pointerRequest(){if(!pointerTimer)pointerTimer=setTimeout(()=>{pointerTimer=0;request();},33);}
function draw(){raf=0;if(lost||opaque.matches||!enabled())return;const start=performance.now();if(width!==innerWidth||height!==innerHeight)wallpaper();gl.useProgram(program);gl.bindTexture(gl.TEXTURE_2D,texture);gl.uniform2f(uni.screen,width,height);const tone=window.STUDIO_THEME,dark=tone==='glass-dusk'||tone==='glass-moon';gl.uniform3f(uni.material,...(tone==='glass-dusk'?[.12,.08,.17]:tone==='glass-moon'?[.025,.045,.10]:[.98,.99,1.]));gl.uniform1f(uni.shine,dark?.32:1.);
for(const [el,p]of panes){const r=el.getBoundingClientRect();if(!r.width||!r.height||r.bottom<0||r.top>height||r.right<0||r.left>width||getComputedStyle(el).visibility==='hidden'){if(p.canvas.width>1){p.canvas.width=1;p.canvas.height=1;p.key='';el.classList.remove('liquid-ready');}continue;}
if(el.scrollTop||el.scrollLeft||p.canvas.style.transform)placeCanvas(el,p.canvas);
if(scrolling&&p.key&&p.canvas.width>1)continue;
const style=getComputedStyle(el),radii=['borderTopLeftRadius','borderTopRightRadius','borderBottomRightRadius','borderBottomLeftRadius'].map(k=>{const v=style[k];return Math.min(r.width/2,r.height/2,v.includes('%')?Math.min(r.width,r.height)*parseFloat(v)/100:parseFloat(v)||0);});
const depth=Math.min(3,(()=>{let n=el.parentElement,d=0;while(n){if(panes.has(n))d++;n=n.parentElement;}return d;})());const selected=el.matches('button.primary,[data-nav=save],button.active,button[aria-pressed=true],button[aria-checked=true],button[aria-selected=true]')?1:0;
const key=[r.x,r.y,r.width,r.height,radii,depth,selected,p.light,p.hover,width,height].join('|');if(p.key===key&&!allDirty)continue;
const scale=Math.min(el.tagName==='BUTTON'?2:1.25,devicePixelRatio||1,1024/r.width,768/r.height),w=Math.max(1,Math.ceil(r.width*scale)),h=Math.max(1,Math.ceil(r.height*scale));
if(p.canvas.width!==w||p.canvas.height!==h){p.canvas.width=w;p.canvas.height=h;}
gl.viewport(0,0,w,h);gl.enable(gl.SCISSOR_TEST);gl.scissor(0,0,w,h);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
gl.uniform1f(uni.layer,depth);gl.uniform1f(uni.selected,selected);gl.uniform3f(uni.accent,...(tone==='glass-dusk'?[.42,.22,.65]:tone==='glass-moon'?[.12,.32,.58]:[.03,.36,.76]));gl.uniform3f(uni.material,...(depth>0?(tone==='glass-dusk'?[.39,.30,.45]:tone==='glass-moon'?[.22,.31,.44]:[1.,1.,1.]):(tone==='glass-dusk'?[.12,.08,.17]:tone==='glass-moon'?[.025,.045,.10]:[.98,.99,1.])));
gl.uniform2f(uni.size,r.width,r.height);gl.uniform2f(uni.origin,r.left,r.top);gl.uniform2f(uni.light,p.light[0],p.light[1]);gl.uniform4f(uni.radii,...radii);gl.uniform1f(uni.edge,.8/scale);gl.uniform1f(uni.hover,p.hover);gl.drawArrays(gl.TRIANGLES,0,6);
p.ctx??=p.canvas.getContext('2d');p.ctx.clearRect(0,0,w,h);p.ctx.drawImage(gpu,0,gpu.height-h,w,h,0,0,w,h);p.key=key;el.classList.add('liquid-ready');stats.draws++;}
allDirty=false;stats.frames++;stats.lastDrawMs=Math.round((performance.now()-start)*10)/10;
}
function scheduleScan(records){if(!enabled())return;
// Text/HTML replacement must not leave an already-painted control bare until the delayed scan.
if(records)for(const record of records){const el=record.target,p=panes.get(el);if(p&&el.isConnected&&p.canvas.parentElement!==el){el.append(p.canvas);request();}}
if(records&&records.every(r=>r.type==='childList'&&[...r.addedNodes,...r.removedNodes].every(n=>n.nodeType!==1||n.matches?.('.liquid-optics'))))return;
// Coalesce a batch of DOM updates before the next paint. Repeated synchronous
// scans inside mutation delivery can otherwise block input for an entire list.
if(!scanTimer)scanTimer=requestAnimationFrame(()=>{scanTimer=0;discover();});}
const mutations=new MutationObserver(scheduleScan);mutations.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open','hidden']});
document.addEventListener('pointermove',e=>{if(!enabled()||reduce.matches||opaque.matches||e.buttons)return;const el=e.target.closest?.('.liquid-pane'),p=panes.get(el);if(!p)return;const r=el.getBoundingClientRect();p.light=[e.clientX-r.left,e.clientY-r.top];p.hover=1;pointerRequest();},{passive:true});
document.addEventListener('pointerout',e=>{if(!enabled())return;const el=e.target.closest?.('.liquid-pane'),p=panes.get(el);if(p&&!el.contains(e.relatedTarget)){p.light=[-100,-100];p.hover=0;pointerRequest();}},{passive:true});
document.addEventListener('click',()=>setTimeout(request,0),{passive:true});
document.addEventListener('transitionend',request,{capture:true});document.addEventListener('animationend',request,{capture:true});
// Reuse composed glass while scrolling; resample its wallpaper once scrolling settles.
document.addEventListener('scroll',e=>{if(!enabled())return;scrolling=true;const p=panes.get(e.target);if(p)placeCanvas(e.target,p.canvas);request();clearTimeout(scrollTimer);scrollTimer=setTimeout(()=>{scrolling=false;request();},100);},{capture:true,passive:true});window.addEventListener('resize',request,{passive:true});document.addEventListener('visibilitychange',()=>{if(document.hidden&&raf){cancelAnimationFrame(raf);raf=0;}else request();});opaque.addEventListener('change',()=>{document.documentElement.classList.toggle('liquid-gpu',!opaque.matches&&enabled());request();});
gpu.addEventListener('webglcontextlost',e=>{e.preventDefault();lost=true;document.documentElement.classList.remove('liquid-gpu');stats.renderer='context-lost fallback';if(raf)cancelAnimationFrame(raf);raf=0;});
// The controls remain fully usable after a GPU reset; a subsequent app launch retries GPU setup.
window.addEventListener('pagehide',()=>{if(raf)cancelAnimationFrame(raf);cancelAnimationFrame(scanTimer);clearTimeout(scrollTimer);clearTimeout(pointerTimer);ro.disconnect();gl.deleteTexture(texture);gl.deleteBuffer(buffer);gl.deleteProgram(program);},{once:true});
window.addEventListener('studio-theme-change',()=>{const active=enabled();document.documentElement.classList.toggle('liquid-gpu',active&&!opaque.matches&&!lost);if(!active){mutations.disconnect();ro.disconnect();cancelAnimationFrame(scanTimer);clearTimeout(scrollTimer);clearTimeout(pointerTimer);scanTimer=scrollTimer=pointerTimer=0;if(raf)cancelAnimationFrame(raf);raf=0;for(const [el,p]of panes){p.canvas.width=1;p.canvas.height=1;p.key='';el.classList.remove('liquid-ready');}gpu.width=1;gpu.height=1;source.width=1;source.height=1;gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,null);width=0;height=0;for(const [el,p]of panes){p.canvas.remove();el.classList.remove('liquid-pane','liquid-relative','liquid-ready');}panes.clear();stats.panes=0;document.documentElement.style.removeProperty('--liquid-wallpaper');stats.renderer=window.STUDIO_GLASS_MATERIAL==='frosted'?'frosted (paused)':'classic (paused)';}else{mutations.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open','hidden']});stats.renderer=lost?'context-lost fallback':'WebGL';width=0;height=0;allDirty=true;discover();}});
stats.renderer='WebGL';if(!opaque.matches)document.documentElement.classList.add('liquid-gpu');wallpaper();discover();
}
window.addEventListener('studio-theme-change',start);start();
})();
