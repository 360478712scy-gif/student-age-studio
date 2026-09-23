const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});try{
 const page=await browser.newPage({viewport:{width:1280,height:720}});
 await page.setContent('<div id="large-scene" style="width:1200px;height:650px"></div>');
 for(const f of ['styles.css','scene-dialogue.css'])await page.addStyleTag({path:'standalone/'+f});
 for(const f of ['preview-text.js','scene.js'])await page.addScriptTag({path:'standalone/'+f});
 const result=await page.evaluate(()=>{
  const content='<color=#ff0000><b>荀彧</b></color> <size=150%><i>字号</i></size><u>下划线</u><s>删除线</s><br><noparse><b>原文</b></noparse><img src=x onerror="window.injected=1">';
  const doc={persons:{},talks:{1:{id:1,content,roleIds:[],roles:[]},2:{id:2,content:'普通文字',roleIds:[],roles:[]}},backgrounds:{}};
  const renderer=new StudentAgeScene.Renderer(document.querySelector('#large-scene'),{canEditDialogue:()=>true});
  renderer.draw(doc,StudentAgeScene.reconstruct(doc,1));
  const p=document.querySelector('.scene-dialogue p'),spans=[...p.querySelectorAll('span')];
  const result={text:p.textContent,red:spans.some(s=>getComputedStyle(s).color==='rgb(255, 0, 0)'),bold:spans.some(s=>getComputedStyle(s).fontWeight==='700'),italic:spans.some(s=>getComputedStyle(s).fontStyle==='italic'),br:p.querySelectorAll('br').length,unsafe:p.querySelectorAll('img,script').length};
  renderer.draw(doc,StudentAgeScene.reconstruct(doc,1),{edit:true});result.raw=document.querySelector('textarea').value;result.editSpans=p.children.length;
  renderer.draw(doc,StudentAgeScene.reconstruct(doc,2));result.next=p.textContent;result.nextSpans=p.children.length;
  renderer.dispose();return {...result,content};
 });
 assert(result.red&&result.bold&&result.italic);assert.equal(result.br,1);assert.equal(result.unsafe,0);assert(result.text.includes('<b>原文</b>'));assert.equal(result.raw,result.content);assert.equal(result.editSpans,0);assert.equal(result.next,'普通文字');assert.equal(result.nextSpans,0);
 console.log('preview-text: native formatting, safe literal fallback, edit isolation and next-line cleanup passed');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
