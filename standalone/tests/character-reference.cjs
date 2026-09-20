// Regression: delayed reference must not resize already editable art.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
 const svg=(w,h)=>'data:image/svg+xml;base64,'+Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="100%" height="100%" fill="green"/></svg>`).toString('base64');
 const person={id:105,name:'参考',gender:2,url:['young'],url2:['adult'],l2d:['model'],l2d2:['model2'],l2dParm:[[1500,0,500,0]],l2dParm2:[[1500,0,500,0]],bubbleParm:[960],bubbleParm2:[960]};
 const own={...person,id:1999999,name:'测试',url:['Mods/test/reference0.png'],url2:['Mods/test/reference1.png'],l2d:[],l2d2:[],urlParm:[0,450,1.5],urlParm2:[0,450,1.5]};
 const fixture={person,own,frames:{},images:{'role_head/role_qingya2':svg(450,450),'role_head/adult':svg(450,450),'role_half/role_qingya2':svg(646,1000),'role_half/adult':svg(646,1000)},sizes:{'role_head/adult':[450,450],'role_half/adult':[646,1000],'role_half/role_qingya2':[646,1000]}};
 for(const grade of [0,1]){fixture.frames[grade]={frame:{bounds:[-.25,-.5,.5,1]},available:[0]};fixture.images[`portrait-cache/105-${grade}-0-0.png`]=svg(500,1000);fixture.images[`Mods/test/reference${grade}.png`]=svg(500,1000);fixture.sizes[`Mods/test/reference${grade}.png`]=[500,1000];}
 await page.route('http://qa/**',async route=>{const u=new URL(route.request().url());if(u.pathname==='/api/talk-ui')return route.fulfill({status:404,body:'{}',contentType:'application/json'});return route.fulfill({body:'<div id="host"><div id="character-form"></div><div id="character-preview"></div></div>',contentType:'text/html'});});
 await page.goto('http://qa/');for(const f of ['styles.css','characters.css','scene-dialogue.css','character-model.css'])await page.addStyleTag({path:'standalone/'+f});await page.addStyleTag({content:'body{overflow:auto;padding:24px;background:#252031;color:#eee}#host{width:100%}#character-form{padding:0;max-height:none}'});
 for(const f of ['character-ui.js','scene.js','character-images.js','character-model.js'])await page.addScriptTag({path:'standalone/'+f});
 await page.evaluate(f=>{window.fixture=f;window.S={grade:1,selected:1999999,cloth:0,previewFace:0,data:{tables:{PersonCfg:{referenceRows:{105:f.person}}}}};window.p=structuredClone(f.own);window.delay=0;window.unblock=null;
 window.ctx={S,host:document.querySelector('#host'),person:()=>p,readonly:()=>false,all:()=>({}),change:fn=>fn(),imageURL:path=>fixture.images[path]||'bad.png',options:{project:{id:'test'},token:'qa',api:async(url,data)=>{if(url==='/api/portraits'){if(delay)await new Promise(r=>unblock=r);return fixture.frames[S.grade];}return Object.fromEntries(data.paths.map(k=>[k,fixture.sizes[k]]).filter(x=>x[1]));}}};window.model=StudentAgeCharacterModel.create(ctx);model.render();},fixture);
 const ready=()=>page.waitForFunction(()=>[...document.querySelectorAll('.model-art')].every(x=>x.style.visibility==='visible'));
 const sizes=()=>page.locator('.model-art').evaluateAll(nodes=>nodes.map(n=>({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height,top:n.offsetTop})));
 await ready();let r=await sizes();assert(Math.abs(r[0].height-r[1].height)<.1,JSON.stringify(r));assert(Math.abs(r[0].width-r[1].width)<.7,JSON.stringify(r));
 // A delayed reference must not expose temporary incorrect geometry.
 await page.evaluate(()=>{delay=1;model.render();});await page.waitForFunction(()=>!!unblock);assert.equal(await page.locator('.model-art').evaluateAll(ns=>ns.some(n=>n.style.visibility==='visible')),false);await page.evaluate(()=>{delay=0;unblock();});await ready();const settled=await sizes();assert.deepEqual(settled,r);
 // Cached image/API work cannot change the scale while dragging.
 const art=page.locator('[data-model-stage=own] .model-art'),box=await art.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+20,box.y+box.height/2-12,{steps:5});let moved=await sizes();assert.equal(moved[0].height,r[0].height);await page.mouse.up();assert.equal((await sizes())[0].height,r[0].height);
 await page.locator('[data-model-grade="0"]').click();await ready();r=await sizes();assert(Math.abs(r[0].height-r[1].height)<.1);await page.locator('[data-model-grade="1"]').click();await ready();
 // Fixed-size head widgets must not inflate high-resolution imports.
 await page.evaluate(()=>{const pic=fixture.images['role_head/role_qingya2'];fixture.images['Mods/test/reference1_head.png']=pic;fixture.sizes['Mods/test/reference1_head.png']=[900,900];model.state.kind='head';model.render();});await ready();r=await sizes();assert.deepEqual(r[0],r[1]);
 // Native-size companion photos retain a common unit scale; loading is gated.
 await page.evaluate(()=>{fixture.images['Mods/test/reference1_half.png']=fixture.images['role_half/role_qingya2'];fixture.sizes['Mods/test/reference1_half.png']=fixture.sizes['role_half/role_qingya2'];model.state.kind='half';model.render();});await ready();r=await sizes();assert.deepEqual(r[0],r[1]);
 await page.evaluate(()=>{model.state.kind='portrait';model.render();});await ready();
 assert.deepEqual(errors,[]);console.log('PASS character reference, delayed loading, dragging, grades, head, half');
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
