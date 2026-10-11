'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});try{
 const page=await browser.newPage();let bound='555',unlinks=0,publishes=0;const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://workshop.test/**',async route=>{const url=new URL(route.request().url());
 if(url.pathname==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<html><body><script src="/workshop-publish-ui.js"></script></body></html>'});
 if(url.pathname==='/workshop-publish-ui.js')return route.fulfill({contentType:'text/javascript; charset=utf-8',body:fs.readFileSync(path.join(__dirname,'../workshop-publish-ui.js'),'utf8')});
 if(url.pathname==='/api/publish-prereq')return route.fulfill({json:{ready:true,steam:{available:true},manifest:{ok:true},preview:{ok:true},binding:{ok:true,publishedFileId:bound},revision:'fixture',defaults:{title:'合成测试',tags:['剧情']}}});
 if(url.pathname==='/api/publish-unbind'){unlinks++;bound='0';return route.fulfill({json:{publishedFileId:'0',revision:'fixture'}});}
 if(url.pathname==='/api/publish'){publishes++;assert.equal(bound,'0');return route.fulfill({json:{jobId:'new',state:'done',phase:'上传完成',publishedFileId:'777',percent:100}});}
 return route.fulfill({status:404,body:''});});
 await page.goto('http://workshop.test/');await page.evaluate(()=>STUDIO_PUBLISH.open({project:{id:'synthetic'}}));
 await page.locator('[data-publish-binding-editor] summary').click();
 page.once('dialog',d=>d.dismiss());await page.locator('[data-publish-unbind]').click();assert.equal(unlinks,0);
 page.once('dialog',d=>d.accept());await page.locator('[data-publish-unbind]').click();
 await page.getByText('已解除关联。点击“发布到创意工坊”可创建新条目。').waitFor();assert.equal(unlinks,1);assert.equal(publishes,0);
 assert.match(await page.locator('[data-publish-binding]').textContent(),/首次发布/);
 await page.locator('[name=changeNote]').fill('重新发布');await page.locator('[data-publish-submit]').click();await page.getByText('已关联条目 · 777').waitFor();assert.equal(publishes,1);assert.deepEqual(errors,[]);
 console.log('PASS: cancel unlink, explicit unlink, first-publish UI, new submission');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
