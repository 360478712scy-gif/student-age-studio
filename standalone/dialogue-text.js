(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeDialogueText=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';
const encode=text=>String(text??'').replace(/\\/g,'\\\\').replace(/\r\n|\r|\n/g,'\\n');
const decode=text=>String(text).replace(/\\(\\|n)/g,(_,c)=>c==='n'?'\n':'\\');
function serialize(rows,separator=' '){separator=[' ','：',':'].includes(separator)?separator:' ';return (rows.tokens||rows).map(row=>row.marker!==undefined?row.marker:encode(row.speaker||'旁白')+separator+encode(row.content)).join('\n')+(rows.length?'\n':'');}
function parse(text,persons={},bindings={}){
 const names=new Map([['旁白',[]]]);
 for(const person of Object.values(persons)){if(!person||person.name==null)continue;const name=String(person.name).trim();if(!name||name==='旁白')continue;if(!names.has(name))names.set(name,[]);names.get(name).push(Number(person.id));}
 const known=[...names.keys(),...Object.keys(bindings)].sort((a,b)=>b.length-a.length),rows=[],errors=[],sections=[],tokens=[];let active=null,main=-1;const lanes=new Map();
 for(const [index,original] of String(text).replace(/^\uFEFF/,'').split(/\r\n|\r|\n/).entries()){
  if(!original.trim())continue;
  const depth=(original.match(/^\t*/)?.[0]||'').length,marker=original.trim(),option=/^选项(?:[ \t]+|[：:][ \t]*)(.+)$/.exec(marker),branch=/^分支\s*([0-9]*)$/.exec(marker);
  if(marker==='。'){tokens.push({marker:'\t'.repeat(depth)+'。'});if(!active)errors.push({line:index+1,message:'句号前没有尚未结束的对话夹。'});lanes.delete(depth);active=[...lanes.values()].at(-1)||null;continue;}
  if(option||branch){
   const kind=option?'option':'condition',same=lanes.get(depth),parent=same?same.parent:active?rows.length-1:main;
   if(same&&same.kind!==kind){errors.push({line:index+1,message:'请先用单独一行的句号结束当前对话夹。'});continue;}
   active={kind,parent,title:option?decode(option[1].trim()):'',number:branch?.[1]?Number(branch[1]):null,start:rows.length};sections.push(active);tokens.push({marker:'\t'.repeat(depth)+(option?'选项 '+encode(active.title):'分支'+(active.number??''))});lanes.set(depth,active);continue;
  }
  const line=original.trimStart(),matched=known.find(name=>line.startsWith(encode(name))&&/[ \t：:]/.test(line.charAt(encode(name).length))),parts=matched?[encode(matched),line.slice(encode(matched).length).replace(/^(?:[：:][ \t]?|[ \t])/,'')]:line.match(/^([^：:\s]+)(?:[：:][ \t]?|[ \t])(.*)$/)?.slice(1)||['旁白',line];
  const speaker=decode(parts[0]),content=decode(parts[1]),bound=bindings[speaker],candidates=names.get(speaker)||[];
  const group=speaker.split('、').map(name=>names.get(name));
  const roleIds=speaker==='旁白'||bound==='narrator'?[]:bound!==undefined?[Number(bound)]:candidates.length===1?candidates:group.length>1&&group.every(ids=>ids?.length===1)?group.flat():null;
  if(roleIds?.some(id=>!persons[id])){errors.push({line:index+1,message:'人物已不存在，请重新选择。'});continue;}
  const row={speaker,content,roleIds,candidates,line:index+1};if(active)row.section=sections.indexOf(active);else main=rows.length;rows.push(row);tokens.push(row);
 }
 if(sections.length){Object.defineProperty(rows,'tokens',{value:tokens});Object.defineProperty(rows,'sections',{value:sections});for(const section of sections)if(section.number!==null&&(!Number.isSafeInteger(section.number)||section.number<1))errors.push({line:0,message:'分支编号必须是正整数。'});}
 if(sections.length>2000)errors.push({line:0,message:'一次最多导入 2000 个对话夹。'});
 if(rows.length>2000)errors.push({line:0,message:'一次最多导入 2000 句对话。'});
 return {rows,errors,unmatched:[...new Set(rows.filter(row=>row.roleIds===null).map(row=>row.speaker))]};
}
return {parse,serialize,encode,decode};
});
