(()=>{'use strict';
const token=window.STUDIO_TOKEN,esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths={play:'m9 5 11 7-11 7Z',pause:'M8 5v14M16 5v14',next:'m5 5 10 7-10 7ZM19 5v14',previous:'m19 5-10 7 10 7ZM5 5v14',list:'m17 2 4 4-4 4M3 11V8a2 2 0 0 1 2-2h16M7 22l-4-4 4-4m14-1v3a2 2 0 0 1-2 2H3',single:'m17 2 4 4-4 4M3 11V8a2 2 0 0 1 2-2h16M7 22l-4-4 4-4m14-1v3a2 2 0 0 1-2 2H3M10 10l2-1v6',shuffle:'m17 3 4 4-4 4M3 17l4 0 10-10h4M3 7h4l3 3m4 4 3 3h4m-4-4 4 4-4 4',collapse:'m14 5-7 7 7 7',expand:'m9 5 7 7-7 7'};
const icon=k=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[k]}"/></svg>`;
let state={tracks:[],preferences:{mode:'list',collapsed:false,volume:.35}},index=0,open=false,loaded=false,loading=null,notice='',queue=[],epoch=0,prefTimer,importing=false;
const audio=new Audio();audio.preload='none';
const host=document.createElement('section');host.id='editor-music';host.setAttribute('aria-label','编辑器音乐播放器');document.body.append(host);
let wantsPlayback=true,gesturePending=false,leaving=false,resumeTimer;
const foreground=new Set(),mediaActive=new Map(),tracked=new WeakSet();
const interrupted=()=>foreground.size>0||mediaActive.size>0;
function focusChanged(){clearTimeout(resumeTimer);if(interrupted()){audio.pause();render();}else if(wantsPlayback&&!leaving)resumeTimer=setTimeout(resume,120);}
function setFocus(key,active){const before=foreground.has(key);if(active)foreground.add(key);else foreground.delete(key);if(before!==active)focusChanged();}
function mediaState(media){if(media===audio)return;const active=!media.paused&&!media.ended&&!media.error,before=mediaActive.has(media);if(active)mediaActive.set(media,media.isConnected);else mediaActive.delete(media);if(before!==active)focusChanged();}
function trackMedia(media){if(!media?.addEventListener||media===audio||tracked.has(media))return media;tracked.add(media);for(const name of ['play','playing','pause','ended','error','emptied','abort'])media.addEventListener(name,()=>mediaState(media));mediaState(media);return media;}
for(const name of ['play','playing','pause','ended','error','emptied','abort'])document.addEventListener(name,e=>{if(e.target instanceof HTMLMediaElement){trackMedia(e.target);mediaState(e.target);}},true);
const removals=new MutationObserver(()=>{for(const [media,attached] of mediaActive)if(attached&&!media.isConnected){media.pause();mediaActive.delete(media);focusChanged();}});
removals.observe(document.body,{childList:true,subtree:true});
async function resume(){
 if(!loaded||!wantsPlayback||leaving||interrupted())return;
 if(!audio.src){const first=state.tracks.findIndex(t=>t.local||t.assetPath&&window.STUDIO_CURRENT_PROJECT?.());if(first<0)return;return select(first);}
 try{await audio.play();gesturePending=false;notice='';}catch(e){if(e.name==='NotAllowedError'){gesturePending=true;notice='点击编辑器后开始播放背景音乐。';}else if(e.name!=='AbortError'){notice='音乐暂时无法播放，请检查本地文件。';}}render();
}
function retryGesture(e){if(gesturePending&&!host.contains(e.target)&&wantsPlayback&&!interrupted())resume();}
document.addEventListener('pointerdown',retryGesture);document.addEventListener('keydown',retryGesture);
window.StudentAgeAudioFocus={track:trackMedia,set:setFocus,hold(){const key=Symbol('preview');setFocus(key,true);return()=>setFocus(key,false);}};

async function api(data){const r=await fetch('/api/editor-music',{method:data?'POST':'GET',headers:{'X-Studio-Token':token,...(data?{'Content-Type':'application/json'}:{})},body:data?JSON.stringify(data):undefined});const v=await r.json();if(!r.ok)throw Error(v.error||'音乐读取失败');return v;}
function persist(){clearTimeout(prefTimer);prefTimer=setTimeout(()=>api(state.preferences).catch(e=>{notice=e.message;render();}),200);}
function render(){const showPause=wantsPlayback&&(!gesturePending||interrupted());const t=state.tracks[index]||{name:'遠い空へ',artist:'市川淳'},p=state.preferences;host.classList.toggle('collapsed',p.collapsed);host.classList.toggle('playing',!audio.paused);host.innerHTML=`<div class="music-card"><button data-music="play" class="vinyl" aria-label="${showPause?'暂停':'播放'}"><span class="record-face"><span class="record-label">♪</span></span></button><div class="music-details"><button class="music-title" data-music="playlist" aria-expanded="${open}">${esc(t.name)}</button><small>${esc(interrupted()&&wantsPlayback?'预览或试听中 · 背景音乐暂停':t.artist)}</small><div class="music-controls">${[['previous','上一首'],[showPause?'pause':'play',showPause?'暂停':'播放'],['next','下一首'],[p.mode,({single:'单曲循环',list:'列表循环',shuffle:'随机播放'})[p.mode]]].map(([key,label])=>`<button data-music="${key==='pause'?'play':key}" title="${label}" aria-label="${label}">${icon(key)}</button>`).join('')}<input data-volume type="range" min="0" max="1" step="0.01" value="${p.volume}" aria-label="音量"></div></div></div><button class="music-handle" data-music="collapse" title="${p.collapsed?'展开播放器':'收起播放器'}" aria-label="${p.collapsed?'展开播放器':'收起播放器'}">${icon(p.collapsed?'expand':'collapse')}</button>${open&&!p.collapsed?`<div class="music-list"><header><strong>播放列表</strong><button data-music="playlist" aria-label="关闭播放列表">×</button></header>${state.tracks.map((r,i)=>`<button data-track="${i}" aria-pressed="${i===index}">${r.local||r.id==='tooi-sora'?'':'['+esc(r.id)+'] '}${esc(r.name)}${r.id==='tooi-sora'&&!r.local?' · 导入本地音乐':''}</button>`).join('')}<label class="music-import music-import-local">＋ 导入本地音乐<input type="file" accept=".mp3,.ogg,.wav,.m4a,.flac" multiple data-import="local" ${importing?'disabled':''}></label><details class="music-special-import"><summary>导入指定曲目</summary><label class="music-import">导入「遠い空へ」<input type="file" accept=".mp3,.ogg,.wav,.m4a,.flac" data-import="tooi-sora"></label><label class="music-import">导入「踊り子」<input type="file" accept=".mp3,.ogg,.wav,.m4a,.flac" data-import="odoriko"></label></details></div>`:''}${notice?`<p role="status" class="music-notice">${esc(notice)}</p>`:''}`;}
async function load(){if(loading)return loading;loading=api().then(v=>{const current=state.tracks[index]?.id;state=v;index=Math.max(0,state.tracks.findIndex(t=>t.id===current));queue=[];audio.volume=v.preferences.volume;const firstLoad=!loaded;loaded=true;render();if(firstLoad)resume();}).catch(e=>{notice=e.message;render();}).finally(()=>loading=null);return loading;}
async function select(i,play=true){wantsPlayback=play;index=i;const t=state.tracks[index];if(!t)return;const turn=++epoch;audio.pause();audio.removeAttribute('src');audio.load();notice='';if(t.id==='tooi-sora'&&!t.local){notice='请导入本地「遠い空へ」音频后播放。';open=true;render();return;}const projectId=window.STUDIO_CURRENT_PROJECT?.();if(t.assetPath&&!projectId){notice='打开模组后可播放原版空间音乐。';render();return;}audio.src=!t.assetPath?'/api/editor-music-file?'+new URLSearchParams({id:t.id,token}):'/api/social-image?'+new URLSearchParams({projectId,path:t.assetPath,token});render();if(play)await resume();}

function next(direction=1){const playable=state.tracks.map((t,i)=>i).filter(i=>state.tracks[i].id!=='tooi-sora'||state.tracks[i].local);if(!playable.length)return null;if(state.preferences.mode==='shuffle'&&direction>0){queue=queue.filter(i=>playable.includes(i)&&i!==index);if(!queue.length){queue=playable.filter(i=>i!==index);for(let i=queue.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[queue[i],queue[j]]=[queue[j],queue[i]];}}return queue.pop()??playable[0];}const pos=playable.indexOf(index);return playable[(pos+direction+playable.length)%playable.length];}
function step(direction){const i=next(direction);if(i!==null)select(i);}
audio.onended=()=>{if(state.preferences.mode==='single'){audio.currentTime=0;resume();}else step(1);};audio.onplay=()=>{if(interrupted()||!wantsPlayback||leaving)audio.pause();render();};audio.onpause=render;audio.onerror=()=>{notice='音乐读取失败；可检查缓存或重新导入。';render();};
host.onclick=async e=>{const b=e.target.closest('button');if(!b)return;if(!loaded)await load();if(b.dataset.track!==undefined){queue=[];return select(Number(b.dataset.track));}switch(b.dataset.music){case 'play':if(gesturePending&&wantsPlayback&&!interrupted()){await resume();break;}wantsPlayback=!wantsPlayback;if(wantsPlayback)await resume();else{gesturePending=false;audio.pause();render();}break;case 'next':step(1);break;case 'previous':step(-1);break;case 'playlist':open=!open;render();break;case 'collapse':state.preferences.collapsed=!state.preferences.collapsed;open=false;notice='';persist();render();break;case 'single':case 'list':case 'shuffle':state.preferences.mode=({list:'single',single:'shuffle',shuffle:'list'})[state.preferences.mode];queue=[];persist();render();break;}};
host.oninput=e=>{if(e.target.matches('[data-volume]')){audio.volume=Number(e.target.value);state.preferences.volume=audio.volume;persist();}};
host.onchange=async e=>{
 if(!e.target.matches('[data-import]')||importing)return;
 const trackId=e.target.dataset.import,files=[...e.target.files];if(!files.length)return;
 importing=true;let count=0;const failures=[];
 try{for(const f of files){
  notice=`正在导入 ${f.name}…`;render();
  try{
   if(f.size>40*1024*1024)throw Error('文件超过 40 MB');
   const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=()=>reject(Error('文件读取失败'));r.readAsDataURL(f);});
   const result=await api({fileName:f.name,data,trackId}),current=state.tracks[index]?.id,preferences=state.preferences;
   state={...result,preferences};index=Math.max(0,state.tracks.findIndex(t=>t.id===current));queue=[];count++;
   if(current===trackId&&audio.src){await select(index,wantsPlayback);}
  }catch(err){failures.push(f.name+'：'+err.message);}
 }}finally{importing=false;notice=`已导入 ${count} 首音乐。`+(failures.length?' '+failures.join('；'):'');render();}
};
document.addEventListener('pointerdown',e=>{if(open&&!host.contains(e.target)){open=false;render();}});
window.addEventListener('pagehide',()=>{leaving=true;wantsPlayback=false;clearTimeout(resumeTimer);clearTimeout(prefTimer);removals.disconnect();foreground.clear();mediaActive.clear();audio.pause();audio.removeAttribute('src');audio.load();});render();load();
window.StudentAgeEditorMusic={getState:()=>({index,mode:state.preferences.mode,tracks:state.tracks,collapsed:state.preferences.collapsed,interrupted:interrupted(),wantsPlayback}),next,audio,refresh:load};
})();
