/* Safe TextMeshPro-style formatting for playback only. Never interpret dialogue as HTML. */
(() => {
'use strict';
const colors=new Set(['black','blue','green','orange','purple','red','white','yellow']);
function color(value){return /^#(?:[\da-f]{3}|[\da-f]{4}|[\da-f]{6}|[\da-f]{8})$/i.test(value)||colors.has(value.toLowerCase())?value:null;}
function length(value){const m=/^([+-]?\d+(?:\.\d+)?)(px|em|%)?$/.exec(value);if(!m||Math.abs(Number(m[1]))>10000)return null;return m[2]==='%'?`${Number(m[1])/100}em`:m[2]==='em'?`${m[1]}em`:`calc(${m[1]}px * var(--game-ui-scale, 1))`;}
function render(target,content){
 const fragment=document.createDocumentFragment(),stack=[{name:'',node:fragment}];let literal=false;
 const append=text=>stack.at(-1).node.append(document.createTextNode(text));
 for(const token of String(content??'').split(/(<[^<>\r\n]*>)/g)){
  if(!token)continue;
  if(literal){if(/^<\/noparse>$/i.test(token))literal=false;else append(token);continue;}
  const match=/^<(\/)?([a-z][a-z0-9-]*|#[\da-f]{6}|#[\da-f]{8})(?:=(?:"([^"]*)"|'([^']*)'|([^<>]*)))?\s*>$/i.exec(token);
  if(!match){append(token);continue;}
  let [,closing,name,a,b,c]=match;name=name.toLowerCase();const value=(a??b??c??'').trim();
  if(closing){const index=stack.map(s=>s.name).lastIndexOf(name);if(index>0)stack.splice(index);else append(token);continue;}
  if(name==='noparse'){literal=true;continue;}
  if(name==='br'){stack.at(-1).node.append(document.createElement('br'));continue;}
  const node=document.createElement('span');let valid=true;
  if(name[0]==='#'){node.style.color=name;name='color';}
  else if(name==='color'||name==='mark'){const v=color(value);if(v)node.style[name==='color'?'color':'backgroundColor']=v;else valid=false;}
  else if(name==='b')node.style.fontWeight='bold';
  else if(name==='i')node.style.fontStyle='italic';
  else if(name==='u'||name==='s'||name==='strikethrough')node.style.textDecoration=name==='u'?'underline':'line-through';
  else if(name==='size'){const v=length(value);if(v&&Number.parseFloat(value)>0)node.style.fontSize=v;else valid=false;}
  else if(name==='sub'||name==='sup'){node.style.verticalAlign=name;node.style.fontSize='70%';}
  else if(name==='uppercase'||name==='lowercase')node.style.textTransform=name;
  else if(name==='smallcaps')node.style.fontVariant='small-caps';
  else if(name==='cspace'){const v=length(value);if(v)node.style.letterSpacing=v;else valid=false;}
  else if(name==='voffset'){const v=length(value);if(v){node.style.position='relative';node.style.top=`calc(-1 * ${v})`;}else valid=false;}
  else valid=false;
  if(!valid||stack.length>128){append(token);continue;}
  stack.at(-1).node.append(node);stack.push({name,node});
 }
 target.replaceChildren(fragment);
 return target.textContent;
}
window.StudentAgePreviewText={render};
})();
