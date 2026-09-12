/* Source view belongs to this browser window; the destination remains a real mod. */
(()=>{
'use strict';
let projectId=null;
const nativeFetch=window.fetch.bind(window);
window.STUDIO_ORIGINAL_MODE=()=>!!projectId&&projectId===window.STUDIO_CURRENT_PROJECT?.();
window.STUDIO_ORIGINAL_SOURCE={set(id){projectId=id||null;document.body.classList.toggle('original-edit-mode',!!projectId);}};
window.fetch=(input,options)=>{
 const url=new URL(input instanceof Request?input.url:input,location.href);
 if(projectId&&url.origin===location.origin&&url.pathname.startsWith('/api/')){
  const headers=new Headers(options?.headers||(input instanceof Request?input.headers:undefined));
  headers.set('X-Studio-Original-Project',projectId);
  return nativeFetch(input,{...options,headers});
 }
 return nativeFetch(input,options);
};
})();
