/* Theme is stored in the same durable user preferences as cache paths. */
(()=>{'use strict';
function apply(value){const theme=['classic','glass','glass-dusk','glass-moon'].includes(value)?value:'glass';window.STUDIO_THEME=theme;document.documentElement.dataset.theme=theme;for(const name of ['glass-palette.css','glass-theme.css']){const link=document.querySelector(`link[href="/${name}"]`);if(link)link.media=theme!=='classic'?'all':'not all';}const meta=document.querySelector('meta[name="color-scheme"]');if(meta)meta.content=theme==='glass'?'light':'dark';window.dispatchEvent(new Event('studio-theme-change'));}
window.STUDIO_SET_THEME=async value=>{const r=await fetch('/api/display-settings',{method:'POST',headers:{'X-Studio-Token':window.STUDIO_TOKEN,'Content-Type':'application/json'},body:JSON.stringify({theme:value})});const v=await r.json();if(!r.ok)throw Error(v.error||'主题保存失败');apply(v.theme);};
apply(window.STUDIO_THEME);
})();
