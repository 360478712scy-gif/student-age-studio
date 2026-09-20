// Finished entrance animations must release layout for late metadata and resizing.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});try{
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 await page.setContent('<div id="large-scene"></div><div id="studio-corner-tools"><button>工具</button></div><div id="story-preview-controls"><button><i></i><span>日志</span></button></div>');
 for(const f of ['styles.css','scene-dialogue.css','navigation.css','preview-ui.css','editor-theme.css','glass-palette.css','glass-theme.css','frosted-glass.css'])await page.addStyleTag({path:'standalone/'+f});
 await page.addScriptTag({path:process.env.SCENE_SOURCE||'standalone/scene.js'});
 await page.evaluate(()=>{
  document.body.classList.add('story-fullscreen');const dock=document.querySelector('#studio-corner-tools');dock.setAttribute('popover','manual');dock.showPopover();
  const svg='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="600"><rect width="300" height="600" fill="red"/></svg>');
  window.doc={persons:{1:{id:1,name:'人物',url:['test'],urlParm:[65,190,.63]}},talks:{1:{id:1,content:'测试',roleIds:[1],roles:[[1,1001,0,3,0,0,0]]}},backgrounds:{}};
  window.renderer=new StudentAgeScene.Renderer(document.querySelector('#large-scene'),{assetUrl:()=>svg});
  window.state=StudentAgeScene.reconstruct(doc,1);renderer.draw(doc,state,{animate:true});
 });
 await page.waitForTimeout(2300);
 await page.evaluate(()=>{const img=document.querySelector('.scene-actor img');StudentAgeScene.portraitSizes.set(img.dataset.scenePath,[1081,2704]);renderer.refreshPortraits();});
 async function aligned(){const mismatch=await page.evaluate(()=>{const n=document.querySelector('.scene-actor'),r=n.getBoundingClientRect(),stage=document.querySelector('.scene-actors').getBoundingClientRect(),w=parseFloat(n.style.width)*stage.width/100,bottom=stage.bottom-parseFloat(n.style.bottom)*stage.height/100,left=stage.left+parseFloat(n.style.left)*stage.width/100-w/2;return Math.max(Math.abs(r.left-left),Math.abs(r.bottom-bottom));});assert(mismatch<.1,'late geometry must replace finished entrance pose: '+mismatch);}
 await aligned();await page.setViewportSize({width:1920,height:1080});await page.waitForTimeout(100);await aligned();
 for(const theme of ['classic','glass','glass-dusk','glass-moon'])for(const material of ['frosted','liquid']){
  await page.evaluate(({theme,material})=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.glassMaterial=material;},{theme,material});
  const result=await page.evaluate(()=>{const s=getComputedStyle(document.querySelector('#story-preview-controls button'));return {color:s.color,bg:s.backgroundColor,dock:getComputedStyle(document.querySelector('#studio-corner-tools')).display,scale:getComputedStyle(document.querySelector('#story-preview-controls')).transform};});assert.equal(result.color,'rgb(255, 251, 243)');assert.equal(result.bg,'rgba(0, 0, 0, 0)');assert.equal(result.dock,'none');assert(result.scale.startsWith('matrix(0.7,'));
 }
 await page.evaluate(()=>document.body.classList.remove('story-fullscreen'));assert(await page.locator('#studio-corner-tools').isVisible());
 console.log('scene-preview-layout: late metadata, resize, theme isolation, native control scale and dock restoration passed');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
