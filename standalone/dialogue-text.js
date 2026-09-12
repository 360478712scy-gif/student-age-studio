(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeDialogueText=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';
const encode=text=>String(text??'').replace(/\\/g,'\\\\').replace(/\r\n|\r|\n/g,'\\n');
const decode=text=>String(text).replace(/\\(\\|n)/g,(_,c)=>c==='n'?'\n':'\\');
function serialize(rows,separator=' '){separator=[' ','：',':'].includes(separator)?separator:' ';return rows.map(row=>encode(row.speaker||'旁白')+separator+encode(row.content)).join('\n')+(rows.length?'\n':'');}
function parse(text,persons={},bindings={}){
 const names=new Map([['旁白',[]]]);
 for(const person of Object.values(persons)){if(!person||person.name==null)continue;const name=String(person.name).trim();if(!name||name==='旁白')continue;if(!names.has(name))names.set(name,[]);names.get(name).push(Number(person.id));}
 const known=[...names.keys(),...Object.keys(bindings)].sort((a,b)=>b.length-a.length),rows=[],errors=[];
 for(const [index,original] of String(text).replace(/^\uFEFF/,'').split(/\r\n|\r|\n/).entries()){
  if(!original.trim())continue;const line=original.trimStart(),matched=known.find(name=>line.startsWith(encode(name))&&/[ \t：:]/.test(line.charAt(encode(name).length))),parts=matched?[encode(matched),line.slice(encode(matched).length).replace(/^(?:[：:][ \t]?|[ \t])/,'')]:line.match(/^([^：:\s]+)(?:[：:][ \t]?|[ \t])(.*)$/)?.slice(1);
  if(!parts){errors.push({line:index+1,message:'人物名后用空格、中文冒号或英文冒号分隔，再填写对话。'});continue;}
  const speaker=decode(parts[0]),content=decode(parts[1]),bound=bindings[speaker],candidates=names.get(speaker)||[];
  const group=speaker.split('、').map(name=>names.get(name));
  const roleIds=speaker==='旁白'||bound==='narrator'?[]:bound!==undefined?[Number(bound)]:candidates.length===1?candidates:group.length>1&&group.every(ids=>ids?.length===1)?group.flat():null;
  if(roleIds?.some(id=>!persons[id])){errors.push({line:index+1,message:'人物已不存在，请重新选择。'});continue;}
  rows.push({speaker,content,roleIds,candidates,line:index+1});
 }
 if(rows.length>2000)errors.push({line:0,message:'一次最多导入 2000 句对话。'});
 return {rows,errors,unmatched:[...new Set(rows.filter(row=>row.roleIds===null).map(row=>row.speaker))]};
}
return {parse,serialize,encode,decode};
});
