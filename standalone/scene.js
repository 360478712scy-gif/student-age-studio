'use strict';

// Stateful scene reconstruction follows story links, never the editor's sorted list.
(() => {
const copy = value => JSON.parse(JSON.stringify(value));
const list = value => Array.isArray(value) ? value.map(Number).filter(Number.isFinite) : [];
const unique = values => [...new Set(values)];
const label = (doc,id) => doc.persons?.[id]?.name || (Number(id)===0?'主角':'人物 '+id);
const protagonistGender=doc=>Number(doc.protagonistGender)===2?2:1;
const portraitIdentity=(doc,id)=>Number(id)===0&&protagonistGender(doc)===2?'0-female':String(id);
const supported = new Set([1001,1002,1003,2001,2002,3000,3001,3002,3003,3004,3005,3006,3007,3008,3009,3012,3013,3014]);

// Retained API for callers; native durations are authored data, never repaired.
function normalizeNativeMoves(talk){return talk;}
function routes(doc,talk,{allBranches=false}={}) {
  if(!talk)return [];
  const result=[];
  if(talk.miniGame?.length)return [{id:null,label:'先进行小游戏（请在游戏内预演）',type:'external',available:false}];
  function add(target,text,type,conditional=false,reset=false,extra={},seen=new Set()){
    target=Number(target);if(seen.has(target))return;seen=new Set([...seen,target]);
    const all=Object.values(doc.branchFolders||{}),exit=all.find(f=>f.kind==='condition'&&Number(f.exitId)===target),end=all.some(f=>f.kind==='condition'&&Number(f.endId)===target);
    const completed=all.find(f=>f.kind==='condition'&&!list(f.baseNext).some(id=>id>0)&&(Number(f.endId)===target||(Number(f.exitId)===target&&f.continuation?.kind==='following')));
    const outer=completed&&all.find(f=>f.kind!=='condition'&&list(f.talkIds).at(-1)===Number(completed.parentTalkId)&&f.continuation?.kind==='event');
    if(outer){eventExit(outer.continuation.eventId,text,type,conditional);return;}
    if(end){target=0;}
    if(exit){
      if(exit.continuation?.kind==='event'){eventExit(exit.continuation.eventId,text,type,conditional);return;}
      const dest=list(doc.talks[target]?.nextTalk);if(dest.length){dest.forEach(id=>add(id,text,type,conditional,reset,extra,seen));return;}target=0;
    }
    if(target===0){result.push({id:null,label:text+' · 结束',type,conditional,end:true,available:true,...extra});return;}
    result.push({id:target,label:text,type,conditional,reset,available:!!doc.talks?.[target],...extra});
  }
  function exits(targets,text,type,conditional=false,reset=false,extra={}){const values=list(targets);if(!values.length)return;values.forEach((target,index)=>add(target,text+(values.length>1?(index===0?' · 男主角':index===1?' · 女主角':' · 保留的额外目标'):''),type,conditional||values.length>1,reset,{...extra,...(values.length>1?{gender:index===0?1:index===1?2:null,genderOnly:!conditional}: {})}));}
  function eventExit(eventId,text,type,conditional=false){const event=doc.events?.[eventId];if(event&&list(event.talkId).length)exits(event.talkId,text+' · 接续剧情「'+(event.title||'未命名剧情')+'」（预演）',type,conditional,true,{eventId:Number(eventId)});else result.push({id:null,label:text+' · 未载入后续剧情',available:false,type:'external',eventId:Number(eventId)});}
  const options=list(talk.option);
  for(const id of options){const optionRouteStart=result.length;const option=doc.options?.[id];if(!option){result.push({id:null,label:'外部选项 '+id,type:'external',available:false});continue;}
    if(option.miniGame?.length){result.push({id:null,label:(option.content||'选择')+' · 先进行小游戏（游戏内预演）',type:'external',available:false});continue;}
    const managedFolder=doc.branchFolders?.[Number(talk.id)+':'+id];
    const managed=managedFolder?.continuation?.kind==='event'&&!list(managedFolder.talkIds).length&&Number(managedFolder.continuation.eventId)===Number(option.nextEvtId);
    function optionEvent(text){if(managed)eventExit(option.nextEvtId,text,'option',true);else result.push({id:null,label:text+' · 原版事件弹窗（游戏内预演）',type:'external',available:false,eventId:Number(option.nextEvtId)});}
    const check=!!option.check?.length,conditional=!!(check||option.precondition?.length),name=option.content||'未命名选择';
    if(list(option.talkId).length)exits(option.talkId,name+(check?' · 条件满足':''),'option',conditional);
    else if(option.nextEvtId)optionEvent(name);
    else result.push({id:null,label:name+(check?' · 条件满足':'')+' · 结束',type:'option',available:true,end:true,conditional});
    if(check){if(list(option.talkId2).length)exits(option.talkId2,name+' · 条件未满足','option',true);else if(option.nextEvtId)optionEvent(name+' · 条件未满足');else result.push({id:null,label:name+' · 条件未满足 · 结束',type:'option',available:true,end:true,conditional:true});}
    for(const route of result.slice(optionRouteStart)){route.optionId=id;route.optionText=option.content||'未命名选择';}
  }
  const branches=Object.values(doc.branchFolders||{}).filter(f=>f.kind==='condition'&&Number(f.parentTalkId)===Number(talk.id)).sort((a,b)=>a.branchId-b.branchId);
  if(branches.length){
    let fallback=true;
    for(const f of branches){const check=doc.talks[f.routerId]?.check?.length;add(list(f.talkIds)[0]||f.exitId,'分支'+f.branchId+(check?' · 条件满足':' · 无限制'),'branch',!!check,false,{branchId:f.branchId});if(!check){fallback=false;if(!allBranches)break;}else if(Array.isArray(f.failureNext)){(list(f.failureNext).length?list(f.failureNext):[f.endId]).forEach(id=>add(id,'分支'+f.branchId+' · 判定失败','alternate',true));fallback=false;if(!allBranches)break;}}
    if(fallback){const next=list(branches[0].baseNext);(next.length?next:[branches[0].endId]).forEach(id=>add(id,'所有分支条件均不满足','alternate',true));}
    return result;
  }
  const conditional=!!talk.check?.length,normal=list(talk.nextTalk),alternate=list(talk.nextTalk2);
  if(conditional){const fallback=!alternate.length||alternate[0]===0?normal:alternate;normal.forEach((target,index)=>{const gender=normal.length>1?(index===0?' · 男主角':' · 女主角'):'';if(!target){add(0,'普通出口为空'+gender,'next',false);return;}add(target,'条件满足'+gender,'next',true,false,{gender:normal.length>1?index+1:null});const other=fallback.length>1?fallback[index]:fallback[0];add(other||0,'条件未满足'+(!alternate.length||alternate[0]===0?' · 沿用普通出口':'')+gender,'alternate',true,false,{gender:normal.length>1?index+1:null});});}
  else exits(normal,options.length?'不选选项，继续对话':'下一句','next',false);
  if(!normal.some(id=>id>0)&&!alternate.some(id=>id>0)&&!options.length){
    const folder=Object.values(doc.branchFolders||{}).find(f=>list(f.talkIds).at(-1)===Number(talk.id)&&f.continuation?.kind==='event');
    if(folder){result.length=0;eventExit(folder.continuation.eventId,'对话夹结束','event',conditional);}
  }
  return result;
}
function pathTo(doc,target,roots) {
  target=Number(target);
  function search(starts){
    const queue=[],parents=new Map();
    for(const root of unique(list(starts)))if(doc.talks?.[root]){queue.push(root);parents.set(root,null);}
    for(let index=0;index<queue.length&&index<20000;index++){
      const id=queue[index];if(id===target){const path=[];for(let node=id;node!==null;node=parents.get(node))path.push(node);path.reverse();return {path,found:true};}
      for(const route of routes(doc,doc.talks[id]))if(route.id!==null&&route.available&&!parents.has(route.id)){parents.set(route.id,id);queue.push(route.id);}
    }
    return null;
  }
  const explicit=search(roots);if(explicit)return explicit;
  // A new mod can contain a connected draft before an event entry is assigned.
  // Recover only real predecessors of this dialogue, never its sidebar neighbours.
  const incoming=new Map();
  for(const talk of Object.values(doc.talks||{}))for(const route of routes(doc,talk))if(route.id!==null&&route.available&&doc.talks[route.id]){
    if(!incoming.has(route.id))incoming.set(route.id,new Set());incoming.get(route.id).add(Number(talk.id));
  }
  const ancestors=[target],seen=new Set(ancestors),starts=[];
  for(let index=0;index<ancestors.length&&index<20000;index++){
    const id=ancestors[index],previous=incoming.get(id);
    if(!previous?.size)starts.push(id);
    else for(const parent of previous)if(!seen.has(parent)){seen.add(parent);ancestors.push(parent);}
  }
  const draft=search(starts);if(draft)return {...draft,inferred:true};
  return {path:doc.talks?.[target]?[target]:[],found:false};
}
function blank(reference=[2560,1440]) {return {background:0,cg:0,paperId:0,phone:null,phoneEvent:null,roles:{},roleCloths:{},motionStarts:{},talkId:null,speaker:'',speakerIds:[],speakerGender:0,highlightIds:[],content:'',warnings:[],motions:[],reference,trace:[],routeChoices:[],talkingAxis:2,useCloth:null};}
// Match the native List<T>.Sort introsort, including its unstable equal-key
// ordering. JavaScript Array.sort is stable and produces different cast slots.
function nativeRoleOrder(input){
 const a=input.map(r=>r.slice()),cmp=(x,y)=>x[0]!==y[0]?0:x[1]>=1001&&x[1]<=1003?-1:y[1]>=1001&&y[1]<=1003?1:0;
 const swap=(i,j)=>{[a[i],a[j]]=[a[j],a[i]];},order=(i,j)=>{if(i!==j&&cmp(a[i],a[j])>0)swap(i,j);};
 function heap(lo,n){function down(i,count){const d=a[lo+i-1];while(i<=Math.floor(count/2)){let child=2*i;if(child<count&&cmp(a[lo+child-1],a[lo+child])<0)child++;if(cmp(d,a[lo+child-1])>=0)break;a[lo+i-1]=a[lo+child-1];i=child;}a[lo+i-1]=d;}
  for(let i=Math.floor(n/2);i>=1;i--)down(i,n);for(let i=n;i>1;i--){swap(lo,lo+i-1);down(1,i-1);}}
 function sort(lo,hi,depth){while(hi>lo){const n=hi-lo+1;if(n<=16){if(n===2){order(lo,hi);return;}if(n===3){order(lo,hi-1);order(lo,hi);order(hi-1,hi);return;}for(let i=lo;i<hi;i++){const t=a[i+1];let j=i;while(j>=lo&&cmp(t,a[j])<0){a[j+1]=a[j];j--;}a[j+1]=t;}return;}
  if(depth--===0){heap(lo,n);return;}const mid=lo+Math.floor((hi-lo)/2);order(lo,mid);order(lo,hi);order(mid,hi);const pivot=a[mid];swap(mid,hi-1);let left=lo,right=hi-1;while(left<right){while(left<hi&&cmp(a[++left],pivot)<0){}while(right>lo&&cmp(pivot,a[--right])<0){}if(left>=right)break;swap(left,right);}if(left!==hi-1)swap(left,hi-1);sort(left+1,hi,depth);hi=left-1;}}
 if(a.length>1)sort(0,a.length-1,2*(Math.floor(Math.log2(a.length))+1));return a;
}
// Forward Sequence evaluation follows the bundled DOTween implementation:
// stable insertion order, lazy start capture and whole-position writes, including
// overlapping tweens which can overwrite one another after a shorter one ends.
function nativePositionPlayer(track){
 const f=Math.fround,items=track.steps.map((s,index)=>({...s,index,at:f(s.at),duration:f(s.duration),end:f(s.at+s.duration),from:null})).sort((a,b)=>a.at-b.at||a.index-b.index);
 let point={x:f(track.start.x),y:f(track.start.y)},previous=-1;
 return {get point(){return {...point};},advance(time){const now=f(time);if(now<previous)throw Error('Position playback must advance forwards');
  for(const s of items){if(s.at>now||(s.at>0?s.end<=previous:s.end<previous))continue;
   if(s.set){point={x:f(s.x),y:f(s.y)};continue;}
   if(!s.from)s.from={...point};const p=s.duration>0?Math.min(1,Math.max(0,f(f(now-s.at)/s.duration))):1;
   const ease=f(f(-p)*f(p-2));point={x:f(s.from.x+f(f(s.x-s.from.x)*ease)),y:f(s.from.y+f(f(s.y-s.from.y)*ease))};
  }previous=now;return {...point};}};
}
function nativePositionFrames(track){
 const duration=Math.max(0,...track.steps.map(s=>s.at+s.duration)),player=nativePositionPlayer(track),frames=[];
 // Dense linear samples avoid substituting CSS ease-out for native OutQuad.
 // Cap sampling for long delays; retain all command boundaries independently.
 const count=Math.max(1,Math.min(7200,Math.ceil(duration*120))),times=new Set([0,duration]);
 for(let i=1;i<count;i++)times.add(i*duration/count);
 for(const s of track.steps){times.add(s.at);times.add(s.at+s.duration);}
 for(const time of [...times].sort((a,b)=>a-b))frames.push({time,...player.advance(time)});
 return {duration,frames};
}
function apply(doc,prior,talk,grade=1,recordTrace=true) {
  if(globalThis.StudentAgeRemoteTalks?.nodeInfo(talk))talk=StudentAgeRemoteTalks.sceneRecord(talk);
  const state=copy({...prior,trace:[]});state.motionStarts=copy(prior.roles);state.motions=[];state.positionTracks={};state.paperId=0;state.talkId=talk.id;state.trace=recordTrace?[...prior.trace,talk.id]:[];
  // NewTalkView retains roleCloths independently of the visible cast.
  state.roleCloths??={};
  // Exit records are retained for this line's rendering only. Native removes
  // the actor after its sequence, so the next line must create a fresh record.
  for(const [id,role] of Object.entries(state.roles)){if(!role.visible){delete state.roles[id];delete state.motionStarts[id];}else delete role.emoji;}
  state.speakerIds=list(talk.roleIds).filter(id=>id>=0);state.speaker=talk.roleName||state.speakerIds.map(id=>label(doc,id)).join('、')||'旁白';state.content=talk.content||'';
  state.highlightIds=unique([...state.speakerIds,...list(talk.highlights)]);
  for(const [id,on]of Object.entries(talk.studioLighting||{})){state.highlightIds=state.highlightIds.filter(x=>x!==Number(id));if(on)state.highlightIds.push(Number(id));}
  // Speaking always takes priority, including legacy manual 'off' settings.
  state.highlightIds=unique([...state.speakerIds,...state.highlightIds]);
  const genders=unique(state.speakerIds.map(id=>id===0?protagonistGender(doc):Number(doc.persons?.[id]?.gender)||0));
  state.speakerGender=genders.length===1&&[1,2].includes(genders[0])?genders[0]:0;
  // NewTalkView.RefreshTalk -> OnBlackBg clears the previous cast before
  // applying this line's actions. bg=0/same background inherits; -2 retains
  // actors across a black transition. CG/comic mode bypasses this clear.
  const bg=Number(talk.bg)||0,changesScene=bg===-1||bg===-2||(bg!==prior.background&&!!doc.backgrounds?.[bg]);
  state.transition=(prior.talkId!=null&&(changesScene||Math.floor(prior.talkId/1000)!==Math.floor(talk.id/1000)))?{kind:!prior.talkId||bg<=0||backgroundPath(doc,{background:bg,roles:prior.roles})===backgroundPath(doc,prior)?'wipe':'mosaic',from:prior.background}:null;
  state.screen=window.StudentAgeScreenEffects?.state(prior.screen,talk,changesScene);
  if(changesScene&&bg!==-2&&!prior.cg&&!prior.nativeComic){state.roles={};state.motionStarts={};state.talkingAxis=2;}
  if(!state.speakerIds.length)state.talkingAxis=2;
  const defaultAxis=state.talkingAxis===3?1:(state.talkingAxis%2+1);
  if(Number(talk.bg)>0){state.background=Number(talk.bg);if(!state.useCloth?.length){state.useCloth=list(doc.backgrounds?.[state.background]?.cloth);if(!state.useCloth.length)state.useCloth=[0];}}
  const outfitCloth=id=>{const outfits=doc.characterOutfits?.[id];if(!outfits)return null;return Number(Object.entries(outfits).find(([slot,o])=>(o.backgrounds||[]).includes(state.background))?.[0]||0);};
  for(const role of Object.values(state.roles)){const cloth=outfitCloth(role.id);if(cloth!==null&&state.background!==prior.background){role.cloth=cloth;delete role.manualCloth;}}
  const defaultCloth=id=>{if(state.roleCloths[id]!=null)return state.roleCloths[id];const outfit=outfitCloth(id);if(outfit!==null)return outfit;if(!state.useCloth?.length)state.useCloth=[0];const special=id===1?1:id===5?2:0;if(special&&doc.backgrounds?.[state.background])return list(doc.backgrounds[state.background].cloth)[special]||0;return state.useCloth[0]||0;};
  const screen=talk.screenEffect||[];
  if(screen.length){const code=Number(screen[0]);if(code===4015)state.cg=Number(screen[1]);else if(code===4017){state.cg=0;state.nativeComic=false;}else if(code===4016){state.nativeComic=true;state.warnings.push('漫画画面需在游戏中预演。');}else if(code===4007&&!(talk.roleIds||[]).length){state.warnings.push('本句没有说话人，原版不会启动电话。');}else if(code===4007){state.phone={left:Number(screen[1])||100,right:state.background||201011,caller:Number(screen[2])||0,remote:screen.slice(2).map(Number),local:[...new Set([...(talk.highlights||[]),...(talk.roleIds||[])].map(Number))]};}else if(code===4008){for(const id of state.phone?.remote||[state.phone?.caller])if(state.roles[id])state.roles[id].visible=false;state.phone=null;}else if(!window.StudentAgeScreenEffects?.entries.some(e=>e.id===code))state.warnings.push('这段包含额外屏幕效果，最终效果请在游戏中确认。');}
  if(talk.effect?.length||talk.effect2?.length||talk.miniGame?.length)state.warnings.push('此段的数值变化、奖励或小游戏交由游戏执行。');
  // Native NewTalkView implicitly brings in a new speaker when there are no explicit actions.
  // Implicit rows are remembered together with the record they create: a scene change, an
  // exit or a branch reset deletes that record, so the editor must edit the entry that
  // still governs the staging on screen, never a superseded one from an earlier scene.
  let actions=nativeRoleOrder((talk.roles||[]).filter(Array.isArray));
  const implicitRows=new Set();let implicitBlock=null;
  if(!actions.length){actions=state.speakerIds.filter(id=>!state.roles[id]).map(id=>[id,1001,1,defaultAxis,0]);implicitBlock=actions.map(row=>row.slice());for(const row of actions)implicitRows.add(row);}
  if(Number(screen[0])===4007&&(talk.roleIds||[]).length&&state.phone){
    const anchor=Number(talk.highlights?.[0]??0),entry=actions.find(r=>Number(r[0])===anchor&&[1001,1002,1003].includes(Number(r[1])));
    const axis=Number(entry?.[3])||state.roles[anchor]?.axis||2;
    state.phone.localRight=axis!==1;
    state.phone.local=state.phone.local.filter(id=>id>=0&&!state.phone.remote.includes(id));
    for(const id of [...state.phone.remote].reverse()){
      if(state.roles[id]){state.roles[id].visible=false;delete state.roles[id].nativeTargetX;delete state.roles[id].nativeTargetY;}
      actions.unshift([id,1001,1,axis===1?2:1,0]);
    }
  }
  // Native RefreshTalk prepares new actors before playing the sorted actions.
  // Initial clothing/flip/shadow are state, not delayed playback commands.
  const creationOrder=[...new Set(actions.map(r=>Number(r[0])))].filter(id=>!state.roles[id]);
  const entered=new Set(),initial=new Map(),declaredAxes=new Map();
  for(const row of actions)if(row[1]>=1001&&row[1]<=1003&&row.length>3)declaredAxes.set(Number(row[0]),Number(row[3]));
  const prepared=[];
  for(const row of actions){const id=Number(row[0]),code=Number(row[1]);
    if(code>=1001&&code<=1003)entered.add(id);
    if(!state.roles[id]?.visible&&[3006,3007,3012,3013,3014].includes(code)){
      const data=initial.get(id)||{};if(code===3006)data.cloth=Number(row[2])||0;if(code===3007)data.flip=true;if(code===3012||code===3013)data.shadow=code===3012;if(code===3014)data.hair=Number(row[2])||0;initial.set(id,data);
      if(!entered.has(id)){entered.add(id);const implicit=[id,1001,1,declaredAxes.get(id)||defaultAxis];implicitRows.add(implicit);prepared.push(implicit);}continue;
    }prepared.push(row);
  }
  actions=prepared;for(const role of Object.values(state.roles))if(role.visible&&!actions.some(r=>Number(r[0])===role.id))actions.push([role.id]);const originalActions=actions;
  function place(role,axis,layer){
    const occupied=new Set(Object.values(state.roles).filter(r=>r.visible&&r.id!==role.id&&r.axis===axis).map(r=>r.slot||0));let slot=0;while(occupied.has(slot))slot++;
    role.slot=slot;const offset=slot===0?0:slot%2?-(slot+1)/2*300:(slot/2)*300;
    role.x=({1:-800,3:0,2:800}[axis]??0)+offset;role.y=layer===-1?-850:0;role.scale=layer===-1?2:1;role.axis=axis;role.layer=layer;
    for(const other of Object.values(state.roles))if(other.id!==role.id&&other.visible&&Math.abs(other.x-role.x)<=500&&(other.depth||0)<=(role.depth||0))role.depth=(other.depth||0)-10;
  }
  const movementDelays={1001:4,1002:4,1003:4,2001:3,2002:2,3001:3,3002:3,3003:3,3004:3,3005:2,3007:2,3008:3,3009:3};
  for(const role of Object.values(state.roles)){role.x=role.nativeTargetX??role.x;role.y=role.nativeTargetY??role.y;}
  for(const row of actions){if(!row.length)continue;const id=Number(row[0]),code=Number(row[1]||0);
    if(code===5001){state.paperId=Number(row[2])||0;continue;}
    if(!Number.isFinite(id)||id<0)continue;
    if(code!==0&&!supported.has(code)){state.warnings.push(label(doc,id)+' 有一个扩展动作（'+code+'），当前预览保留它但不模拟。');continue;}
    let role=state.roles[id];
    if(!role){
      if(code===2001||code===2002)continue;
      role={id,visible:false,x:0,y:0,axis:defaultAxis,layer:1,face:0,cloth:defaultCloth(id),hair:0,scale:1,flip:false,shadow:false,grade};role.depth=-10*(Object.keys(prior.roles||{}).length+Math.max(0,creationOrder.indexOf(id)));Object.assign(role,initial.get(id)||{});state.roles[id]=role;
      // 这条记录由哪一句、哪一种登场建立；同句的显式登场指令会覆盖它。
      role.entryTalkId=talk.id;role.entryImplicit=implicitRows.has(row);role.entryBlock=role.entryImplicit?implicitBlock:null;
      state.roleCloths[id]=role.cloth;
      if(code>=3000){place(role,declaredAxes.get(id)||defaultAxis,1);state.motionStarts[id]=copy(role);role.visible=true;state.motions.push({id,code:1001,delay:0,fromAxis:defaultAxis});}
    }
    const delay=Math.max(0,Number(row[movementDelays[code]])||0);
    let track=state.positionTracks[id];
    if(!track){const physical=state.motionStarts[id]||role;track=state.positionTracks[id]={start:{x:physical.x,y:physical.y},steps:[],fresh:!physical.visible};}
    if(code>=1001&&code<=1003){
      const axis=Number(row[3])||role.axis||3,layer=Number(row[2])||role.layer||1;
      if(!implicitRows.has(row)){role.entryTalkId=talk.id;role.entryImplicit=false;role.entryBlock=null;}
      if(!role.visible||role.axis!==axis||role.layer!==layer)place(role,axis,layer);
      if(!role.visible)state.motionStarts[id]=copy(role);
      role.axis=axis;role.layer=layer;role.visible=true;state.motions.push({id,code,delay:Number(row[4])||0,fromAxis:Number(row[5])||axis,shake:Number(row[6])||0});
    }else if(code===2001||code===2002){
      const requested=Number(row[2])||role.axis,axis=requested===-1?role.axis:requested,toAxis=axis===1?1:2;
      // Native releases the occupied slot immediately, then removes the record
      // only when the full sequence completes. Fade exits keep the live position.
      if(code===2001){role.x=(toAxis===1?-1:1)*(state.reference[0]/2+500*(state.motionStarts[id]?.scale??role.scale)*(state.motionStarts[id]?.flip?-1:1));role.y=role.layer===-1?-850:0;}
      else{const physical=state.motionStarts[id]||role;role.x=physical.x;role.y=physical.y;}
      role.visible=false;role.axis=code===2001&&axis!==role.axis?axis:-1;delete role.slot;
      state.motions.push({id,code,delay:Number(row[code===2001?3:2])||0,toAxis});
    }
    else if(code===3000)role.face=Number(row[2])||0;
    else if(code===3006){role.cloth=Number(row[2])||0;role.manualCloth=true;state.roleCloths[id]=role.cloth;}
    else if(code===3014){role.hair=Number(row[2])||0;state.warnings.push(label(doc,id)+' 的发型变更需在游戏中确认，截图缓存可能不含该发型。');}
    else if(code===3004||code===3008){role[code===3004?'x':'y']+=Number(row[2])||0;state.motions.push({id,code,delay:Number(row[3])||0,duration:code===3004&&Number(row[5])>0?Number(row[5]):.4,shake:Number(row[4])||0});}
    else if(code===3003){role.scale*=row.length>2&&Number(row[2])===0?0:1.1;state.motions.push({id,code,delay:Number(row[3])||0});}
    else if(code===3005||code===3007){role.flip=!role.flip;state.motions.push({id,code,delay:Number(row[2])||0});}
    else if(code===3012)role.shadow=true;
    else if(code===3013)role.shadow=false;
    else if(code===3009){role.emoji=Math.trunc(Number(row[2]));state.motions.push({id,code,delay:Number(row[3])||0});}
    else if(code===3001)state.motions.push({id,code,count:Math.min(8,Math.max(1,Number(row[2])||1)),delay:Number(row[3])||0,power:Number(row[4])||1});
    else if(code===3002)state.motions.push({id,code,duration:Number(row[2])||.4,delay:Number(row[3])||0});
    if(track.fresh){const first=state.motionStarts[id]||role;track.start={x:first.x,y:first.y};
      if(code===1001){const axis=Number(row[5])||role.axis;if(axis!==3)track.start.x=(axis===1?-1:1)*(state.reference[0]/2+500*role.scale*(role.flip?-1:1));}
      if(code===1003)track.start.y-=state.reference[1];
      track.steps.push({set:true,at:delay,duration:0,...track.start});track.fresh=false;
    }
    if(code===3004&&row.length>5)track.moveTime=Number(row[5]);
    const original=state.motionStarts[id],physical=original?.visible?original:{x:-10000,y:0};
    if(role.x!==physical.x||role.y!==physical.y){
      track.steps.push({at:delay,duration:track.moveTime>0?track.moveTime:.4,x:role.x,y:role.y,code});track.moveTime=0;
    }
  }
  // Native HelpCheckRoleAction updates one shared delay per role in source order.
  // Keep existing movement semantics; use that final delay for the native emoji tween.
  const nativeDelays={},delaySlots={1001:4,1002:4,1003:4,2001:3,2002:2,3001:3,3002:3,3003:3,3004:3,3005:2,3007:2,3008:3,3009:3};
  for(const row of originalActions){const slot=delaySlots[Number(row[1])];if(slot!==undefined&&row.length>slot)nativeDelays[Number(row[0])]=Number(row[slot])||0;}
  for(const role of Object.values(state.roles))if(role.emoji!==undefined){role.emojiDelay=nativeDelays[role.id]||0;for(const m of state.motions)if(m.id===role.id&&m.code===3009){m.delay=role.emojiDelay;m.duration=.5;}}
  if(state.phone){
    const remote=new Set(state.phone.remote||[]),local=state.phone.local||[],allowed=new Set([...local,...remote]);
    for(const role of Object.values(state.roles))if(!allowed.has(role.id))role.visible=false;
    // Keep movement, scaling and exit visibility produced by the original role actions.
  }
  for(const [id,track]of Object.entries(state.positionTracks)){
    const role=state.roles[id];role.nativeTargetX=role.x;role.nativeTargetY=role.y;
    if(track.steps.length){const end=nativePositionFrames(track).frames.at(-1);role.x=end.x;role.y=end.y;}
  }
  if(state.speakerIds.length&&state.roles[state.speakerIds[0]])state.talkingAxis=state.roles[state.speakerIds[0]].axis;
  if(state.motions.some(m=>(m.code===2001||m.code===2002)&&state.speakerIds.includes(m.id)))state.talkingAxis=2;
  state.routeChoices=routes(doc,talk);state.warnings=unique(state.warnings);return state;
}
// “初始站位”只改决定当前画面站位的那一条登场：人物记录会因换场景、退场或分支复位而重建，
// 重建之前的登场指令对当前画面已经无效，改它只会让预览不动并连带改动上一幕。
function roleEntry(doc,state,roleId){
 roleId=Number(roleId);const role=state?.roles?.[roleId];if(!role?.visible)return null;
 const talk=doc.talks?.[role.entryTalkId];
 if(talk){
  const rows=talk.roles||[];
  if(!role.entryImplicit)for(let j=rows.length-1;j>=0;j--){const command=rows[j];if(Number(command[0])===roleId&&[1001,1002,1003].includes(Number(command[1])))return {roleId,talkId:talk.id,index:j,axis:Number(command[3])||role.axis};}
  return {roleId,talkId:talk.id,index:-1,axis:role.axis,layer:role.layer,implicit:role.entryBlock||null};
 }
 // Legacy snapshots lack provenance. Replay native transitions once to recover
 // the live entry; guessed background cutoffs lose boundary-line or CG entries.
 let scene=blank(state.reference);
 for(const id of state.trace||[]){const row=doc.talks?.[id];if(row)scene=apply(doc,scene,row,role.grade,false);}
 if(scene.roles[roleId]?.entryTalkId!=null)return roleEntry(doc,scene,roleId);
 return null;
}
function setRoleEntry(talk,entry,axis){
 axis=Number(axis);if(!talk||!entry||![1,2,3].includes(axis))return false;
 if(entry.index>=0){const command=(talk.roles||[])[entry.index];if(!command)return false;while(command.length<4)command.push(0);command[3]=axis;return true;}
 if(entry.implicit?.length){talk.roles=entry.implicit.map(command=>{const copy=command.slice();if(Number(copy[0])===Number(entry.roleId))copy[3]=axis;return copy;});return true;}
 if(!Array.isArray(talk.roles))talk.roles=[];talk.roles.unshift([Number(entry.roleId),1001,entry.layer||1,axis,0]);return true;
}
// Plan against the FINAL native action order: adding even one command can
// redistribute slots. Keep all existing actions/timing and compensate positions
// only when native ordering actually moves an unrelated actor.
function planSceneDrag(selected,before,roleId,target,evaluate){
 const commands=copy(selected.roles||[]),desired=new Map([[roleId,target]]);
 const visible=Object.values(before.roles).filter(r=>r.visible);
 function ensure(id){for(const code of [3004,3008])if(!commands.some(r=>Number(r[0])===id&&Number(r[1])===code))commands.push(code===3004?[id,code,0,0,0,.4]:[id,code,0,0,0]);}
 function adjust(state){const ordered=nativeRoleOrder(commands);for(const [id,want] of desired)for(const [axis,code]of [['x',3004],['y',3008]]){
   const delta=want[axis]-state.roles[id][axis];if(Math.abs(delta)<.01)continue;
   const first=ordered.find(r=>Number(r[0])===id&&Number(r[1])===code),key=JSON.stringify(first),row=commands.find(r=>JSON.stringify(r)===key);
   row[2]=Math.round(((Number(row[2])||0)+delta)*1000)/1000;
 }}
 ensure(roleId);
 for(let pass=0;pass<8;pass++){
   const state=evaluate(commands);let expanded=false;
   for(const role of visible){const actual=state.roles[role.id];if(!actual?.visible)throw Error('拖动会改变人物登场状态，已保留原位置。');
    if(role.id!==roleId&&!desired.has(role.id)&&(Math.abs(actual.x-role.x)>.01||Math.abs(actual.y-role.y)>.01)){
     // Reserve both axes for every actor once, so later corrections never change
     // the list length (and therefore never trigger another sorting boundary).
     for(const r of visible){desired.set(r.id,r.id===roleId?target:{x:r.x,y:r.y});ensure(r.id);}const groups=new Map();for(const row of commands){const key=Number(row[0]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}commands.splice(0,commands.length,...[...groups.values()].flat());
     expanded=true;break;
    }
   }
   if(expanded)continue;
   if([...desired].every(([id,p])=>Math.abs(state.roles[id].x-p.x)<.05&&Math.abs(state.roles[id].y-p.y)<.05))return commands;
   adjust(state);
 }
 throw Error('当前动作组合无法安全调整位置，已保留原指令。');
}
const diskStageCaches=new WeakMap();
function reconstruct(doc,target,options={}) {
  const remote=globalThis.StudentAgeRemoteTalks?.info(doc.talks),source=doc.talks;
  const cacheKey=remote?(globalThis.StudentAgeIndexedTalks?.stringify||JSON.stringify)([remote.graphVersion,options.grade,options.reference,options.roots,options.event,doc.protagonistGender,doc.persons,doc.faces,doc.backgrounds,doc.options,doc.branchFolders]):null;
  if(remote)doc={...doc,talks:StudentAgeRemoteTalks.sceneTable(doc.talks,target)};
  const roots=options.roots?.length?options.roots:Object.values(doc.events||{}).flatMap(e=>list(e.talkId));
  const route=options.trace?{path:options.trace,found:true}:pathTo(doc,target,roots);
  let state=blank(options.reference||[2560,1440]),trace=[],start=0;
  const event=options.event||Object.values(doc.events||{}).find(e=>list(e.talkId).includes(route.path[0]));
  if(event&&[70,71].includes(Number(event.type)))state.phoneEvent=copy(event);
  let cache=remote?diskStageCaches.get(source):null;
  if(remote&&cache?.key!==cacheKey){cache={key:cacheKey,path:[],points:[],bytes:0};diskStageCaches.set(source,cache);}
  if(cache){let common=0;while(common<Math.min(cache.path.length,route.path.length)&&cache.path[common]===route.path[common])common++;const checkpoint=cache.points.filter(p=>p.index<=common&&p.index<route.path.length).at(-1);if(checkpoint){start=checkpoint.index;state=copy(checkpoint.state);trace=checkpoint.trace.slice();}cache.points=cache.points.filter(p=>p.index<=start);cache.bytes=cache.points.reduce((n,p)=>n+p.bytes,0);cache.path=route.path.slice();}
  for(let index=start;index<route.path.length;index++){const id=route.path[index],talk=doc.talks?.[id];if(talk){if(state.talkId!==null&&routes(doc,doc.talks[state.talkId]).some(r=>r.id===Number(id)&&r.reset)){state=blank(options.reference||[2560,1440]);trace=[];}state=apply(doc,state,talk,options.grade??1,false);trace.push(talk.id);}
    if(cache&&(index+1)%64===0){const point={index:index+1,state:copy(state),trace:trace.slice()};point.state.content='';point.bytes=JSON.stringify(point).length*2;cache.points.push(point);cache.bytes+=point.bytes;while(cache.points.length>64||cache.bytes>4*1024*1024){const old=cache.points.shift();cache.bytes-=old.bytes;}}
  }
  state.trace=trace;
  if(route.inferred)state.warnings.push('这段尚未设置事件入口，按已连接的前后对话还原。');
  if(!route.found&&state.talkId!==null)state.warnings.push('找不到通向这句的事件入口。这里只能从这句开始还原，前一幕状态未知。');
  if(!options.trace&&route.path.some((id,index)=>index<route.path.length-1&&routes(doc,doc.talks[id]).filter(r=>r.available).length>1))state.warnings.push('这句之前有分支；当前按可到达的路线还原。播放时可选择另一条路线。');
  return state;
}
function portraitSource(doc,role) {
  const person=doc.persons?.[role.id];if(!person)return {path:null,exact:false,missing:false};
  const index=Number(role.id)===0?protagonistGender(doc)-1:0;
  const young=(role.grade===0&&person.url?.length)||(role.grade===1&&!person.url2?.length);
  const face=doc.faces?.[role.id*1000+role.cloth*100+role.face],base=doc.faces?.[role.id*1000+role.cloth*100];
  // Match RoleMgr.GetExpressionIcon exactly: an existing row with an empty
  // grade image goes straight to PersonCfg. Its missing-row fallback uses
  // the opposite grade field; do not silently substitute a different image.
  const exact=face&&(young?face.icon_xx:face.icon),expression=face?exact:base&&(young?base.icon:base.icon_xx);
  const models=role.grade===0?person.l2d:person.l2d2,hasModel=!!models?.some(value=>typeof value==='string'&&value.trim());
  return {path:expression||(young?person.url?.[index]:person.url2?.[index])||null,exact:!!exact,hasModel,missing:!hasModel&&!exact&&(!!face||!!base||role.face!==0)};
}
function portraitCandidates(doc,role) {
  const person=doc.persons?.[role.id];if(!person)return [];
  const image=portraitSource(doc,role).path;
  const models=role.grade===0?person.l2d:person.l2d2;
  if(!models?.some(value=>typeof value==='string'&&value.trim()))return image?[image]:[];
  const cache=`portrait-cache/${portraitIdentity(doc,role.id)}-${role.grade}-${role.cloth}-${role.face}.png`;
  return unique(image&&/^(Mods|Textures|StudentAgeStudio)[\\/]/i.test(image)?[image,cache]:[cache,`portrait-cache/${portraitIdentity(doc,role.id)}-${role.grade}-${role.cloth}-0.png`,...(image?[image]:[])]);
}
function backgroundPath(doc,state) {
  const bg=doc.backgrounds?.[state.background];if(!bg)return null;
  const grade=Object.values(state.roles).find(r=>r.visible)?.grade??1;
  return grade>0&&bg.gaozhongUrl&&doc.backgrounds[bg.gaozhongUrl]?.url||bg.url;
}

// Original Cell_NewTalkRoleItem uses a bottom-centred actor origin; artwork
// retains its own model/image pivot and PersonCfg transform in canvas units.
// Native bubble resources are shared; every renderer waiting for them is notified.
const bubbleAssetStates=new Map();
function bubbleAssets(urls,onReady){
 let state=bubbleAssetStates.get(urls.manifest);
 if(!state){state={manifest:null,image:'',emoji:'',failed:false,listeners:new Set(),pending:false,retryAt:0};bubbleAssetStates.set(urls.manifest,state);}
 if(onReady&&!state.manifest)state.listeners.add(onReady);
 if(!state.manifest&&!state.pending&&Date.now()>=state.retryAt){state.pending=true;
  fetch(urls.manifest,{headers:urls.headers||{}}).then(r=>r.ok?r.json():Promise.reject(new Error(String(r.status)))).then(async manifest=>{
   const image=urls.resource('bubble.png'),emoji=urls.resource('emoji.png');
   await Promise.all([image,emoji].map(src=>new Promise((resolve,reject)=>{const img=new Image();img.onload=resolve;img.onerror=reject;img.src=src;})));
   state.manifest=manifest;state.image=image;state.emoji=emoji;state.failed=false;
  }).catch(()=>{state.failed=true;state.retryAt=Date.now()+3000;}).finally(()=>{state.pending=false;for(const fn of state.listeners)fn();state.listeners.clear();});
 }
 return state;
}
// A closed preview must not be retained by an unfinished/failed shared request.
function releaseBubbleAssets(onReady){if(onReady)for(const state of bubbleAssetStates.values())state.listeners.delete(onReady);}
// CfgExtension.GetBubblePos + TalkRoleItem.SetData; missing female slot is 1080, not the male slot.
function bubbleY(person,grade,female){
 if(!person.bubbleParm?.length&&!person.bubbleParm2?.length)return 1150;
 let p=grade===0?person.bubbleParm:(person.bubbleParm2?.length?person.bubbleParm2:person.bubbleParm);
 if(grade===0){if(person.url?.length)p=person.bubbleParm;else if(person.url2?.length)p=person.bubbleParm2;}
 else if(person.url2?.length)p=person.bubbleParm2;else if(person.url?.length)p=person.bubbleParm;
 return Number.isFinite(p?.[female?1:0])?p[female?1:0]:1080;
}
function bubbleGlyph(manifest,index){
 const e=manifest.emoji,c=e?.characters?.[index],g=e?.glyphs?.find(g=>g.m_Index===c?.m_GlyphIndex);if(!g)return null;
 const f=e.fontFace,s=e.spriteFace,fontScale=e.fontSize/f.m_PointSize*f.m_Scale,metrics=g.m_Metrics;
 const scale=c.m_Scale*g.m_Scale*(s.m_PointSize>0?e.fontSize/s.m_PointSize*s.m_Scale:f.m_AscentLine/metrics.m_Height*fontScale);
 return {rect:g.m_GlyphRect,scale,width:metrics.m_Width*scale,height:metrics.m_Height*scale,advance:metrics.m_HorizontalAdvance*scale,bearingX:metrics.m_HorizontalBearingX*scale,bottom:(metrics.m_HorizontalBearingY-metrics.m_Height)*scale,ascender:s.m_PointSize>0?s.m_AscentLine*scale:f.m_AscentLine*fontScale,descender:s.m_PointSize>0?s.m_DescentLine*scale:f.m_DescentLine*fontScale};
}
// TalkRoleItem.OnCellCreate selects NativeSize. Use original texture metadata,
// because cached preview pixels may be smaller than the native sprite.
// SetPosY operates on anchoredPosition; icon_role anchors at the centre of a
// 100-unit cell with bottom pivot, so both portrait and bubble gain 50 units.
const portraitFrames=new Map(),portraitSizes=new Map();
function staticPortraitSize(img,path=''){return portraitSizes.get(path)||[img?.naturalWidth||1,img?.naturalHeight||1];}
// A cached portrait path names the exact identity/grade/cloth it was rendered
// for. While a replacement (new cloth, grade or gender) is still rendering, the
// retained image must keep the geometry of the set it belongs to.
function portraitCacheKey(path){const m=/^portrait-cache\/((?:[0-9]+|0-female))-([0-9]+)-([0-9]+)-([0-9]+)\.png$/.exec(path||'');return m?{identity:m[1],grade:Number(m[2]),cloth:Number(m[3]),face:Number(m[4]),female:m[1]==='0-female',key:`${m[1]}-${m[2]}-${m[3]}`}:null;}
function portraitBox(doc,role,img,path=''){
  const person=doc.persons?.[role.id]||{},cached=portraitCacheKey(path);
  const female=cached?cached.female:Number(role.id)===0&&protagonistGender(doc)===2;
  const grade=cached?cached.grade:role.grade;
  const frame=portraitFrames.get(cached?cached.key:`${portraitIdentity(doc,role.id)}-${role.grade}-${role.cloth}`);
  const models=grade===0?person.l2d:person.l2d2;
  const params=(grade===0?person.l2dParm:person.l2dParm2)?.[female?1:0];
  const bounds=frame?.bounds;
  if(cached&&models?.length&&Array.isArray(params)&&Array.isArray(bounds)&&bounds.length===4&&bounds.every(Number.isFinite)&&bounds[2]>0&&bounds[3]>0){
    const scale=Number(params[0]),flip=Number(params[3])===1?-1:1;
    if(Number.isFinite(scale)&&scale>0)return {x:(Number(params[1])||0)+flip*(bounds[0]+bounds[2]/2)*scale,bottom:(Number(params[2])||0)+bounds[1]*scale,width:bounds[2]*scale,height:bounds[3]*scale,flip};
  }
  if(img?.naturalWidth&&!cached){
    const young=role.grade===0?person.url?.length:!person.url2?.length;
    const values=(young?person.urlParm:person.urlParm2)||[],offset=female&&values.length>=6?3:0;
    const scale=Number.isFinite(Number(values[offset+2]))?Number(values[offset+2]):1;
    const [width,height]=staticPortraitSize(img,path);
    return {x:Number(values[offset])||0,bottom:50+(Number(values[offset+1])||0)-height*scale/2,width:width*scale,height:height*scale,flip:1};
  }
  // Only while a model's geometry is being read, retain the previous fallback.
  const height=1152,width=img?.naturalWidth?height*img.naturalWidth/img.naturalHeight:500;
  return {x:0,bottom:0,width,height,flip:1,fallback:true};
}

class Renderer {
  constructor(container,options={}){
    this.container=container;this.options=options;this.actors=new Map();this.assetWarnings=new Map();this.drag=null;this.state=null;this.imageLoads=new WeakMap();this.assetEpoch=0;this.pendingDraw=null;this.drawVersion=0;this.exitAnimations=new Map();this.listeners=[];this.disposed=false;
    container.classList.add('story-scene');container.innerHTML='<div class="scene-backdrop"></div><div class="scene-phone-backdrop" hidden></div><div class="scene-phone-divider" hidden></div><div class="scene-background-label"></div><div class="scene-actors"></div><div class="scene-cg-layer"></div><div class="scene-empty-cast">当前还没有登场的人物</div><div class="scene-dialogue"><button type="button" class="scene-speaker-name" data-scene-choose-speaker><strong></strong></button><p></p><textarea class="scene-dialogue-content" data-edit="content" aria-label="当前对话内容" placeholder="在这里输入对话…" rows="3" hidden></textarea></div><div class="scene-route-overlay" hidden></div><div class="scene-guides"><span>左侧</span><span>中间</span><span>右侧</span></div><div class="scene-paper-overlay" hidden><canvas aria-label="纸条"></canvas></div>';
    this.actorLayer=container.querySelector('.scene-actors');
    // One bitmap plane for the entire cast. Per-actor CSS filters/animated layers
    // can reuse stale WebKit tiles when the editor's stage becomes fullscreen.
    this.castCanvas=document.createElement('canvas');this.castCanvas.className='scene-cast-canvas';this.castCanvas.setAttribute('aria-hidden','true');container.insertBefore(this.castCanvas,this.actorLayer);
    this.castContext=this.castCanvas.getContext('2d');this.rasterFrame=null;this.rasterSignature='';this.shadedImages=new WeakMap();this.castImageSequence=0;
    container.classList.toggle('scene-flat-cast',!!this.castContext);
    this.resizeObserver=new ResizeObserver(()=>{this.updateUIScale();if(this.state)for(const [id,node] of this.actors){const role=this.state.roles[id];if(role)this.position(node,role,this.state.reference);}this.queueCast();});this.resizeObserver.observe(container);
    this.dialogue=container.querySelector('.scene-dialogue');this.dialogueInput=this.dialogue.querySelector('textarea');this.speakerButton=this.dialogue.querySelector('.scene-speaker-name');
    if(container.id==='large-scene')this.dialogueInput.id='scene-dialogue-content';
    // Content writes belong to the application's delegated input listener. The
    // renderer keeps these nodes stable, including while IME text is composing.
    this.dialogueInput.addEventListener('compositionstart',()=>{this.dialogueComposing=true;});
    this.dialogueInput.addEventListener('compositionend',()=>{this.dialogueComposing=false;});
    this.speakerButton.addEventListener('click',event=>{if(this.dialogueEditable)this.options.onChooseSpeaker?.(event);});
    const listen=(target,type,handler)=>{target.addEventListener(type,handler);this.listeners.push(()=>target.removeEventListener(type,handler));};
    listen(container,'pointerdown',e=>this.pointerDown(e));
    listen(window,'pointermove',e=>this.pointerMove(e));listen(window,'pointerup',e=>this.pointerUp(e));
    listen(window,'pointercancel',e=>{if(this.drag?.pointer===e.pointerId&&!this.drag.node.hasPointerCapture?.(e.pointerId))this.cancelDrag();});
    listen(window,'lostpointercapture',e=>{if(this.drag?.pointer===e.pointerId&&!this.drag.node.hasPointerCapture?.(e.pointerId))this.cancelDrag();});
    listen(window,'blur',()=>this.cancelDrag());listen(window,'resize',()=>this.cancelDrag());
    listen(document,'visibilitychange',()=>{if(document.hidden)this.cancelDrag();});
    listen(container,'contextmenu',e=>this.contextMenu(e));
  }
  image(parent,paths,className,alt,onFailure,onSuccess,canInstall){
    const previous=parent.querySelector('img'),keep=!!(previous?.complete&&previous.naturalWidth>0);
    const epoch=this.assetEpoch,img=document.createElement('img'),load={img};this.imageLoads.set(parent,load);
    const current=()=>!this.disposed&&this.imageLoads.get(parent)===load;
    const failure=()=>{if(!current())return;const retained=keep&&parent.classList.contains('scene-actor-art');if(!retained)parent.replaceChildren();parent.classList.add('asset-missing');onFailure?.(retained);};
    if(!paths.length){failure();return;}
    const firstUrl=this.options.assetUrl(paths[0]);
    if(keep&&previous.dataset.sceneAssetEpoch===String(epoch)&&previous.src===new URL(firstUrl,document.baseURI).href){load.install=()=>{if(!current()||canInstall&&!canInstall(previous,paths[0]))return;load.install=null;previous.dataset.scenePath=paths[0];parent.classList.remove('asset-missing');onSuccess?.(paths[0]);};load.install();return;}
    img.dataset.sceneAssetEpoch=String(epoch);img.className=className;img.alt=alt;img.draggable=false;let index=0;
    // Keep the last decoded portrait until the replacement is ready. Late callbacks
    // from superseded face/cache requests must never clear the current image.
    img.onload=async()=>{if(!current())return;try{await img.decode?.();}catch{if(!img.naturalWidth){img.onerror();return;}}if(!current())return;
      img.dataset.scenePath=paths[index];
      // A bitmap may finish before its native bounds. Keep the previous image
      // until both are ready, then install and position in the same task.
      load.install=()=>{if(!current()||canInstall&&!canInstall(img,paths[index]))return;load.install=null;parent.replaceChildren(img);parent.classList.remove('asset-missing');onSuccess?.(paths[index]);};load.install();
    };
    img.onerror=()=>{if(!current())return;if(++index<paths.length)img.src=this.options.assetUrl(paths[index]);else failure();};img.src=firstUrl;
  }

  draw(doc,state,{edit=false,animate=false,fromState=null,textEffects=!edit}={}) {
    if(this.disposed)return;
    if(this.doc&&this.doc!==doc)this.invalidateAssets(true);
    if(this.drag){const role=state.roles[this.drag.role.id];
      if(doc===this.doc&&state.talkId===this.drag.talkId&&edit&&role?.visible&&['x','y','scale'].every(key=>role[key]===this.drag.role[key])){this.pendingDraw={doc,state,options:{edit,animate}};return;}
      this.cancelDrag(false);
    }
    this.pendingDraw=null;this.drawVersion++;this.doc=doc;const previous=fromState||this.state;this.state=state;this.edit=edit;this.drawOptions={edit,animate};this.updateUIScale();
    for(const [id,exit] of this.exitAnimations){if(!animate||state.roles[id]?.visible||previous?.talkId!==state.talkId){this.exitAnimations.delete(id);exit.animation.cancel();exit.node.remove();}}

    this.container.classList.toggle('scene-editing',edit);this.container.classList.toggle('scene-playing',animate);
    this.container.querySelector('.scene-guides').hidden=!edit||!!state.phone;
    this.container.classList.toggle('scene-phone',!!state.phone);
    const phoneBackdrop=this.container.querySelector('.scene-phone-backdrop');phoneBackdrop.hidden=!state.phone;this.container.querySelector('.scene-phone-divider').hidden=!state.phone;
    phoneBackdrop.style.left=state.phone?.localRight===false?'50%':'0';
    const phonePath=state.phone?backgroundPath(doc,{...state,background:state.phone.left}):null;
    if(phonePath!==this.phoneBackground){this.phoneBackground=phonePath;this.image(phoneBackdrop,phonePath?[phonePath]:[],'','通话对象的场景');}
    const bgPath=backgroundPath(doc,state),backdrop=this.container.querySelector('.scene-backdrop'),bgLabel=this.container.querySelector('.scene-background-label');
    if(bgPath!==this.background){this.background=bgPath;bgLabel.textContent='';this.image(backdrop,bgPath?[bgPath]:[],'',doc.backgrounds?.[state.background]?.name||'背景',()=>{bgLabel.textContent=state.background?(doc.backgrounds?.[state.background]?.name||'场景')+' · 素材尚未导出':'未设置场景背景';});}
    const cgPath=doc.cgs?.[state.cg]?.urls?.[0],cgLayer=this.container.querySelector('.scene-cg-layer');cgLayer.hidden=!state.cg;
    if(cgPath!==this.cg){this.cg=cgPath;this.image(cgLayer,cgPath?[cgPath]:[],'',doc.cgs?.[state.cg]?.name||'CG',()=>{if(state.cg){const text=document.createElement('span');text.textContent=(doc.cgs?.[state.cg]?.name||'CG')+' · 素材尚未导出';cgLayer.append(text);}});}
    const visible=Object.values(state.roles).filter(r=>r.visible);
    const exiting=animate?Object.values(state.roles).filter(r=>!r.visible&&state.motions.some(m=>m.id===r.id&&(m.code===2001||m.code===2002))&&(previous?.roles[r.id]?.visible||state.motions.some(m=>m.id===r.id&&m.code>=1001&&m.code<=1003))):[];
    const rendered=[...visible,...exiting],renderedIds=new Set(rendered.map(r=>r.id));
    for(const [id,node] of this.actors)if(!renderedIds.has(id)){this.assetWarnings.delete(id);this.actors.delete(id);node.remove();}
    for(const role of rendered){let node=this.actors.get(role.id);
      if(!node){node=document.createElement('div');node.className='scene-actor';node.dataset.role=String(role.id);node.innerHTML='<div class="scene-actor-art"></div><span class="scene-actor-emoji" hidden></span><span class="scene-actor-name"></span><span class="scene-drag-tag">拖动位置</span><span class="scene-asset-note"></span>';this.actorLayer.append(node);this.actors.set(role.id,node);}
      node.querySelector('.scene-actor-name').textContent=label(doc,role.id);node.classList.toggle('scene-speaker',state.highlightIds.includes(role.id));
      // The editor displays the end pose. Animation must use this dialogue's
      // reconstructed starting pose, not whichever pose a UI refresh last drew.
      node.getAnimations?.().forEach(a=>a.cancel());node.scenePositionAnimations=new Map();node.sceneMotionState=null;node.style.transition='none';
      this.position(node,role,state.reference);node.style.zIndex=String(10-(role.depth||0));
      const art=node.querySelector('.scene-actor-art');art.getAnimations?.().forEach(a=>a.cancel());
      this.updateActorImage(doc,role,node);
      const flipMotion=state.motions.find(m=>m.id===role.id&&(m.code===3005||m.code===3007)),start=state.motionStarts?.[role.id]||role;
      art.style.transition='none';art.style.transform=`scaleX(${this.artBox(node,role).flip*(role.flip?-1:1)})`;art.style.filter='none';
      if(animate&&flipMotion&&!!start.flip!==!!role.flip)art.animate?.([{transform:`scaleX(${this.artBox(node,role).flip*(start.flip?-1:1)})`},{transform:art.style.transform}],{duration:flipMotion.code===3005?50:1,delay:Math.max(0,flipMotion.delay)*1000,fill:'backwards'});
      if(animate)this.animatePosition(node,role,state);
      const pixelScale=this.unitScale(state.reference);
      if(animate)for(const m of state.motions.filter(m=>m.id===role.id)){
        if(m.code===3001)art.animate?.([{translate:'0 0'},{translate:`0 ${-Math.min(100,m.power*10*pixelScale*role.scale)}px`},{translate:'0 0'}],{duration:400/m.count,iterations:m.count,delay:m.delay*1000});
        const shaking=m.code===3002?m.duration:m.shake;if(shaking>0){const power=Math.max(2,25*pixelScale*role.scale);art.animate?.([{translate:'0 0'},{translate:`${-power}px ${power*.3}px`},{translate:`${power}px ${-power*.3}px`},{translate:'0 0'}],{duration:130,iterations:Math.max(1,Math.round(shaking*1000/130)),delay:m.delay*1000});}
      }
    }
    // Exit keeps the actor alive for its preceding effects and delay. Animate out
    // after those effects, then remove only this exact node (never a restored one).
    for(const role of exiting){const id=role.id,node=this.actors.get(id);if(!node)continue;
      const motion=state.motions.find(m=>m.id===id&&(m.code===2001||m.code===2002));
      // Position already uses the shared native sequence above. Both native exit
      // types fade linearly in 150 ms, independently of the movement duration.
      const animation=node.animate([{opacity:1},{opacity:0}],{duration:150,delay:Math.max(0,motion.delay||0)*1000,fill:'forwards',easing:'linear'}),exit={node,animation};this.exitAnimations.set(id,exit);this.actors.delete(id);
      const pending=node.getAnimations().map(a=>a.finished.catch(()=>{}));
      Promise.all(pending).then(()=>{if(this.exitAnimations.get(id)===exit){this.exitAnimations.delete(id);node.remove();this.queueCast();}});
    }
    this.container.querySelector('.scene-empty-cast').hidden=rendered.length>0||!!state.cg;
    this.drawDialogue(state,edit,textEffects);this.drawPaper(state,doc);window.StudentAgeScreenEffects?.draw(this,doc,state,animate);
    this.options.onAssetStatus?.([...this.assetWarnings.values()]);this.options.onStatus?.(state);this.queueCast();return state;
  }
  get paperVisible(){return !!this.state?.paperId&&this.paperClosed!==this.state.talkId;}
  dismissPaper(){if(!this.paperVisible)return false;this.paperClosed=this.state.talkId;this.container.querySelector('.scene-paper-overlay').hidden=true;return true;}
  drawPaper(state,doc){
    if(this.paperTalk!==state.talkId){this.paperTalk=state.talkId;this.paperClosed=null;}
    const overlay=this.container.querySelector('.scene-paper-overlay');overlay.hidden=!this.paperVisible;
    if(!this.paperVisible)return;
    const paper=doc.papers?.[state.paperId];if(!paper){overlay.hidden=true;this.paperClosed=state.talkId;return;}
    overlay.onclick=e=>{e.stopPropagation();this.dismissPaper();this.options.onPaperClose?.();};
    const signature=JSON.stringify(paper);if(this.paperSignature===signature)return;this.paperSignature=signature;
    const canvas=overlay.querySelector('canvas'),scale=Math.max(1,Number(paper.scale)||1);
    canvas.style.width=`calc(${554*scale}px * var(--game-ui-scale))`;canvas.style.height=`calc(${558*scale}px * var(--game-ui-scale))`;
    window.StudentAgePreviewUI?.drawPaper(canvas,paper,doc);
  }
  queueCast(){
    if(this.disposed||!this.castContext||this.rasterFrame!==null)return;
    this.rasterFrame=requestAnimationFrame(()=>{this.rasterFrame=null;this.paintCast();});
  }
  shadeImage(img,shade){
    if(!shade)return img;
    let entry=this.shadedImages.get(img);if(entry?.shade===shade)return entry.canvas;
    if(!entry){const canvas=document.createElement('canvas');canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;entry={canvas,shade:null};this.shadedImages.set(img,entry);}
    const {canvas}=entry,ctx=canvas.getContext('2d');ctx.globalCompositeOperation='source-over';ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,0,0);ctx.globalCompositeOperation='source-atop';ctx.fillStyle=`rgba(0,0,0,${shade})`;ctx.fillRect(0,0,canvas.width,canvas.height);entry.shade=shade;return canvas;
  }
  paintCast(){
    if(this.disposed||!this.castContext||!this.state)return;
    const stage=this.stageRect(),dpr=Math.min(2,window.devicePixelRatio||1);
    if(stage.width<=0||stage.height<=0)return;
    const width=Math.max(1,Math.round(stage.width*dpr)),height=Math.max(1,Math.round(stage.height*dpr));
    let resized=false;if(this.castCanvas.width!==width||this.castCanvas.height!==height){this.castCanvas.width=width;this.castCanvas.height=height;resized=true;}
    const nodes=[...this.actors.entries(),...Array.from(this.exitAnimations,([id,exit])=>[id,exit.node])],rows=[];
    for(const [id,node] of nodes){
      const role=this.state.roles[id],art=node.querySelector('.scene-actor-art'),img=art?.querySelector('img');
      if(!role||!node.isConnected||!img?.complete||!img.naturalWidth)continue;
      const box=node.getBoundingClientRect(),style=getComputedStyle(art),rect=art.getBoundingClientRect();
      const matrix=new DOMMatrixReadOnly(style.transform==='none'?undefined:style.transform),flip=matrix.a;
      const fit=Math.min(box.width/img.naturalWidth,box.height/img.naturalHeight),w=img.naturalWidth*fit,h=img.naturalHeight*fit;
      if(!img.dataset.castFrameId)img.dataset.castFrameId=String(++this.castImageSequence);
      rows.push({id,img,shade:role.shadow?1:this.state.highlightIds.includes(id)?0:.38,
        x:rect.left+rect.width/2-stage.left,y:rect.bottom-stage.top,w,h,flip,opacity:Number(getComputedStyle(node).opacity),layer:Number(node.style.zIndex)||0});
    }
    rows.sort((a,b)=>a.layer-b.layer);
    const signature=JSON.stringify([width,height,!!this.state.phone,...rows.map(r=>[r.img.dataset.castFrameId,r.img.src,r.shade,r.x,r.y,r.w,r.h,r.flip,r.opacity,r.layer])]);
    if(resized||signature!==this.rasterSignature){
      this.rasterSignature=signature;const ctx=this.castContext;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.clearRect(0,0,stage.width,stage.height);
      for(const row of rows){if(!row.opacity||Math.abs(row.flip)<.00001)continue;ctx.save();if(this.state.phone){ctx.beginPath();ctx.rect((this.state.phone.local?.includes(row.id)!==(this.state.phone.localRight===false))?stage.width/2:0,0,stage.width/2,stage.height);ctx.clip();}ctx.globalAlpha=row.opacity;ctx.translate(row.x,row.y);ctx.scale(row.flip,1);ctx.drawImage(this.shadeImage(row.img,row.shade),-row.w/2,-row.h,row.w,row.h);ctx.restore();}
    }
    // Delayed animations are 'running' as well. Static scenes consume no RAF loop.
    if(nodes.some(([,node])=>node.getAnimations?.({subtree:true}).some(a=>a.playState==='running')))this.queueCast();
  }
  updateActorImage(doc,role,node){
    const art=node.querySelector('.scene-actor-art'),key=[role.id,role.grade,role.cloth,role.face,Number(role.id)===0?protagonistGender(doc):0,portraitCandidates(doc,role).join('|')].join('-');
      if(node.dataset.asset!==key){node.dataset.asset=key;this.assetWarnings.delete(role.id);node.querySelector('.scene-asset-note').textContent='';
        const retry=()=>{if(this.disposed||this.actors.get(role.id)!==node||node.dataset.asset!==key)return;node.dataset.asset='';const latest=this.state?.roles[role.id];if(latest?.visible)this.updateActorImage(this.doc,latest,node);};
        const scheduleRetry=()=>{const note=node.querySelector('.scene-asset-note');note.onclick=e=>{e.stopPropagation();node.sceneRetryCount=0;retry();};if((node.sceneRetryCount||0)<3){node.sceneRetryCount=(node.sceneRetryCount||0)+1;setTimeout(retry,1000*Math.pow(3,node.sceneRetryCount-1));}};
        const setAssetNote=(note,short)=>{if(node.dataset.asset!==key||(this.actors.get(role.id)!==node&&this.exitAnimations.get(role.id)?.node!==node))return;node.querySelector('.scene-asset-note').textContent=short||'';if(note)this.assetWarnings.set(role.id,note);else this.assetWarnings.delete(role.id);this.options.onAssetStatus?.([...this.assetWarnings.values()]);};
        // While a model's new cloth/grade renders, keep the retained Live2D frame
        // rather than swapping in the original static artwork with its own placement.
        let candidates=portraitCandidates(doc,role);const shown=art.querySelector('img'),person=doc.persons?.[role.id];
        if(shown?.complete&&shown.naturalWidth>0&&portraitCacheKey(shown.dataset.scenePath)&&(role.grade===0?person?.l2d:person?.l2d2)?.length)candidates=candidates.filter(p=>p.startsWith('portrait-cache/')||/^(Mods|Textures|StudentAgeStudio)[\\/]/i.test(p));
        this.image(art,candidates,'',label(doc,role.id),retained=>{scheduleRetry();if(retained){setAssetNote(label(doc,role.id)+' 的所选外观暂未读取，已保留原立绘。','点击重试');return;}const missing=document.createElement('div');missing.className='scene-missing-person';missing.textContent=label(doc,role.id)+'\n立绘未缓存';art.append(missing);setAssetNote(label(doc,role.id)+' 的立绘尚未读取，可以重试。','点击重试');},path=>{
          node.sceneRetryCount=0;node.querySelector('.scene-asset-note').onclick=null;
          const person=doc.persons?.[role.id],face=doc.faces?.[role.id*1000+role.cloth*100+role.face],young=(role.grade===0&&person?.url?.length)||(role.grade===1&&!person?.url2?.length),exact=face&&(young?face.icon_xx:face.icon);
          if(portraitSource(doc,role).missing)setAssetNote(label(doc,role.id)+' 的所选服装或学段缺少这张表情图片，当前按游戏备用规则显示。','表情图片缺失');else if(!path.startsWith('portrait-cache/')&&path!==exact&&(role.face!==0||role.cloth!==0))setAssetNote(label(doc,role.id)+' 当前显示默认立绘；正在读取所选表情或服装。','默认立绘');else setAssetNote('','');const current=this.state?.roles[role.id];if(current)this.position(node,current,this.state.reference);this.queueCast();
        },(img,path)=>{
          if(this.options.portraitGeometryPending?.(path))return false;
          // The fallback illustration and the Live2D frame have different native
          // geometry. Do not briefly display the illustration while the model
          // is still loading, then visibly resize it when the model arrives.
          if(!portraitCacheKey(path)&&! /^(Mods|Textures|StudentAgeStudio)[\\/]/i.test(path)&&this.options.portraitModelPending?.(role))return false;
          const cached=portraitCacheKey(path),person=doc.persons?.[role.id];
          const params=(cached?.grade===0?person?.l2dParm:person?.l2dParm2)?.[cached?.female?1:0];
          if(cached&&Number(params?.[0])>0&&portraitBox(doc,role,img,path).fallback)return false;
          // Retained artwork must keep its own grade/gender until its replacement installs.
          img.scenePortraitRole={...role};img.scenePortraitGender=protagonistGender(doc);return true;
        });
      }
      this.imageLoads.get(art)?.install?.();
  }
  refreshPortraits(){
    if(this.drag)return;
    if(this.disposed||!this.doc||!this.state)return;
    // Decoded images can arrive mid-motion. Replace only artwork, never redraw
    // positions or cancel the running Web Animations/exit lifecycle.
    for(const [id,node] of this.actors){const role=this.state.roles[id];if(role){this.updateActorImage(this.doc,role,node);this.position(node,role,this.state.reference);}}
    for(const [id,exit] of this.exitAnimations){const role=this.state.roles[id];if(role)this.updateActorImage(this.doc,role,exit.node);}
  }
  drawDialogue(state,edit,textEffects){
    const editable=!!(edit&&state.talkId!==null&&this.options.canEditDialogue?.()),input=this.dialogueInput;
    const changedTalk=this.dialogueTalkId!==state.talkId,content=String(state.content||''),focused=document.activeElement===input;
    this.dialogueEditable=editable;this.dialogue.classList.toggle('scene-dialogue-editable',editable);
    this.dialogue.dataset.cg=String(!!state.cg);if(state.cg)window.StudentAgePreviewUI?.loadCG();
    this.container.classList.toggle('scene-showing-cg',!!state.cg);
    this.dialogue.dataset.narration=String(!(state.speakerIds||[]).length);
    this.dialogue.dataset.speakerAxis=String(state.talkingAxis||1);
    this.dialogue.dataset.speakerGender=state.speakerGender===1?'male':state.speakerGender===2?'female':'neutral';
    const name=state.speaker||'旁白';this.speakerButton.querySelector('strong').textContent=name;
    this.speakerButton.disabled=!editable||!this.options.onChooseSpeaker;
    this.speakerButton.setAttribute('aria-label',editable?name+'，点击选择说话人':name);
    const paragraph=this.dialogue.querySelector('p');const display=content||(state.talkId===null?'选择一句对话，开始预览。':'');if(textEffects&&!edit&&window.StudentAgePreviewText)window.StudentAgePreviewText.render(paragraph,display);else paragraph.textContent=display;paragraph.hidden=editable;input.hidden=!editable;
    if(changedTalk)this.dialogueComposing=false;
    if(input.value!==content&&(changedTalk||!this.dialogueComposing&&(!focused||content!==this.dialogueContent))){
      const start=input.selectionStart,end=input.selectionEnd,direction=input.selectionDirection,scroll=input.scrollTop;input.value=content;
      if(focused&&!changedTalk){input.setSelectionRange(Math.min(start,content.length),Math.min(end,content.length),direction);input.scrollTop=scroll;}
    }
    this.dialogueTalkId=state.talkId;this.dialogueContent=content;
  }
  updateUIScale(){this.container.style.setProperty('--game-ui-scale',this.unitScale(this.state?.reference||[2560,1440]));}
  stageRect(){return (this.actorLayer||this.container).getBoundingClientRect();}
  unitScale(reference){const box=this.stageRect();return Math.min(box.width/reference[0],box.height/reference[1])||1;}
  artBox(node,role){if(this.drag?.node===node&&this.drag.art)return this.drag.art;const img=node.querySelector('.scene-actor-art img');const sourceRole=img?.scenePortraitRole||role,sourceDoc=img?.scenePortraitGender?{...this.doc,protagonistGender:img.scenePortraitGender}:this.doc;const box=portraitBox(sourceDoc,sourceRole,img,img?.dataset.scenePath||'');
    // Geometry still loading: keep the last resolved box for this actor rather than jumping to the generic size.
    if(box.fallback){const last=node.sceneLastBox;if(last&&last.id===role.id)return last.box;return box;}
    node.sceneLastBox={id:role.id,box};return box;}
  layout(node,role,reference){const box=this.stageRect(),unit=this.unitScale(reference),art=this.artBox(node,role),flip=role.flip?-1:1;
    return {left:(50+(role.x+art.x*role.scale*flip)*unit/box.width*100)+'%',bottom:((role.y+art.bottom*role.scale)*unit/box.height*100)+'%',height:(art.height*role.scale*unit/box.height*100)+'%',width:(art.width*role.scale*unit/box.width*100)+'%'};}
  position(node,role,reference){if(this.drag?.node===node)role={...role,x:this.drag.role.x+this.drag.dx,y:this.drag.role.y+this.drag.dy};Object.assign(node.style,this.layout(node,role,reference));const art=node.querySelector('.scene-actor-art');const transform=`scaleX(${this.artBox(node,role).flip*(role.flip?-1:1)})`;if(art.style.transform!==transform)art.style.transform=transform;this.positionEmoji(node,role);if(node.sceneMotionState)this.animatePosition(node,role,node.sceneMotionState,true);this.queueCast();}
  // Native cell RectTransform + TMP single-sprite middle/centre layout, not a Unicode emoji.
  positionEmoji(node,role){
    const bubble=node.querySelector('.scene-actor-emoji');if(!bubble)return;
    const index=Number.isInteger(role.emoji)&&role.emoji>=0?role.emoji:-1;
    this.bubbleReady??=()=>{if(!this.disposed&&this.state)this.refreshPortraits();};
    const assets=index>=0&&this.options.talkUi?bubbleAssets(this.options.talkUi,this.bubbleReady):null;
    const glyph=assets?.manifest?bubbleGlyph(assets.manifest,index):null;
    if(!glyph){bubble.sceneAnimation?.cancel();bubble.sceneAnimation=null;bubble.sceneVersion=null;bubble.hidden=true;return;}
    const m=assets.manifest,b=m.bubble,person=this.doc?.persons?.[role.id]||{},art=this.artBox(node,role),flip=role.flip?-1:1;
    const cell=m.cell,cp=cell.pivot,cs=cell.sizeDelta,pivot=b.pivot,w=b.sizeDelta[0],h=b.sizeDelta[1];
    const px=(b.anchorMin[0]-cp[0])*cs[0],py=(b.anchorMin[1]-cp[1])*cs[1]+bubbleY(person,role.grade,role.id===0&&protagonistGender(this.doc)===2);
    if(!(w>0&&h>0&&art.width>0&&art.height>0)){bubble.hidden=true;return;}
    Object.assign(bubble.style,{left:((px-pivot[0]*w-art.x*flip+art.width/2)/art.width*100)+'%',bottom:((py-pivot[1]*h-art.bottom)/art.height*100)+'%',width:w/art.width*100+'%',height:h/art.height*100+'%',transformOrigin:pivot[0]*100+'% '+(1-pivot[1])*100+'%',backgroundImage:'url("'+assets.image+'")'});
    const e=m.emoji,a=e.anchorMin,z=e.anchorMax,p=e.pivot,ew=(z[0]-a[0])*w+e.sizeDelta[0],eh=(z[1]-a[1])*h+e.sizeDelta[1];
    const ex=(a[0]+(z[0]-a[0])*p[0])*w+e.anchoredPosition[0]-p[0]*ew,ey=(a[1]+(z[1]-a[1])*p[1])*h+e.anchoredPosition[1]-p[1]*eh;
    let cellNode=bubble.querySelector('.scene-actor-emoji-glyph');if(!cellNode){cellNode=document.createElement('span');cellNode.className='scene-actor-emoji-glyph';cellNode.append(document.createElement('img'));bubble.append(cellNode);}
    Object.assign(cellNode.style,{left:(ex+(ew-glyph.advance)/2+glyph.bearingX)/w*100+'%',bottom:(ey+eh/2-(glyph.ascender+glyph.descender)/2+glyph.bottom)/h*100+'%',width:glyph.width/w*100+'%',height:glyph.height/h*100+'%'});
    const img=cellNode.firstElementChild,rect=glyph.rect,[aw,ah]=e.atlasSize;
    if(img.getAttribute('src')!==assets.emoji)img.src=assets.emoji;
    Object.assign(img.style,{width:aw/rect.m_Width*100+'%',height:ah/rect.m_Height*100+'%',left:-rect.m_X/rect.m_Width*100+'%',top:-(ah-rect.m_Y-rect.m_Height)/rect.m_Height*100+'%'});
    bubble.hidden=false;
    if(bubble.sceneVersion!==this.drawVersion){bubble.sceneVersion=this.drawVersion;bubble.sceneAnimation?.cancel();bubble.sceneAnimation=null;
      if(this.drawOptions?.animate)bubble.sceneAnimation=bubble.animate?.([{transform:'scale(0)'},{transform:'scale(1)'}],{duration:500,delay:Math.max(0,role.emojiDelay||0)*1000,fill:'backwards',easing:'cubic-bezier(0.333333333333,1.567193333333,0.666666666667,1)'});
    }
  }
  animatePosition(node,role,state,retarget=false){
    if(!node.animate)return;let start=state.motionStarts?.[role.id]||role;const motions=state.motions.filter(m=>m.id===role.id);
    const entry=motions.find(m=>m.code>=1001&&m.code<=1003),entering=entry&&!start.visible;
    if(!retarget){node.sceneMotionState=state;node.scenePositionAnimations??=new Map();}
    function tween(property,from,to,motion,duration=.4){
      const frames=[{[property]:from},{[property]:to}];
      if(retarget){const animation=node.scenePositionAnimations?.get(property);if(animation?.playState==='running'||animation?.playState==='paused')animation.effect.setKeyframes(frames);return;}
      if(from===to)return;node.scenePositionAnimations.set(property,node.animate(frames,{duration:Math.max(.001,motion?.duration||duration)*1000,delay:Math.max(0,motion?.delay||0)*1000,easing:'ease-out',fill:'backwards'}));
    }
    const from=this.layout(node,start,state.reference);let left=from.left,bottom=from.bottom;
    if(entering){tween('opacity',0,1,entry,entry.code===1002?.15:.4);if(entry.code===1001&&entry.fromAxis!==3)left=entry.fromAxis===1?'-35%':'135%';if(entry.code===1003)bottom=(parseFloat(from.bottom)-100)+'%';}
    const changeScale=motions.find(m=>m.code===3003),flip=motions.find(m=>m.code===3005||m.code===3007);
    const track=state.positionTracks?.[role.id];
    if(track?.steps.length){
      const timeline=nativePositionFrames(track),frames=timeline.frames.map(p=>{const box=this.layout(node,{...role,x:p.x,y:p.y},state.reference);return {left:box.left,bottom:box.bottom,offset:timeline.duration?p.time/timeline.duration:0};});
      if(frames.length===1)frames.push({...frames[0],offset:1});
      if(retarget){const animation=node.scenePositionAnimations?.get('position');if(animation&&(animation.playState==='running'||animation.playState==='paused'))animation.effect.setKeyframes(frames);}
      // layout() already stores the final pose. A forwards fill would keep an
      // obsolete endpoint above it after late portrait metadata or a resize.
      else node.scenePositionAnimations.set('position',node.animate(frames,{duration:Math.max(.001,timeline.duration)*1000,fill:'backwards',easing:'linear'}));
    }else{
      tween('left',left,node.style.left,motions.find(m=>m.code===3004)||entry||changeScale||flip,flip?.code===3007?.001:flip?.code===3005?.05:.4);
      tween('bottom',bottom,node.style.bottom,motions.find(m=>m.code===3008)||entry||changeScale);
    }
    const scale=motions.find(m=>m.code===3003);tween('height',from.height,node.style.height,scale);tween('width',from.width,node.style.width,scale);
  }
  setSelected(id){this.selected=id;for(const [role,node] of this.actors)node.classList.toggle('scene-selected',role===id);}
  showChoices(choices,onChoose){const panel=this.container.querySelector('.scene-route-overlay');panel.innerHTML='';panel.hidden=!choices.length;this.container.classList.toggle('scene-awaiting-choice',!!choices.length);
    if(choices.some(c=>c.conditional)){const note=document.createElement('p');note.className='scene-condition-note';note.textContent='预览不修改游戏数值，请选择要查看的条件路线。';panel.append(note);}
    for(const choice of choices){const b=document.createElement('button');b.textContent=choice.label+(choice.available?'':' · 当前模组中不可播放');b.disabled=!choice.available;b.onclick=event=>{event.stopPropagation();panel.hidden=true;this.container.classList.remove('scene-awaiting-choice');onChoose(choice);};panel.append(b);}
  }
  contextMenu(event){
    const target=event.target.closest('.scene-actor');
    if(!target){if(this.state?.cg&&this.edit&&this.options.onBeforeInteract?.()!==false&&this.options.onCGContextMenu){event.preventDefault();event.stopPropagation();this.options.onCGContextMenu(event.clientX,event.clientY);}return;}
    this.cancelDrag();if(this.options.onBeforeInteract?.()===false||!this.edit)return;
    const id=Number(target.dataset.role);if(!this.state.roles[id]?.visible)return;
    event.preventDefault();event.stopPropagation();this.options.onContextMenu?.(id,event.clientX,event.clientY);
  }
  pointerDown(event){
    const target=event.target.closest('.scene-actor');if(!target)return;
    if(event.button===2||(event.button===0&&event.ctrlKey)){this.contextMenu(event);return;}
    if(event.button!==0)return;this.cancelDrag();if(this.options.onBeforeInteract?.()===false||!this.edit)return;
    const role=this.state.roles[target.dataset.role],node=this.actors.get(Number(target.dataset.role));if(!role?.visible||!node)return;
    event.preventDefault();const rect=this.stageRect();if(rect.width<=0||rect.height<=0)return;
    const art=copy(this.artBox(node,role));
    this.drag={node,art,role:copy(role),talkId:this.state.talkId,doc:this.doc,reference:this.state.reference.slice(),rect,startX:event.clientX,startY:event.clientY,pointer:event.pointerId,dx:0,dy:0,moved:false};
    node.getAnimations?.().forEach(a=>a.cancel());node.querySelector('.scene-actor-art')?.getAnimations?.().forEach(a=>a.cancel());node.sceneMotionState=null;this.drag.unit=this.unitScale(this.drag.reference);this.drag.bounds=this.dragBounds(this.drag);
    try{node.setPointerCapture(event.pointerId);}catch{ /* Window listeners still finish drags when WebKit rejects capture. */ }
    node.classList.add('dragging');this.options.onSelectRole?.(role.id);
  }
  dragBounds(d){
    const rect=d.rect,unit=d.unit||this.unitScale(d.reference),art=this.artBox(d.node,d.role),width=art.width*d.role.scale*unit,height=art.height*d.role.scale*unit;
    const dialogue=this.dialogue.getBoundingClientRect(),bottom=Math.min(rect.bottom,Math.max(rect.top,dialogue.top));
    const grab=Math.max(1,Math.min(72,rect.width*.075,width*.75,height*.4,(bottom-rect.top)*.4));
    const dx=art.x*d.role.scale*(d.role.flip?-1:1),dy=art.bottom*d.role.scale;
    return {left:(grab-width/2-rect.width/2)/unit-dx,right:(rect.width/2+width/2-grab)/unit-dx,bottom:(rect.bottom-bottom-height+grab)/unit-dy,top:(rect.height-grab)/unit-dy};
  }
  pointerMove(event){
    const d=this.drag;if(!d||event.pointerId!==d.pointer)return;
    if(event.buttons!==undefined&&!(event.buttons&1)){this.cancelDrag();return;}
    const px=event.clientX-d.startX,py=event.clientY-d.startY;if(!Number.isFinite(px)||!Number.isFinite(py))return;
    if(!d.moved&&Math.hypot(px,py)<3)return;d.moved=true;const bounds=d.bounds;
    const x=Math.max(bounds.left,Math.min(bounds.right,d.role.x+px/d.unit)),y=Math.max(bounds.bottom,Math.min(bounds.top,d.role.y-py/d.unit));
    d.dx=x-d.role.x;d.dy=y-d.role.y;if(d.frame==null)d.frame=requestAnimationFrame(()=>{d.frame=null;if(this.drag===d)this.position(d.node,{...d.role,x:d.role.x+d.dx,y:d.role.y+d.dy},d.reference);});
  }
  releaseDrag(d){
    if(d.frame!=null)cancelAnimationFrame(d.frame);d.frame=null;d.node.classList.remove('dragging');try{if(d.node.hasPointerCapture?.(d.pointer))d.node.releasePointerCapture(d.pointer);}catch{}
  }
  pointerUp(event){
    const d=this.drag;if(!d||event.pointerId!==d.pointer||event.button!==0)return;
    this.drag=null;this.releaseDrag(d);const pending=this.pendingDraw;this.pendingDraw=null;const version=this.drawVersion;
    try{if(d.moved)this.options.onDrag?.(d.role.id,Math.round(d.dx),Math.round(d.dy),{talkId:d.talkId,doc:d.doc,x:d.role.x,y:d.role.y});}
    finally{if(this.drawVersion===version){const frame=pending||{doc:this.doc,state:this.state,options:{...this.drawOptions,animate:false}};this.draw(frame.doc,frame.state,frame.options);}}
  }
  cancelDrag(redraw=true){
    const d=this.drag;if(!d)return;this.drag=null;this.releaseDrag(d);this.position(d.node,d.role,d.reference);const pending=this.pendingDraw;this.pendingDraw=null;
    if(redraw&&pending)this.draw(pending.doc,pending.state,pending.options);
  }

  invalidateAssets(force=false){if(force)this.assetEpoch++;this.background=undefined;this.cg=undefined;this.assetWarnings.clear();for(const node of this.actors.values())node.dataset.asset='';}
  dispose(){releaseBubbleAssets(this.bubbleReady);this.cancelDrag(false);for(const animation of this.screenShakeAnimations||[])animation.cancel();this.screenShakeAnimations=[];this.disposed=true;cancelAnimationFrame(this.rasterFrame);this.resizeObserver?.disconnect();for(const remove of this.listeners)remove();for(const exit of this.exitAnimations.values())exit.animation.cancel();this.exitAnimations.clear();this.container.innerHTML='';this.actors.clear();}
}

class Player {
  constructor(options){this.options=options;this.trace=[];this.playing=false;this.timer=null;this.scene=null;this.ended=false;this.historyStarted=false;}
  get doc(){return this.options.getDoc();}
  select(id,trace=null){
    if(this.options.loadTalk&&globalThis.StudentAgeRemoteTalks?.info(this.doc.talks)&&!StudentAgeRemoteTalks.ready(this.doc.talks,id)){this.pause();const sequence=this.loadSequence=(this.loadSequence||0)+1,doc=this.doc.talks;this.options.loadTalk(id).then(()=>{if(sequence===this.loadSequence&&doc===this.doc.talks)this.select(id,trace);}).catch(error=>this.options.onWarning?.(error.message));return;}
    this.loadSequence=(this.loadSequence||0)+1;this.pause();this.ended=false;this.historyStarted=false;this.scene=reconstruct(this.doc,id,{...this.options.getContext(),trace:trace||undefined});this.trace=this.scene.trace.slice();this.render(false);}
  refresh(){if(this.trace.length){this.scene=reconstruct(this.doc,this.trace[this.trace.length-1],{...this.options.getContext(),trace:this.trace});this.render(false);}}
  choices(){return this.options.getChoices?.(this.scene)??this.scene.routeChoices??[];}
  render(animate,initial=false){this.options.onRender(initial?{...this.scene,transition:null}:this.scene,{animate,playing:this.playing,ended:this.ended});}
  recordStart(reason='play'){if(this.historyStarted||!this.scene?.talkId)return;this.historyStarted=true;this.options.onHistory?.({kind:'start',talkId:this.scene.talkId,reason,scene:copy(this.scene)});}
  play({initial=false}={}){if(!this.scene?.talkId)return;this.recordStart();this.ended=false;this.playing=true;this.resumeAfterChoice=false;this.render(true,initial);this.schedule();}
  pause(){this.playing=false;this.resumeAfterChoice=false;clearTimeout(this.timer);this.timer=null;this.options.onPlaying?.(false);}
  schedule(){clearTimeout(this.timer);if(!this.playing)return;const choices=this.choices();
    if(choices.length>1||choices.some(c=>c.conditional||c.type==='option'||c.type==='branch')){this.resumeAfterChoice=true;this.playing=false;this.options.onPlaying?.(false);this.options.onChoices?.(choices);return;}
    if(this.options.manual?.())return;
    const motionTime=Math.max(0,...(this.scene.motions||[]).map(m=>(Math.max(0,m.delay||0)+Math.max(.4,m.duration||0,m.shake||0))*1000));
    this.timer=setTimeout(()=>this.next(),Math.max(window.StudentAgeScreenEffects?.duration(this.scene)||0,motionTime,Math.min(10000,Math.max(2000,(this.scene.content||'').length*75+1100))));
  }
  next(){clearTimeout(this.timer);if(!this.scene)return;this.recordStart('next');const choices=this.choices();
    if(!choices.length){this.ended=true;this.pause();this.options.onHistory?.({kind:'end'});this.render(false);return;}
    if(choices.length>1||choices.some(c=>c.conditional||c.type==='option'||c.type==='branch')){const resume=this.playing;this.pause();this.resumeAfterChoice=resume;this.options.onChoices?.(choices);return;}
    if(!choices[0].available){this.pause();this.options.onChoices?.(choices);this.options.onWarning?.('下一句属于当前模组之外，载入对应内容后才能继续预览。');return;}
    this.choose(choices[0]);
  }
  async choose(route){if(!route.available)return;
    if(this.options.loadTalk&&!route.end){const sequence=this.loadSequence=(this.loadSequence||0)+1,scene=this.scene;try{await this.options.loadTalk(route.id);}catch(error){this.pause();this.options.onWarning?.(error.message);return;}if(sequence!==this.loadSequence||scene!==this.scene)return;}
this.recordStart('choice');if(route.optionId!==undefined||route.conditional||route.type==='alternate')this.options.onHistory?.({kind:'choice',route:copy(route)});if(route.end){this.ended=true;this.pause();this.options.onHistory?.({kind:'end'});this.render(false);return;}
    if(this.trace.length>=2000){this.pause();this.options.onWarning?.('这次预览已经经过很多句，请重置后继续。');return;}
    if(route.reset)this.trace=[];if(this.resumeAfterChoice){this.playing=true;this.resumeAfterChoice=false;}this.trace.push(route.id);this.scene=reconstruct(this.doc,route.id,{...this.options.getContext(),trace:this.trace});
    this.options.onHistory?.({kind:'line',talkId:route.id,scene:copy(this.scene)});this.options.onSelect?.(route.id);this.render(true);if(this.playing)this.schedule();
  }
  back(){this.pause();this.ended=false;if(this.trace.length<2)return;this.trace.pop();this.scene=reconstruct(this.doc,this.trace[this.trace.length-1],{...this.options.getContext(),trace:this.trace});this.options.onSelect?.(this.scene.talkId);this.render(false);}
  reset(){this.pause();this.ended=false;const roots=this.options.getContext().roots||[],id=roots[0]||this.trace[0];if(id){this.select(id);this.recordStart('replay');this.options.onSelect?.(id);}}
  dispose(){this.pause();}
}
class AudioPlayer {
  constructor(options){this.options=options;this.bgm=null;this.group=null;this.nativeBgm=null;this.sfx=[];this.lastTalk=null;this.pendingMusic=null;this.desiredMusic=null;this.failedMusic=null;}
  create(id,volume,loop=false,resource){const url=resource===undefined?this.options.getUrl(Number(id)):resource;if(!url){this.options.onWarning?.('所选声音尚未读取到本地，无法试听。');return null;}const audio=this.options.createAudio?this.options.createAudio(url):new Audio(url);window.StudentAgeAudioFocus?.track(audio);audio.volume=Math.max(0,Math.min(1,Number.isFinite(Number(volume))?Number(volume):1));audio.loop=!!loop;audio.play()?.catch?.(()=>this.options.onWarning?.('声音未能播放，请检查本地素材。'));return audio;}
  cancelPendingMusic(){const pending=this.pendingMusic;if(!pending)return;this.pendingMusic=null;pending.audio.removeEventListener?.('error',pending.fail);pending.audio.pause();}
  switchMusic(key,track){
    const attempt=JSON.stringify([key,track?.url||null]);
    if(this.desiredMusic?.attempt!==attempt)this.failedMusic=null;
    this.desiredMusic={key,track,attempt};
    const configure=audio=>{audio.volume=Math.max(0,Math.min(1,Number.isFinite(Number(track?.volume))?Number(track.volume):1));audio.loop=!!track?.loop;};
    if(key&&track?.url&&this.bgm&&this.currentMusicUrl===track.url){this.cancelPendingMusic();configure(this.bgm);this.group=key;return;}
    if(key&&track?.url&&this.pendingMusic?.url===track.url){this.pendingMusic.key=key;this.pendingMusic.attempt=attempt;configure(this.pendingMusic.audio);return;}
    if(this.pendingMusic?.attempt!==attempt)this.cancelPendingMusic();
    if(!key){this.bgm?.pause();this.bgm=null;this.group=null;return;}
    if(this.pendingMusic||this.failedMusic===attempt)return;
    const warn=()=>{this.failedMusic=attempt;this.options.onWarning?.(this.bgm?'本句背景音乐未能读取，继续播放上一首音乐。':'本句背景音乐未能读取，请检查对应素材。');};
    if(!track?.url){warn();return;}
    let audio;
    try{audio=this.options.createAudio?this.options.createAudio(track.url):new Audio(track.url);}
    catch{warn();return;}
    window.StudentAgeAudioFocus?.track(audio);audio.volume=Math.max(0,Math.min(1,Number.isFinite(Number(track.volume))?Number(track.volume):1));audio.loop=!!track.loop;
    const pending={key,attempt,audio,url:track.url};this.pendingMusic=pending;
    const fail=()=>{if(this.pendingMusic!==pending)return;this.cancelPendingMusic();warn();};pending.fail=fail;
    // The game keeps the old channel until the replacement clip has loaded.
    // A missing URL, decode error or rejected play must not silence that channel.
    const ready=()=>{
      if(this.pendingMusic!==pending){audio.pause();return;}
      audio.removeEventListener?.('error',fail);this.pendingMusic=null;
      this.bgm?.pause();this.bgm=audio;this.group=pending.key;this.currentMusicUrl=pending.url;this.failedMusic=null;
    };
    audio.addEventListener?.('error',fail,{once:true});
    try{const playing=audio.play();if(playing?.then)playing.then(ready,fail);else ready();}catch{fail();}
  }
  musicAt(talkId,index=null){
    const cues=this.options.getCues()||{},group=index?index.get(Number(talkId)):(cues.bgm||[]).find(g=>(g.talkIds||[]).some(id=>Number(id)===Number(talkId)));
    if(group&&Number(group.audioId)===0)return false;
    if(group){this.activeGroup=group;this.nativeBgm=null;return true;}
    const preserved=Number(cues.nativeAudio?.[talkId]),legacy=preserved?null:this.options.getLegacy?.(talkId);
    const native=preserved||(Number(legacy?.type)===1?Number(legacy.id):0);
    if(native){this.activeGroup=null;this.nativeBgm=native;return true;}return false;
  }
  prime(trace=[]){
    this.activeGroup=null;this.nativeBgm=null;const index=new Map();
    for(const group of this.options.getCues()?.bgm||[])for(const id of group.talkIds||[])index.set(Number(id),group);
    for(let i=trace.length-1;i>=0;i--)if(this.musicAt(trace[i],index))break;
  }
  enter(talkId,trace=null){if(trace)this.prime(trace.slice(0,-1));this.musicAt(talkId);
    const cues=this.options.getCues()||{},legacy=this.options.getLegacy?.(talkId),group=this.activeGroup;
    const fallback=!group&&!this.nativeBgm?this.options.getDefaultBgm?.():null;
    const key=group?JSON.stringify([group.id,group.audioId,group.loop,group.volume]):this.nativeBgm?'native:'+this.nativeBgm:fallback?'default:'+fallback.id+':'+fallback.url:null;
    const track=group?{url:this.options.getUrl(Number(group.audioId)),volume:group.volume??1,loop:group.loop}:this.nativeBgm?{url:this.options.getUrl(this.nativeBgm),volume:1,loop:true}:fallback?{url:fallback.url,volume:fallback.volume??1,loop:true}:null;
    this.switchMusic(key,track);
    if(Number(talkId)!==this.lastTalk){this.sfx=this.sfx.filter(a=>!a.ended);const effects=(cues.sfx?.[talkId]||[]).slice();if(Number(legacy?.type)===2&&!effects.some(c=>Number(c.audioId)===Number(legacy.id)))effects.push({audioId:legacy.id,volume:1});for(const cue of effects){const audio=this.create(cue.audioId,cue.volume??1);if(audio)this.sfx.push(audio);}}
    this.lastTalk=Number(talkId);
  }
  pause(){this.cancelPendingMusic();this.bgm?.pause();for(const audio of this.sfx)audio.pause();}
  resume(){if(this.bgm&&!this.bgm.ended)this.bgm.play()?.catch?.(()=>{});for(const audio of this.sfx)if(!audio.ended)audio.play()?.catch?.(()=>{});if(this.desiredMusic){const {key,track}=this.desiredMusic;this.switchMusic(key,track);}}
  stop(){this.pause();this.bgm=null;this.sfx=[];this.group=null;this.nativeBgm=null;this.activeGroup=null;this.lastTalk=null;this.desiredMusic=null;this.failedMusic=null;}
}
window.StudentAgeScene={planSceneDrag,nativePositionPlayer,nativePositionFrames,nativeRoleOrder,normalizeNativeMoves,staticPortraitSize,bubbleAssets,releaseBubbleAssets,bubbleY,bubbleGlyph,portraitBox,portraitCacheKey,portraitFrames,portraitSizes,protagonistGender,portraitIdentity,routes,pathTo,blank,apply,reconstruct,roleEntry,setRoleEntry,portraitSource,portraitCandidates,backgroundPath,Renderer,Player,AudioPlayer};
})();
