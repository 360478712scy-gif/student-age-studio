/* Color and material are independent durable preferences. */
(()=>{'use strict';
function apply(value,material=window.STUDIO_GLASS_MATERIAL){
 const theme=['classic','glass','glass-dusk','glass-moon'].includes(value)?value:'glass';
 window.STUDIO_THEME=theme;window.STUDIO_GLASS_MATERIAL=material==='frosted'?'frosted':'liquid';
 document.documentElement.dataset.theme=theme;document.documentElement.dataset.glassMaterial=window.STUDIO_GLASS_MATERIAL;
 for(const name of ['glass-palette.css','glass-theme.css']){const link=document.querySelector(`link[href="/${name}"]`);if(link)link.media=theme!=='classic'?'all':'not all';}
 const meta=document.querySelector('meta[name="color-scheme"]');if(meta)meta.content=theme==='glass'?'light':'dark';
 window.dispatchEvent(new Event('studio-theme-change'));
}
let pending=Promise.resolve();
function save(change){
 const task=pending.then(async()=>{const r=await fetch('/api/display-settings',{method:'POST',headers:{'X-Studio-Token':window.STUDIO_TOKEN,'Content-Type':'application/json'},body:JSON.stringify(change)});const v=await r.json();if(!r.ok)throw Error(v.error||'外观保存失败');apply(v.theme,v.glassMaterial);});
 pending=task.catch(()=>{});return task;
}
window.STUDIO_SET_THEME=value=>save({theme:value});
window.STUDIO_SET_GLASS_MATERIAL=value=>save({glassMaterial:value});
apply(window.STUDIO_THEME);
})();
