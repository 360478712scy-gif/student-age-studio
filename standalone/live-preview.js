/* Unity prefab parameters + original idle curves; Cubism Core/physics and WebGL. */
(()=>{'use strict';
let runtime,renderer,frame,lastTime,idleTimer,modelLoads=0;
const active=new Set(),textures=new Set(),pool=[],descriptions=new Map();
async function prepare(request,loader){
 const key=JSON.stringify(request),cached=descriptions.get(key);
 if(cached&&Date.now()-cached.time<60000)return cached.value;
 const task='model:'+key;window.STUDIO_CACHE_TASKS?.update(task,'读取人物模型缓存',0);
 try{const result=await loader();if(result.status==='ready'){descriptions.delete(key);descriptions.set(key,{time:Date.now(),value:result});while(descriptions.size>6)descriptions.delete(descriptions.keys().next().value);window.STUDIO_CACHE_TASKS?.finish(task);}else if(result.status==='error')window.STUDIO_CACHE_TASKS?.finish(task);return result;}
 catch(e){window.STUDIO_CACHE_TASKS?.finish(task);throw e;}
}
function pruneTextures(){const used=new Set([...active,...pool].flatMap(item=>item.model.textures));for(const texture of textures)if(!used.has(texture)){texture.destroy(true);textures.delete(texture);}}
function release(model,key){pool.push({model,key});while(pool.length>2)pool.shift().model.destroy();pruneTextures();if(!active.size){clearTimeout(idleTimer);idleTimer=setTimeout(()=>{if(active.size)return;while(pool.length)pool.pop().model.destroy();pruneTextures();renderer?.destroy(true);renderer=null;},60000);}}
function renderLoop(now){
 if(lastTime!==null&&now-lastTime<1000/30){frame=requestAnimationFrame(renderLoop);return;}
 const dt=Math.min(50,Math.max(0,now-(lastTime??now)));lastTime=now;
 const visible=[...active].filter(item=>!document.hidden&&item.canvas.isConnected);
 if(visible.length){const width=Math.max(...visible.map(i=>i.canvas.width)),height=Math.max(...visible.map(i=>i.canvas.height));if(renderer.width!==width||renderer.height!==height)renderer.resize(width,height);
 for(const {canvas,model,context} of visible){model.update(dt);renderer.render(model);context.clearRect(0,0,canvas.width,canvas.height);context.drawImage(renderer.view,0,0,canvas.width,canvas.height,0,0,canvas.width,canvas.height);}}
 frame=active.size?requestAnimationFrame(renderLoop):null;
}
function loadRuntime(){
 if(!runtime)runtime=(async()=>{for(const name of ['pixi.min.js','pixi-csp.min.js','live2dcubismcore.min.js','cubism4.js'])await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/ui-assets/live2d/'+name;script.onload=resolve;script.onerror=()=>{script.remove();reject(Error('动态模型组件读取失败，请重试。'));};document.head.append(script);});})().catch(e=>{runtime=null;throw e;});
 return runtime;
}
function curve(keys,t){let lo=0,hi=keys.length;while(lo<hi){const m=(lo+hi)>>1;if(keys[m][0]<=t)lo=m+1;else hi=m;}const [start,c]=keys[Math.max(0,lo-1)],dt=Math.max(0,t-start);return ((c[0]*dt+c[1])*dt+c[2])*dt+c[3];}
function sample(animation,t){const a=animation,d=a.dense,time=a.start+(t%a.duration),out={};a.bindings.forEach((name,i)=>{if(!name)return;if(i<a.streamCount){if(a.stream[i]?.length)out[name]=curve(a.stream[i],time);}else if(i<a.streamCount+d.m_CurveCount){const frame=Math.max(0,Math.min(d.m_FrameCount-1,(time-d.m_BeginTime)*d.m_SampleRate)),left=Math.floor(frame),right=Math.min(d.m_FrameCount-1,left+1),index=i-a.streamCount,f=frame-left;out[name]=d.m_SampleArray[left*d.m_CurveCount+index]*(1-f)+d.m_SampleArray[right*d.m_CurveCount+index]*f;}else{const index=i-a.streamCount-d.m_CurveCount;if(index<a.constant.length)out[name]=a.constant[index];}});return out;}
function damp(state,goal,dt,smooth){const omega=2/Math.max(.0001,smooth),x=omega*dt,decay=1/(1+x+.48*x*x+.235*x*x*x);for(let i=0;i<2;i++){const difference=state.value[i]-goal[i],temp=(state.velocity[i]+omega*difference)*dt;state.velocity[i]=(state.velocity[i]-omega*temp)*decay;state.value[i]=goal[i]+(difference+temp)*decay;}return state.value;}
function blinkState(config,random=Math.random){let phase=0,elapsed=0,next=(config.Mean??2.5)+(random()*2-1)*(config.MaximumDeviation??2);return dt=>{if(!phase){next-=dt;if(next<0){phase=1;elapsed=0;}return 1;}elapsed+=dt*(config.Timescale??10);const length=[0,1,.5,1.5][phase];const value=phase===1?Math.max(0,1-elapsed):phase===2?0:Math.min(1,elapsed/1.5);if(elapsed>=length){phase=(phase+1)%4;elapsed=0;if(!phase)next=(config.Mean??2.5)+(random()*2-1)*(config.MaximumDeviation??2);}return value;};}
function blend(core,id,value,mode){if(mode===1)core.addParameterValueById(id,value);else if(mode===2)core.multiplyParameterValueById(id,value);else core.setParameterValueById(id,value);}
async function mount(art,stage,result,options){
 await loadRuntime();if(!art.isConnected||options.cancelled())return null;
 const profile=result.profile,url=file=>'/api/live-model-file?'+new URLSearchParams({key:result.key,file,token:options.token});
 const settings={Version:3,url:location.origin+url('model.json'),FileReferences:{Moc:url('model.moc3'),Textures:result.files.filter(n=>n.startsWith('texture-')).map(url)}};
 if(result.files.includes('physics.json'))settings.FileReferences.Physics=url('physics.json');
 const cacheKey=result.key+':'+(result.cacheStamp||profile.version),pooled=pool.findIndex(item=>item.key===cacheKey);
 clearTimeout(idleTimer);
 const task='model-mount:'+cacheKey;window.STUDIO_CACHE_TASKS?.update(task,'准备模型预览',50);
 let model;
 try{if(pooled>=0)model=pool.splice(pooled,1)[0].model;else{model=await PIXI.live2d.Live2DModel.from(settings,{autoInteract:false,autoUpdate:false,motionPreload:'NONE'});modelLoads++;}}
 finally{window.STUDIO_CACHE_TASKS?.finish(task);}
 model.textures.forEach(t=>textures.add(t));
 if(options.cancelled()||!art.isConnected){release(model,cacheKey);return null;}
 if(!renderer)renderer=new PIXI.Renderer({width:500,height:700,backgroundAlpha:0,antialias:true,resolution:1});
 const img=art.querySelector('img');img.hidden=true;
 const canvas=document.createElement('canvas');canvas.className='live-model-canvas';canvas.setAttribute('aria-label','实时 Live2D 人物预览');art.prepend(canvas);const context=canvas.getContext('2d');
 const item={model,canvas,context,key:cacheKey};
 let disposed=false,elapsed=0,lastMovement=-Infinity,lastTarget=[0,0],mouse=null,frames=0;
 const lookState={value:[0,0],velocity:[0,0]},blink=blinkState(profile.blink),internal=model.internalModel,core=internal.coreModel;
 const updatePointer=e=>{if(e.pointerType==='touch')return;mouse=[e.clientX,e.clientY];};
 const leave=()=>{mouse=null;};document.addEventListener('pointermove',updatePointer,{passive:true});document.addEventListener('pointerleave',leave);
 const defaults=new Float32Array(core.getModel().parameters.defaultValues);
 const layers={};for(const name of ['Cloth','Hair','Item','Expression']){const choices=profile.layers[name]||{},weight=name==='Cloth'?(options.cloth||0):name==='Expression'?(profile.faces[String(options.face||0)]??-1):0,keys=Object.keys(choices);if(keys.length)Object.assign(layers,choices[keys.reduce((a,b)=>Math.abs(Number(a)-weight)<=Math.abs(Number(b)-weight)?a:b)]);}
 internal.update=(milliseconds)=>{
  if(disposed)return;const dt=Math.min(.05,Math.max(0,milliseconds/1000));elapsed+=dt;const values=core.getModel().parameters.values;values.set(defaults);
  for(const [id,value]of Object.entries({...sample(profile.animation,elapsed),...layers}))core.setParameterValueById(id,value);
  const rect=stage.getBoundingClientRect(),g=options.geometry();let target=[0,0];
  if(mouse){target=[(mouse[0]-rect.left)/rect.width*2-1,1-(mouse[1]-rect.top)/rect.height*2];if(Math.abs(target[0]-lastTarget[0])+Math.abs(target[1]-lastTarget[1])>.1){lastTarget=target.slice();lastMovement=elapsed;}if(elapsed-lastMovement>=3)target=[0,0];}
  const center=g.x*rect.height/2400/rect.width*2;
  const look=damp(lookState,[(target[0]-center)*(g.flip?-1:1),target[1]],dt,profile.lookController.Damping??.15);
  for(const p of profile.look)blend(core,p.id,(look[p.axis]||0)*p.factor,profile.lookController.BlendMode??1);
  const opening=blink(dt);for(const id of profile.eyes)blend(core,id,opening,profile.blinkController.BlendMode??2);
  internal.physics?.evaluate(core,dt);internal.pose?.updateParameters(core,dt);core.update();frames++;canvas.dataset.frames=String(frames);canvas.dataset.look=look.join(',');canvas.dataset.eye=String(opening);canvas.dataset.physics=String(!!internal.physics);
 };
 function resize(){if(disposed)return;const ratio=Math.min(devicePixelRatio||1,1.25),width=Math.max(1,art.clientWidth),height=Math.max(1,art.clientHeight),[x,y,w,h]=profile.bounds,ppu=internal.pixelsPerUnit;const cw=Math.round(Math.min(width*ratio,900)),ch=Math.round(Math.min(height*ratio,1200));if(canvas.width!==cw)canvas.width=cw;if(canvas.height!==ch)canvas.height=ch;const sx=canvas.width/w,sy=canvas.height/h;model.scale.set(sx/ppu,sy/ppu);model.position.set((-x-internal.originalWidth/ppu/2)*sx,(y+h-internal.originalHeight/ppu/2)*sy);canvas.style.transform=`scaleX(${options.geometry().flip?-1:1})`;}
 const observer=new ResizeObserver(resize);observer.observe(art);resize();active.add(item);if(!frame){lastTime=null;frame=requestAnimationFrame(renderLoop);}
 return {model,canvas,resize,get frames(){return frames;},destroy(){if(disposed)return;disposed=true;observer.disconnect();document.removeEventListener('pointermove',updatePointer);document.removeEventListener('pointerleave',leave);active.delete(item);release(model,cacheKey);canvas.remove();if(!active.size){cancelAnimationFrame(frame);frame=null;}}};
}
window.StudentAgeLivePreview={mount,prepare,sample,damp,blinkState,stats:()=>({active:active.size,cached:pool.length,modelLoads})};
})();
