/* Shared reply tree. Folding affects navigation only, never the message graph. */
(()=>{'use strict';
const esc=v=>StudentAgeCharacterUI.esc(v);
function mount(host,entries,{choices={},collapsed=new Set(),attributes=()=>'',title=()=>'',label='回复分支'}={}){
 const nodes=entries.map((entry,index)=>({...entry,index,children:[]})),byKey=new Map(nodes.map(n=>[n.key,n])),roots=[];
 for(const node of nodes)(byKey.get(node.parentKey)?.children||roots).push(node);
 const matches=n=>Object.entries(n.choices).every(([k,v])=>Number(choices[k])===Number(v));
 const selected=nodes.filter(matches).sort((a,b)=>Object.keys(b.choices).length-Object.keys(a.choices).length)[0];
 const item=node=>{const children=node.children,folded=collapsed.has(node.key),active=selected===node;
  return `<li role="treeitem" data-tree-key="${esc(node.key)}" aria-selected="${active}" ${children.length?`aria-expanded="${!folded}"`:''}><div class="reply-tree-row ${active?'active':matches(node)?'on-path':''}">${children.length?`<button class="reply-tree-toggle" data-tree-toggle aria-label="${folded?'展开':'收起'}分支 ${esc(node.label)}" aria-expanded="${!folded}">${folded?'▸':'▾'}</button>`:'<span class="reply-tree-leaf" aria-hidden="true"></span>'}<button class="reply-tree-select" ${attributes(node.index)} title="${esc(title(node))}" ${active?'aria-current="true"':''}><strong>分支 ${esc(node.label)}</strong><small>${esc(title(node))}</small></button></div>${children.length?`<ul role="group" ${folded?'hidden':''}>${children.map(item).join('')}</ul>`:''}</li>`;};
 host.innerHTML=`<ul class="reply-tree" role="tree" aria-label="${esc(label)}"><li role="treeitem" aria-selected="${!selected}"><div class="reply-tree-row reply-tree-start ${!selected?'active':''}"><span class="reply-tree-root" aria-hidden="true">●</span><button class="reply-tree-select" ${attributes(-1)}><strong>完整起点</strong><small>${roots.length?'展开分支查看不同回复':'尚未添加回复分支'}</small></button></div>${roots.length?`<ul role="group">${roots.map(item).join('')}</ul>`:''}</li></ul>`;
 const fold=(li,value)=>{const key=li.dataset.treeKey,group=li.querySelector(':scope > ul'),button=li.querySelector(':scope > .reply-tree-row > [data-tree-toggle]');if(!group||!button)return;value?collapsed.add(key):collapsed.delete(key);group.hidden=value;li.setAttribute('aria-expanded',String(!value));button.setAttribute('aria-expanded',String(!value));button.setAttribute('aria-label',(value?'展开':'收起')+li.querySelector('.reply-tree-select strong').textContent);button.textContent=value?'▸':'▾';};
 host.onclick=e=>{const button=e.target.closest('[data-tree-toggle]');if(!button)return;e.stopPropagation();const li=button.closest('[data-tree-key]');fold(li,li.getAttribute('aria-expanded')==='true');};
 host.onkeydown=e=>{if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const li=e.target.closest('[role=treeitem]');if(!li)return;e.preventDefault();e.stopPropagation();const buttons=[...host.querySelectorAll('.reply-tree-select')].filter(b=>!b.closest('ul[hidden]')),current=li.querySelector(':scope > .reply-tree-row > .reply-tree-select'),index=buttons.indexOf(current);
  if(e.key==='ArrowLeft'){if(li.getAttribute('aria-expanded')==='true')fold(li,true);else li.parentElement.closest('[role=treeitem]')?.querySelector(':scope > .reply-tree-row > .reply-tree-select')?.focus();}
  else if(e.key==='ArrowRight'){if(li.getAttribute('aria-expanded')==='false')fold(li,false);else li.querySelector(':scope > ul > li > .reply-tree-row > .reply-tree-select')?.focus();}
  else buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:Math.max(0,Math.min(buttons.length-1,index+(e.key==='ArrowDown'?1:-1)))]?.focus();
 };
}
window.StudentAgeBranchTree={mount};
})();
