'use strict';
(() => {
const names=['默认','高兴','生气','伤心','害羞','喜欢','认真','疑惑','惊讶','得意','微笑','坏笑','担心','害怕','难过','咆哮','窘迫','不满','冷笑','无语','苦笑'];
function choices({person,faces={},roleId,grade=0,cloth=0,metadata}) {
  if(!person||roleId===null||roleId===undefined)return [];
  const role=Number(roleId),outfit=Number(cloth),young=Number(grade)===0;
  const hasModel=!!(young?person.l2d:person.l2d2)?.length;
  const available=new Set([0]);
  if(hasModel&&metadata){
    const aliases=new Set((metadata.sameAsDefault||[]).map(Number));
    for(const id of (metadata.faces||[]).map(Number))if(!aliases.has(id))available.add(id);
  }
  // A mod can supply a real image for an otherwise missing/default-mapped face.
  for(const row of Object.values(faces))if(Math.floor(Number(row.id)/1000)===role&&Math.floor(Number(row.id)/100)%10===outfit&&(young?row.icon_xx:row.icon))available.add(Number(row.id)%100);
  return [...available].filter(id=>Number.isInteger(id)&&id>=0).sort((a,b)=>a-b).map(id=>{
    const row=faces[role*1000+outfit*100+id],path=row&&(young?row.icon_xx:row.icon);
    return {id,name:row?.name||names[id]||'表情 '+id,path:path||null};
  });
}
window.StudentAgeExpressions={choices,names};
})();
