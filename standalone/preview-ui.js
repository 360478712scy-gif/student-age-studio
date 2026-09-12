'use strict';
// Native sprite slices, colours and fonts come from the user's installed game.
window.StudentAgePreviewUI=(()=>{
 let pending=null;
 const scale=()=>document.documentElement.style.setProperty('--game-ui-scale',Math.min(innerWidth/2560,innerHeight/1440));
 scale();addEventListener('resize',scale);
 async function load(){
  if(pending)return pending;
  window.STUDIO_CACHE_TASKS?.update('preview-ui','准备原版预览素材',0);
  pending=(async()=>{
   const response=await fetch('/api/preview-ui',{headers:{'X-Studio-Token':window.STUDIO_TOKEN}});if(!response.ok)throw Error('原版预览界面资源未能读取');const data=await response.json();
   const url=name=>'/api/preview-ui?resource='+encodeURIComponent(name)+'&token='+encodeURIComponent(window.STUDIO_TOKEN);
   for(const name of data.files.filter(n=>n.endsWith('.png')))document.documentElement.style.setProperty('--game-'+name.slice(0,-4),`url("${url(name)}")`);
   for(const [gender,colors] of Object.entries(data.colors))for(const [i,part] of ['paper','text','name','name-text'].entries())document.documentElement.style.setProperty(`--game-${gender}-${part}`,colors[i]);
   // Keep the rounded fallback until the actual frame and control images decode.
   await Promise.all(data.files.filter(n=>n.endsWith('.png')&&!n.startsWith('paper')).map(name=>new Promise((resolve,reject)=>{const img=new Image();img.onload=resolve;img.onerror=()=>reject(Error('原版预览贴图读取失败：'+name));img.src=url(name); })));
   await Promise.allSettled(['sans','serif'].map(async key=>{const font=new FontFace('StudentAge '+key,`url("${url(key+'.otf')}")`,{weight:key==='sans'?'500':'900'});await font.load();document.fonts.add(font);}));
   document.documentElement.classList.add('game-ui-ready');return data;
  })().catch(error=>{pending=null;console.warn(error.message);return null;}).finally(()=>window.STUDIO_CACHE_TASKS?.finish('preview-ui'));return pending;
 }

 let cgPending=null;
 function loadCG(){if(cgPending)return cgPending;cgPending=(async()=>{
  const url=name=>'/api/cg-ui?resource='+encodeURIComponent(name)+'&token='+encodeURIComponent(window.STUDIO_TOKEN);
  document.documentElement.style.setProperty('--cg-mask',`url("${url('mask.png')}")`);
  await Promise.allSettled(['body','name'].map(async key=>{const font=new FontFace('StudentAge CG '+key,`url("${url(key+'.otf')}")`);await font.load();document.fonts.add(font);}));
 })().catch(error=>{cgPending=null;console.warn(error.message);});return cgPending;}
 const paperImages=new Map();let paperFonts=null;
 const paperUrl=name=>'/api/preview-ui?resource='+encodeURIComponent(name)+'&token='+encodeURIComponent(window.STUDIO_TOKEN);
 function paperImage(name){if(!paperImages.has(name))paperImages.set(name,new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=()=>{paperImages.delete(name);reject(Error('纸条素材读取失败'));};i.src=paperUrl(name);}));return paperImages.get(name);}
 async function drawPaper(canvas,paper,doc){
  const epoch=canvas.paperEpoch=(canvas.paperEpoch||0)+1;
  try{
   if(!await load())return;
   paperFonts||=fetch(paperUrl('paper-fonts.json')).then(r=>{if(!r.ok)throw Error('纸条字体读取失败');return r.json();}).catch(e=>{paperFonts=null;throw e;});
   const fonts=await paperFonts,font=fonts[Number(paper.type)===1?'107':'108']||fonts['108'];
   const [background,...atlases]=await Promise.all([paperImage('paper.png'),...font.atlases.map(paperImage)]);
   if(canvas.paperEpoch!==epoch)return;
   const factor=Math.max(1,Number(paper.scale)||1),w=554*factor,h=558*factor;
   canvas.width=Math.ceil(w*2);canvas.height=Math.ceil(h*2);const ctx=canvas.getContext('2d');ctx.scale(2,2);ctx.drawImage(background,0,0,w,h);
   const face=font.face,point=face.m_PointSize||48;
   const glyph=ch=>font.characters[String(ch.codePointAt(0))];
   const text=value=>String(value||'').replace(/\\n/g,'\n').replace(/\{(\d+)\}/g,(m,id)=>doc.persons?.[id]?.name||m);
   function layout(value,size,width){
    const lines=[{chars:[],width:0}],unit=size/point;
    for(const ch of text(value)){if(ch==='\r')continue;if(ch==='\n'){lines.push({chars:[],width:0});continue;}
     const g=glyph(ch),advance=(g?.m_Metrics?.m_HorizontalAdvance||point)*unit;let line=lines[lines.length-1];
     if(line.chars.length&&line.width+advance>width){line={chars:[],width:0};lines.push(line);}
     line.chars.push({ch,g,x:line.width});line.width+=advance;
    }return {lines,unit,lineHeight:face.m_LineHeight*unit};
   }
   function write(value,x,y,width,height,align){
    let size=50,l;do{l=layout(value,size,width);if(l.lines.length*l.lineHeight<=height||size<=18)break;size-=.25;}while(size>=18);
    const startY=y+Math.max(0,(height-l.lines.length*l.lineHeight)/2)+face.m_AscentLine*l.unit;
    ctx.save();ctx.beginPath();ctx.rect(x,y,width,height);ctx.clip();
    l.lines.forEach((line,index)=>{const left=x+(align==='right'?width-line.width:align==='center'?(width-line.width)/2:0),baseline=startY+index*l.lineHeight;
     for(const {ch,g,x:offset}of line.chars){if(!g){ctx.font=`${size}px sans-serif`;ctx.fillStyle='#000';ctx.fillText(ch,left+offset,baseline);continue;}
      const r=g.m_GlyphRect,m=g.m_Metrics,atlas=atlases[g.m_AtlasIndex||0];if(r.m_Width&&r.m_Height)ctx.drawImage(atlas,r.m_X,atlas.height-r.m_Y-r.m_Height,r.m_Width,r.m_Height,left+offset+m.m_HorizontalBearingX*l.unit,baseline-m.m_HorizontalBearingY*l.unit,m.m_Width*l.unit,m.m_Height*l.unit);
     }
    });ctx.restore();
   }
   write(paper.content,50,50,w-100,h-150,Number(paper.alignment)===1?'left':'center');
   write(paper.name,w-100*factor-366.2523,h-30*factor-60,366.2523,60,'right');
   canvas.setAttribute('aria-label',text(paper.content)+' '+text(paper.name));canvas.dataset.paperReady='true';
  }catch(error){canvas.dataset.paperError=error.message;console.error(error);}
 }
 return {load,loadCG,scale,drawPaper};

})();
