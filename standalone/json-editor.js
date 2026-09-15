'use strict';
/* Raw JSON source viewer/editor for the current mod. A corner button on every
   editor page opens it; syntax errors are located in the user's own text,
   safe missing-comma errors can be repaired in one click, edits are undoable. */
(()=>{
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const injected=window.STUDIO_TOKEN,fragment=location.hash.slice(1);
const token=injected&&injected!=='__STUDIO_TOKEN__'?injected:(fragment.startsWith('token=')?fragment.slice(6):fragment);
async function api(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Studio-Token':token},body:body?JSON.stringify(body):undefined});const data=await response.json().catch(()=>({}));if(!response.ok){const error=new Error(data.error||'请求失败');error.code=data.code;throw error;}return data;}
const LINE=20,LIVE_LIMIT=2*1024*1024,HINTS={space:'KZoneProfileCfg.json',messages:'PhoneMsgCfg.json',social:'KZoneContentCfg.json',characters:'PersonCfg.json',audio:'AudioCfg.json',goals:'IntentCfg.json',manifest:'manifest.json','idle-chats':'InteractCfg.json'};
let corner=null,bug=null,dialog=null,state=null,lastFile='',timer=null;
// Long lines always wrap visually; the text keeps its real line breaks.
const wrapLines=true;
const drafts=new Map();let syncDrawer=null,closeDrawer=null,opening=false,locateInDrawer=null;
function layout(){const top=document.querySelector('#studio-toolbar')?.getBoundingClientRect().bottom||0;document.body.style.setProperty('--json-drawer-top',Math.max(0,top)+'px');}
function provider(name,disk){const wk=window.STUDIO_WORKSHOP_NAV;if(wk?.isOpen?.()&&wk.jsonRead?.(name,disk)!=null)return {read:()=>wk.jsonRead(name,disk),write:rows=>wk.jsonWrite(name,rows,disk),saved:(rows,rev)=>wk.jsonSaved(name,rows,rev)};const story=window.STUDIO_STORY_JSON;if(!wk?.isOpen?.()&&story?.read(name,disk)!=null)return {read:()=>story.read(name,disk),write:rows=>story.write(name,rows,disk),saved:(rows,rev)=>story.saved(name,rows,rev)};return null;}
const table=path=>path.split('/').pop().replace(/\.json$/i,'');
function mergeDraft(base,next,current){if(JSON.stringify(base)===JSON.stringify(next))return current;if(!base||!next||!current||[base,next,current].some(v=>typeof v!=='object'||Array.isArray(v)))return next;const out={...current};for(const key of new Set([...Object.keys(base),...Object.keys(next)])){if(!(key in next))delete out[key];else out[key]=mergeDraft(base[key],next[key],current[key]);}return out;}
const validRows=(name,rows)=>rows&&typeof rows==='object'&&!Array.isArray(rows)&&(name==='manifest'||Object.values(rows).every(row=>row&&typeof row==='object'&&!Array.isArray(row)));
// Native confirm() has no host handler in WKWebView; use an in-page dialog instead.
function ask(message,confirmLabel='确定'){return new Promise(resolve=>{const d=document.createElement('dialog');d.className='json-editor-confirm';d.innerHTML=`<p>${esc(message)}</p><div><button data-ask-cancel>取消</button><button class="danger-button" data-ask-ok>${esc(confirmLabel)}</button></div>`;document.body.append(d);const done=v=>{d.close();d.remove();resolve(v);};d.querySelector('[data-ask-cancel]').onclick=()=>done(false);d.querySelector('[data-ask-ok]').onclick=()=>done(true);d.addEventListener('cancel',e=>{e.preventDefault();done(false);});d.showModal();});}
function projectId(){return window.STUDIO_CURRENT_PROJECT?.()||null;}
function readOnly(){const id=projectId();return !!(window.STUDIO_PROJECTS?.()||[]).find(p=>String(p.id)===String(id))?.readOnly;}
function hint(){
 const wk=window.STUDIO_WORKSHOP_NAV;if(wk?.isOpen?.()){const c=wk.capture?.()||{};if(c.mode==='table'&&c.table)return c.table+'.json';if(HINTS[c.mode])return HINTS[c.mode];return lastFile||'TalkCfg.json';}
 if(window.STUDIO_EVENTS?.isOpen?.())return 'EvtCfg.json';return 'TalkCfg.json';
}
function ensureCorner(){
 if(corner)return corner;corner=document.createElement('button');corner.type='button';corner.id='json-corner';corner.className='json-corner';corner.title='查看 JSON 编码';corner.setAttribute('aria-label','查看当前页面对应的 JSON 编码');corner.innerHTML='<span aria-hidden="true">{ }</span>';corner.hidden=true;
 corner.addEventListener('click',()=> (dialog?closeDrawer():open()).catch(e=>window.STUDIO_NOTIFY?.(e.message,true)));(window.STUDIO_CORNER_TOOLS?.add||((button)=>document.body.append(button)))(corner);bug=document.createElement('button');bug.type='button';bug.id='config-doctor-corner';bug.className='json-corner config-doctor-corner';bug.title='检查并修复配置文件';bug.setAttribute('aria-label','检查并修复配置文件');bug.hidden=true;bug.innerHTML='<svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 7h8v10a4 4 0 0 1-8 0V7Zm2 0V5a2 2 0 0 1 4 0v2M9 3 7 1m8 2 2-2M8 10 4 8m4 6H3m5 4-4 2m12-10 4-2m-4 6h5m-5 4 4 2M12 8v12"/></svg>';bug.onclick=()=>window.STUDIO_CONFIG_DOCTOR.open();(window.STUDIO_CORNER_TOOLS?.add||((button)=>document.body.append(button)))(bug);return corner;
}
function tick(){const button=ensureCorner();const show=!!projectId()&&!window.STUDIO_PREVIEW_ACTIVE?.()&&!window.STUDIO_HELP?.isOpen?.()&&!document.querySelector('#studio-onboarding:not([hidden])');if(button.hidden===show)button.hidden=!show;if(bug)bug.hidden=!show;if(dialog){layout();syncDrawer?.().catch(e=>window.STUDIO_NOTIFY?.(e.message,true));}}
setInterval(tick,700);document.addEventListener('DOMContentLoaded',tick);

async function open(preferred){
 await window.STUDIO_STORY_JSON?.prepare?.();
 if(dialog||opening)return;opening=true;const id=projectId();if(!id)throw Error('请先打开模组。');
 let list;try{list=await api('/api/json-files?projectId='+encodeURIComponent(id));}finally{opening=false;}
 dialog=document.createElement('dialog');dialog.className='json-editor-dialog';dialog.id='json-editor';
 dialog.innerHTML=`<header class="json-editor-header"><div class="json-editor-heading"><h2>JSON 编码</h2><select data-json-file aria-label="选择 JSON 文件" data-no-search="true">${list.files.map(f=>`<option value="${esc(f.path)}">${esc(f.name)}${f.config?'':' · 模组根目录'}</option>`).join('')}</select></div><div class="json-editor-actions"><button data-json-fix class="primary">一键修复语法错误</button><button data-json-check>检查语法</button><button data-json-undo title="Ctrl+Z">撤销</button><button data-json-redo title="Ctrl+Y">重做</button><button data-json-save>保存到模组</button><button data-json-close aria-label="关闭 JSON 编码">关闭</button></div></header><div class="json-editor-errors" data-json-errors hidden></div><div class="json-editor-find" data-json-find hidden><input data-find-input type="text" placeholder="查找…（Enter 下一个，Shift+Enter 上一个，Esc 关闭）" aria-label="在 JSON 中查找"><span data-find-count></span><button type="button" data-find-prev title="上一个">↑</button><button type="button" data-find-next title="下一个">↓</button><button type="button" data-find-close aria-label="关闭查找">✕</button></div><div class="json-editor-body"><div class="json-editor-gutter" aria-hidden="true"></div><div class="json-editor-code"><div class="json-editor-mirror" aria-hidden="true"></div><textarea class="json-editor-text" spellcheck="false" autocomplete="off" autocapitalize="off" wrap="off" aria-label="JSON 文本"></textarea></div></div><footer class="json-editor-footer"><span data-json-status role="status" aria-live="polite"></span><span class="json-editor-hint">语法错误的行会标红；「一键修复」只补上确定缺失的逗号，不猜测其他内容。注释与末尾多余逗号游戏可以读取，不算错误。</span></footer>`;
 document.body.append(dialog);
 const q=s=>dialog.querySelector(s),select=q('[data-json-file]'),text=q('textarea'),mirror=q('.json-editor-mirror'),gutter=q('.json-editor-gutter'),errorsBox=q('[data-json-errors]'),status=q('[data-json-status]');
 dialog.classList.toggle('json-wrap',wrapLines);text.wrap=wrapLines?'soft':'off';
 state={id,path:'',loaded:'',current:'',bom:false,revision:null,history:[],future:[],lastPush:0,errors:[],valid:true,busy:false,analysis:0};
 let context=id+'|'+hint(),loadSequence=0;
 const wanted=preferred||hint();ensureFile(wanted);const match=list.files.find(f=>f.name===wanted||f.path===wanted||f.path==='Cfgs/zh-cn/'+wanted)||list.files.find(f=>f.path===lastFile)||list.files[0];
 const setStatus=(message,error=false)=>{status.textContent=message;status.classList.toggle('error',!!error);};
 const lineCount=()=>text.value.length?text.value.split('\n').length:1;
 const dirty=()=>text.value!==state.loaded;
 // The mirror repeats the text with the textarea's exact metrics (invisible glyphs),
 // so each logical line's on-screen top/height is measured by the browser even when
 // a long line wraps visually. Gutter numbers and error bands follow the mirror.
 let mirrorText=null,mirrorWidth=0,mirrorFrame=null;
 // Search term (marks every match) and the lines of the record/field the visual editor is focused on.
 const find={term:'',matches:[],index:-1,focusLines:new Set()};
 function markLine(line){if(!find.term)return esc(line);const lower=line.toLowerCase(),term=find.term.toLowerCase();let out='',from=0,at;while((at=lower.indexOf(term,from))>=0){out+=esc(line.slice(from,at))+'<span class="json-mark">'+esc(line.slice(at,at+term.length))+'</span>';from=at+term.length;}return out+esc(line.slice(from));}
 function syncMirrorGeometry(){const width=text.clientWidth;if(width!==mirrorWidth){mirrorWidth=width;mirror.style.width=width+'px';}}
 function buildMirror(){mirrorFrame=null;if(!state||!dialog)return;const value=text.value;syncMirrorGeometry();const cacheKey=value+'\u0000'+find.term;if(cacheKey!==mirrorText){mirrorText=cacheKey;const lines=value.split('\n');let html='';for(const line of lines)html+='<div class="json-line">'+(line?markLine(line):'\u200b')+'</div>';mirror.innerHTML=html;}
  const bad=new Map();for(const e of state.errors){bad.set(e.line,'json-line-error');if(e.fixLine!==e.line&&!bad.has(e.fixLine))bad.set(e.fixLine,'json-line-fix');}
  const children=mirror.children;for(let i=0;i<children.length;i++){const cls='json-line'+(bad.has(i+1)?' '+bad.get(i+1):'')+(find.focusLines.has(i+1)?' json-line-focus':'');if(children[i].className!==cls)children[i].className=cls;}
  mirror.style.transform=`translate(${-text.scrollLeft}px,${-text.scrollTop}px)`;paintGutter();}
 function scheduleMirror(){if(mirrorFrame)return;mirrorFrame=requestAnimationFrame(buildMirror);}
 function lineTop(n){const node=mirror.children[n-1];return node?node.offsetTop:0;}
 function paintGutter(){const children=mirror.children,total=children.length;if(!total){gutter.innerHTML='';return;}const top=text.scrollTop,bottom=top+text.clientHeight;
  // Binary search the first line whose bottom edge is inside the viewport.
  let lo=0,hi=total-1;while(lo<hi){const mid=(lo+hi)>>1;if(children[mid].offsetTop+children[mid].offsetHeight<top)lo=mid+1;else hi=mid;}
  const bad=new Set(state.errors.map(e=>e.line));let html='';for(let i=Math.max(0,lo-1);i<total;i++){const node=children[i];if(node.offsetTop>bottom+40)break;html+=`<span class="${bad.has(i+1)?'json-line-error':''}" style="top:${node.offsetTop-top}px">${i+1}</span>`;}
  // Spans are offset by the scroll position; the gutter box itself stays inside the body and clips.
  gutter.innerHTML=html;gutter.style.height='';gutter.style.transform='';}
 function paintErrors(){scheduleMirror();
  errorsBox.hidden=!state.errors.length;errorsBox.innerHTML=state.errors.map((e,i)=>`<button data-json-goto="${i}"><strong>第 ${e.line} 行第 ${e.col} 列</strong>${esc(e.message)}${e.fixLine!==e.line||e.fixCol!==e.col?`<em>（应在第 ${e.fixLine} 行第 ${e.fixCol} 列补上）</em>`:''}${e.fixable?'<span class="json-fixable">可一键修复</span>':''}</button>`).join('');
  q('[data-json-fix]').disabled=state.busy||readOnly()||!state.errors.some(e=>e.fixable);paintGutter();}
 function applyAnalysis(a){state.errors=a.errors||[];state.valid=!!a.valid;paintErrors();}
 // Undo history keeps the text before each burst of typing; quick successive keystrokes merge into one step.
 function push(){const now=Date.now();if(text.value===state.current)return;if(now-state.lastPush<700&&state.history.length){state.current=text.value;state.lastPush=now;return;}state.history.push(state.current);if(state.history.length>200)state.history.shift();state.current=text.value;state.future=[];state.lastPush=now;refreshButtons();}
 function refreshButtons(){q('[data-json-undo]').disabled=!state.history.length;q('[data-json-redo]').disabled=!state.future.length;q('[data-json-save]').disabled=state.busy||readOnly()||!dirty();q('[data-json-fix]').disabled=state.busy||readOnly()||!state.errors.some(e=>e.fixable);text.readOnly=readOnly();}
 function setValue(value){state.history.push(state.current);state.future=[];text.value=value;state.current=value;state.lastPush=0;refreshButtons();scheduleMirror();scheduleCheck(0);}
 function scheduleCheck(delay=600){clearTimeout(timer);if(text.value.length>LIVE_LIMIT){setStatus('文件较大，修改后请点击「检查语法」。');return;}timer=setTimeout(check,delay);}
 function stash(){if(!state?.path)return;state.current=text.value;state.scrollTop=text.scrollTop;state.scrollLeft=text.scrollLeft;drafts.set(state.id+'|'+state.path,state);}
 function ensureFile(name){if(!list.files.some(f=>f.path===name||f.path==='Cfgs/zh-cn/'+name)){const path=name==='manifest.json'?name:'Cfgs/zh-cn/'+name;list.files.push({path,name,virtual:true});select.add(new Option(name,path));}}
 function bridge(){return provider(table(state.path),state.disk||{});}
 function syncVisual(){if(!state.path||state.busy||state.pending)return;const source=bridge(),rows=source?.read();if(rows==null)return;const signature=JSON.stringify(rows);if(signature===state.visual)return;
  if(!state.valid){if(state.visual===undefined)state.visual=signature;setStatus('JSON 输入尚未完成；已保留文本，暂停双向同步。',true);return;}
  state.visual=signature;let parsed;try{parsed=JSON.parse(text.value);}catch{}if(JSON.stringify(parsed)!==signature){const start=text.selectionStart,end=text.selectionEnd,scroll=text.scrollTop;setValue(JSON.stringify(rows,null,2)+'\n');text.setSelectionRange(Math.min(start,text.value.length),Math.min(end,text.value.length));text.scrollTop=scroll;}refreshButtons();
 }
 async function check(){const current=state,seq=++current.analysis,value=text.value;current.pending=true;try{const a=await api('/api/json-analyze',{text:value,parse:true});if(current!==state||seq!==state.analysis||!dialog||text.value!==value)return;applyAnalysis(a);
  if(a.valid&&validRows(table(state.path),a.value)&&!readOnly()){const source=bridge();if(source){const signature=JSON.stringify(source.read());if(state.visual!==undefined&&signature!==state.visual){a.value=mergeDraft(JSON.parse(state.visual),a.value,source.read());text.value=state.current=JSON.stringify(a.value,null,2)+'\n';}const submittedText=text.value;await source.write(a.value);if(current!==state||seq!==state.analysis||!dialog||text.value!==submittedText)return;const canonical=source.read();state.visual=JSON.stringify(canonical);if(JSON.stringify(a.value)!==state.visual){a.value=canonical;setValue(JSON.stringify(canonical,null,2)+'\n');}}state.parsed=a.value;}
  state.pending=false;setStatus(a.valid?`语法正确 · ${lineCount()} 行${dirty()?' · 未保存':''}`:`发现 ${a.errors.length} 处语法错误；文本已保留`,!a.valid);
 }catch(e){if(current===state&&seq===state.analysis){state.pending=false;setStatus(e.message,true);}}}
 async function load(path,newId=projectId()){stash();clearTimeout(timer);const seq=++loadSequence;state={id:newId,path:'',loaded:'',current:'',bom:false,revision:null,history:[],future:[],lastPush:0,errors:[],valid:true,busy:true,analysis:0};text.value='';refreshButtons();setStatus('正在读取…');try{const saved=drafts.get(newId+'|'+path);if(saved){state=saved;state.busy=false;state.pending=false;text.value=state.current;}else{const file=list.files.find(f=>f.path===path);const data=file?.virtual?{text:'{}',revision:list.revision,analysis:{valid:true,errors:[]}}:await api('/api/json-source',{projectId:newId,path});if(!dialog||seq!==loadSequence)return;Object.assign(state,{path,loaded:data.text,current:data.text,bom:data.bom,revision:data.revision,virtual:!!file?.virtual});text.value=data.text;applyAnalysis(data.analysis);const parsed=await api('/api/json-analyze',{text:data.text,parse:true});if(!dialog||seq!==loadSequence)return;state.disk=parsed.valid?parsed.value:{};}
  select.value=path;lastFile=path;state.busy=false;text.scrollTop=state.scrollTop||0;text.scrollLeft=state.scrollLeft||0;paintErrors();syncVisual();scheduleCheck(0);
 }catch(e){setStatus(e.message,true);}finally{if(seq===loadSequence){state.busy=false;refreshButtons();}}}
 syncDrawer=async()=>{if(state.busy)return;const current=projectId()+'|'+hint();if(context!==current){context=current;const newId=projectId();if(!newId)return;if(newId!==state.id){list=await api('/api/json-files?projectId='+encodeURIComponent(newId));select.innerHTML=list.files.map(f=>`<option value="${esc(f.path)}">${esc(f.name)}</option>`).join('');}ensureFile(hint());await load(list.files.find(f=>f.path===hint()||f.path==='Cfgs/zh-cn/'+hint()).path,newId);}else syncVisual();};
 async function fix(){if(state.busy)return;state.busy=true;refreshButtons();setStatus('正在修复…');try{const a=await api('/api/json-analyze',{text:text.value,repair:true});if(!dialog)return;if(a.fixes?.length){setValue(a.text);applyAnalysis(a);state.keepStatus=true;setStatus(a.valid?`已补上 ${a.fixes.length} 处逗号，语法正确；保存后生效。`:`已补上 ${a.fixes.length} 处逗号，还有 ${a.errors.length} 处需要手动修改。`,!a.valid);}else{applyAnalysis(a);setStatus(a.valid?'没有需要修复的语法错误。':'剩余错误无法自动判断，请按提示手动修改。',!a.valid);}}catch(e){setStatus(e.message,true);}finally{state.busy=false;refreshButtons();}}
 async function save(force=false){if(state.busy||readOnly())return;await check();if(!force&&!state.valid&&!await ask('JSON 仍有语法错误，游戏可能无法读取这个文件。仍然保存？','仍然保存'))return;const current=state;state.busy=true;refreshButtons();setStatus('正在保存…');try{const value=text.value;
  if(!state.virtual){const disk=await api('/api/json-source',{projectId:state.id,path:state.path});if(disk.text===state.loaded)state.revision=disk.revision;}
  const result=await api('/api/json-save',{projectId:state.id,path:state.path,text:value,revision:state.revision,bom:state.bom,force:!state.valid,create:!!state.virtual});if(!dialog||current!==state)return;state.loaded=value;state.revision=result.revision;state.virtual=false;applyAnalysis(result.analysis);if(state.valid&&state.parsed){const oldDisk=state.disk;bridge()?.saved(state.parsed,result.revision);const story=window.STUDIO_STORY_JSON;if(window.STUDIO_WORKSHOP_NAV?.isOpen?.()&&story?.read(table(state.path),oldDisk)!=null){await story.write(table(state.path),state.parsed,oldDisk);story.saved(table(state.path),state.parsed,result.revision);}state.disk=structuredClone(state.parsed);}setStatus(state.valid?'已保存到模组。':'已保存，语法错误仍需修正。',!state.valid);
 }catch(e){setStatus(e.message,true);}finally{current.busy=false;if(dialog)refreshButtons();}}
 // --- Find (Ctrl/Cmd+F while the drawer has focus) ---
 const findBar=q('[data-json-find]'),findInput=q('[data-find-input]'),findCount=q('[data-find-count]');
 const lineOf=pos=>{let n=1;for(let i=0;i<pos;i++)if(text.value.charCodeAt(i)===10)n++;return n;};
 function revealLine(line){buildMirror();text.scrollTop=Math.max(0,lineTop(line)-text.clientHeight/3);}
 function runFind(direction=0,fromCaret=false){const term=findInput.value;find.term=term;find.matches=[];if(term){const hay=text.value.toLowerCase(),needle=term.toLowerCase();let at=-1;while((at=hay.indexOf(needle,at+1))>=0){find.matches.push(at);if(find.matches.length>5000)break;}}
  const total=find.matches.length;if(!total){find.index=-1;findCount.textContent=term?'无结果':'';mirrorText=null;buildMirror();return;}
  if(fromCaret||find.index<0){const caret=text.selectionStart||0;find.index=Math.max(0,find.matches.findIndex(m=>m>=caret));if(find.index<0)find.index=0;}
  else find.index=(find.index+direction+total)%total;
  const start=find.matches[find.index];findCount.textContent=(find.index+1)+' / '+total;mirrorText=null;text.setSelectionRange(start,start+term.length);revealLine(lineOf(start));}
 function openFind(){findBar.hidden=false;const selected=text.value.slice(text.selectionStart,text.selectionEnd);if(selected&&!selected.includes('\n')&&selected.length<200)findInput.value=selected;findInput.focus();findInput.select();if(findInput.value)runFind(0,true);}
 function closeFind(){findBar.hidden=true;find.term='';find.matches=[];find.index=-1;findCount.textContent='';mirrorText=null;buildMirror();text.focus();}
 findInput.addEventListener('input',()=>{find.index=-1;runFind(0,true);});
 findInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();runFind(e.shiftKey?-1:1);}else if(e.key==='Escape'){e.preventDefault();closeFind();}});
 q('[data-find-next]').onclick=()=>runFind(1);q('[data-find-prev]').onclick=()=>runFind(-1);q('[data-find-close]').onclick=closeFind;
 // --- Locate: scroll to the record/field the visual editor is working on ---
 function findPath(src,path){let i=0;const n=src.length,ws=()=>{while(i<n&&' \t\r\n'.includes(src[i]))i++;};
  const readString=()=>{const s=i;i++;while(i<n){const c=src[i];if(c==='\\')i+=2;else if(c==='"'){i++;break;}else i++;}try{return JSON.parse(src.slice(s,i));}catch{return src.slice(s+1,i-1);}};
  const skipValue=()=>{ws();const c=src[i];if(c==='"')readString();else if(c==='{'||c==='['){let depth=0;do{const d=src[i];if(d==='"')readString();else{if(d==='{'||d==='[')depth++;else if(d==='}'||d===']')depth--;i++;}}while(i<n&&depth>0);}else{while(i<n&&!',}]'.includes(src[i])&&!' \t\r\n'.includes(src[i]))i++;}};
  function descend(level,keyStart){ws();if(level>=path.length){const start=i;skipValue();return {keyStart,start,end:i};}
   const c=src[i];if(c==='{'){i++;for(;;){ws();if(src[i]==='}'||i>=n)return null;if(src[i]!=='"')return null;const ks=i,key=readString();ws();if(src[i]!==':')return null;i++;if(key===String(path[level]))return descend(level+1,ks);skipValue();ws();if(src[i]===',')i++;}}
   if(c==='['){i++;const want=Number(path[level]);if(!Number.isInteger(want))return null;for(let index=0;;index++){ws();if(src[i]===']'||i>=n)return null;if(index===want)return descend(level+1,i);skipValue();ws();if(src[i]===',')i++;}}
   return null;}
  try{return descend(0,0);}catch{return null;}}
 function highlight(span){find.focusLines.clear();if(span){const first=lineOf(span.keyStart??span.start),last=lineOf(span.end);for(let l=first;l<=Math.min(last,first+400);l++)find.focusLines.add(l);buildMirror();revealLine(first);}else buildMirror();}
 async function locate(target){if(!target||!dialog||state.busy)return false;const wanted=target.file;const file=list.files.find(f=>f.name===wanted||f.path===wanted||f.path==='Cfgs/zh-cn/'+wanted);if(!file)return false;
  if(file.path!==state.path){await check();await load(file.path);if(!dialog||state.path!==file.path)return false;}
  const span=findPath(text.value,target.path||[]);highlight(span);return !!span;}
 locateInDrawer=locate;
 function goto(index){const e=state.errors[index];if(!e)return;const lines=text.value.split('\n');let pos=0;for(let n=1;n<e.fixLine&&n<=lines.length;n++)pos+=lines[n-1].length+1;pos+=Math.max(0,e.fixCol-1);text.focus();text.setSelectionRange(pos,pos);buildMirror();text.scrollTop=Math.max(0,lineTop(e.fixLine)-text.clientHeight/2);paintErrors();}
 function undo(){if(!state.history.length)return;state.future.push(state.current);state.current=text.value=state.history.pop();state.lastPush=0;refreshButtons();scheduleMirror();scheduleCheck(0);}
 function redo(){if(!state.future.length)return;state.history.push(state.current);state.current=text.value=state.future.pop();state.lastPush=0;refreshButtons();scheduleMirror();scheduleCheck(0);}
 async function close(){if(state.busy)return;await check();stash();clearTimeout(timer);window.STUDIO_LAYERING?.release(dialog);dialog.close();dialog.remove();dialog=null;state=null;syncDrawer=null;closeDrawer=null;locateInDrawer=null;document.body.classList.remove('json-drawer-open');window.STUDIO_STORY_JSON?.finish?.();window.dispatchEvent(new Event('resize'));}
 closeDrawer=close;
 text.addEventListener('input',()=>{state.pending=true;push();refreshButtons();scheduleMirror();scheduleCheck(180);});
 text.addEventListener('scroll',()=>{mirror.style.transform=`translate(${-text.scrollLeft}px,${-text.scrollTop}px)`;paintGutter();});
 if(typeof ResizeObserver==='function'){const observer=new ResizeObserver(()=>{if(dialog&&state)buildMirror();});observer.observe(text);}
 text.addEventListener('keydown',e=>{const mod=e.ctrlKey||e.metaKey;if(mod&&!e.altKey&&(e.key==='z'||e.key==='Z')){e.preventDefault();e.shiftKey?redo():undo();}else if(mod&&(e.key==='y'||e.key==='Y')){e.preventDefault();redo();}else if(mod&&(e.key==='s'||e.key==='S')){e.preventDefault();save();}else if(e.key==='Tab'){e.preventDefault();const s=text.selectionStart,en=text.selectionEnd;text.setRangeText('  ',s,en,'end');push();refreshButtons();scheduleCheck();}});
 dialog.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.hasAttribute('data-json-close'))close();else if(b.hasAttribute('data-json-fix'))fix();else if(b.hasAttribute('data-json-check')){setStatus('正在检查…');check();}else if(b.hasAttribute('data-json-undo'))undo();else if(b.hasAttribute('data-json-redo'))redo();else if(b.hasAttribute('data-json-save'))save();else if(b.dataset.jsonGoto!==undefined)goto(Number(b.dataset.jsonGoto));});
 select.addEventListener('change',async()=>{const path=select.value;await check();load(path);});
 dialog.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&!e.altKey&&(e.key==='f'||e.key==='F')){e.preventDefault();e.stopPropagation();openFind();}else if(e.key==='Escape'&&!findBar.hidden){e.preventDefault();closeFind();}});
 dialog.addEventListener('cancel',e=>e.preventDefault());
 document.body.classList.add('json-drawer-open');layout();try{const saved=Number(localStorage.getItem('studio-json-drawer-width'));if(saved>=300)document.body.style.setProperty('--json-drawer-width',Math.min(saved,Math.floor(innerWidth*.7))+'px');}catch{}
 // Drag the left edge to give long lines more room; the width is remembered on this machine.
 const grip=document.createElement('div');grip.className='json-editor-grip';grip.title='拖动调整宽度';dialog.append(grip);
 grip.addEventListener('pointerdown',e=>{e.preventDefault();grip.setPointerCapture(e.pointerId);const startX=e.clientX,startW=dialog.getBoundingClientRect().width;const move=ev=>{const w=Math.max(300,Math.min(Math.floor(innerWidth*.7),Math.round(startW+(startX-ev.clientX))));document.body.style.setProperty('--json-drawer-width',w+'px');};const up=()=>{grip.removeEventListener('pointermove',move);grip.removeEventListener('pointerup',up);grip.removeEventListener('pointercancel',up);try{localStorage.setItem('studio-json-drawer-width',String(Math.round(dialog.getBoundingClientRect().width)));}catch{}window.dispatchEvent(new Event('resize'));};grip.addEventListener('pointermove',move);grip.addEventListener('pointerup',up);grip.addEventListener('pointercancel',up);});
 if(window.STUDIO_LAYERING&&dialog.showPopover){window.STUDIO_LAYERING.keepOnTop(dialog);dialog.setAttribute('open','');}else dialog.show();window.dispatchEvent(new Event('resize'));if(match){select.value=match.path;await load(match.path);}else setStatus('这个模组还没有 JSON 文件。');
}
// Any input the visual editor focuses (a character's name, a table field…) scrolls the drawer to its JSON.
function resolveFocus(el){
 if(!el||!(el instanceof Element)||!dialog||dialog.contains(el))return null;
 if(!/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)||el.type==='search'||el.type==='file'||/search/i.test(el.id||'')||[...el.attributes].some(a=>/search|filter|find/i.test(a.name)))return null;
 const personValue=el.getAttribute('data-person-value');if(personValue){const parts=personValue.split('.');return {file:parts[0]+'.json',path:parts.slice(1)};}
 const wk=window.STUDIO_WORKSHOP_NAV;
 if(wk?.isOpen?.()){const c=wk.capture?.()||{};const fieldPath=el.closest('[data-path]')?.getAttribute('data-path')||el.getAttribute('data-field')||'';
  if(c.mode==='table'&&c.table&&c.selected!=null&&el.closest('#wk-form'))return {file:c.table+'.json',path:[String(c.selected),...(fieldPath?fieldPath.split('.'):[])]};
  if(c.mode==='manifest')return {file:'manifest.json',path:fieldPath?fieldPath.split('.'):[]};}
 if(window.STUDIO_EVENTS?.isOpen?.()&&el.closest('#story-events')){const id=window.StudentAgeStudioTest?.S?.selected;if(id!=null)return {file:'TalkCfg.json',path:[String(id)]};}
 // Feature pages: the nearest panel that shows a record ID button names the record; a data-*-field attribute names the field.
 let node=el.parentElement,record=null;while(node&&node!==document.body){record=node.querySelector('[data-record-id]');if(record)break;node=node.parentElement;}
 if(!record)return null;const file=record.getAttribute('data-record-table')?record.getAttribute('data-record-table')+'.json':hint();const field=el.getAttribute('data-goal-field')||el.getAttribute('data-field')||'';
 return {file,path:[String(record.getAttribute('data-record-id')),...(field?field.split('.'):[])]};
}
let locateTimer=null;
document.addEventListener('focusin',e=>{if(!dialog||!locateInDrawer)return;clearTimeout(locateTimer);const target=resolveFocus(e.target);if(!target)return;locateTimer=setTimeout(()=>{locateInDrawer?.(target).catch(()=>{});},120);});
window.STUDIO_JSON_EDITOR={open:file=>open(file),isOpen:()=>!!dialog,close:()=>closeDrawer?.(),hint,locate:target=>locateInDrawer?locateInDrawer(target):Promise.resolve(false)};
})();
