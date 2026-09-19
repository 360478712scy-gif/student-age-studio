/* Companion names follow CfgExtension; only full portraits have native transform fields. */
(()=>{'use strict';
const kinds=[{id:'portrait',name:'剧情立绘',adjust:true},{id:'half',name:'人物半身照'},{id:'head',name:'人物头像'},{id:'comic',name:'Q 版人物'},{id:'comicHead',name:'Q 版人物头像'},{id:'booth',name:'大头贴合影',adjust:true},{id:'photoButton',name:'大头贴表情按钮'},{id:'avatar',name:'企鹅头像'}];
const custom=p=>/^(Mods|Textures|StudentAgeStudio)[\\/]/i.test(p||'');
function companion(base,suffix){const p=base.replace(/\\/g,'/'),dot=p.lastIndexOf('.');return dot>p.lastIndexOf('/')?p.slice(0,dot)+suffix+p.slice(dot):p+suffix;}
function path(person,kind,grade,gender,faces={},avatars={},cloth=0,expression=0){
 if(!person)return '';const female=person.id===0&&gender===2,index=female?1:0,g=['comic','comicHead'].includes(kind)?0:grade;
 const urls=g?(person.url2?.length?person.url2:person.url):(person.url?.length?person.url:person.url2),base=urls?.[index]||'',face=faces[person.id*1000+cloth*100+expression]||faces[person.id*1000+cloth*100];
 if(kind==='avatar'){const icon=avatars[person.kzoneHeadId]?.icon;return icon||path(person,'head',grade,gender,faces,avatars,cloth,expression);}
 if(kind==='photoButton')return face?.photobooth|| (custom(base)?path(person,'head',grade,gender,faces,avatars,cloth,expression):base?'role_photo/'+base+'_'+expression:'');
 if(kind==='portrait'||kind==='booth'){const full=face?.[grade?'icon':'icon_xx']||base;return !full?'':custom(full)?full:'role_full/'+full;}
 if(!base)return '';const suffix=kind==='comicHead'?'comic':kind;return custom(base)?companion(base,'_'+suffix):'role_'+(kind==='comicHead'?'comic_head':kind)+'/'+base;
}
function file(){return new Promise(resolve=>{const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,image/bmp,image/x-tga';input.hidden=true;document.body.append(input);const end=v=>{input.remove();resolve(v);};input.onchange=()=>end(input.files[0]||null);input.oncancel=()=>end(null);input.click();});}
async function select(ctx,kind,gender){
 const {S,options,person,change,all}=ctx,selected=S.selected,grade=S.grade,cloth=S.cloth,expression=S.previewFace;
 if(['portrait','booth'].includes(kind))return ctx.pickMedia('portrait',grade);
 if(kind==='avatar')return ctx.pickAvatar();
 const chosen=await file();if(!chosen||S.selected!==selected)return;
 const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(chosen);});
 if(S.selected!==selected)return;S.busy=true;
 try{
  const image=await options.api('/api/image-import',{projectId:options.project.id,revision:S.revision,fileName:chosen.name,data});S.revision=image.revision;
  if(S.selected!==selected)return;
  if(kind==='photoButton'){S.busy=false;change(()=>{const id=Number(selected)*1000+cloth*100+expression;S.tables.ModFaceCfg[id]={id,name:expression?'表情 '+expression:'默认',icon:'',icon_xx:'',...structuredClone(all('ModFaceCfg')[id]||{}),photobooth:image.url};});return;}
  const target=['comic','comicHead'].includes(kind)?0:grade,p=person(),key=target?'url2':'url',slot=p.id===0&&gender===2?1:0,base=p[key]?.[slot]||p[target?'url':'url2']?.[slot];
  if(!base)throw Error('请先添加这个学段的剧情立绘，再添加配套图片。');
  const result=await options.api('/api/character-companion',{projectId:options.project.id,revision:S.revision,kind:kind==='comicHead'?'comic':kind,base:custom(base)?base:'role_full/'+base,source:image.url});S.revision=result.revision;
  if(S.selected!==selected)return;S.busy=false;change(()=>{p[key]=[...(p[key]||[])];while(p[key].length<=slot)p[key].push('');p[key][slot]=result.url;});
 }finally{S.busy=false;ctx.notify?.();}
}
window.StudentAgeCharacterImages={kinds,path,select,companion};})();
