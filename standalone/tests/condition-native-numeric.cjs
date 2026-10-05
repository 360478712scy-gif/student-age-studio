'use strict';
// Use the real condition directory dialog with isolated references; never open a user's mod.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const C=require('../conditions.js'),templates=JSON.parse(fs.readFileSync(path.join(__dirname,'../condition-templates.json'),'utf8'));
for(const row of [[4,1,101,20],[4,2,101,20],[4,3,101,10,20],[7,1,3,20],[7,-1,3,20]]){
 const n=C.numeric(row);assert(n);for(const symbol of n.ops){const made=n.make(symbol,25,35);assert([1,2,3,-1].includes(made[1]));assert(templates.some(t=>C.match(made,t)));}
 for(const symbol of ['>','≤','≠','='])assert.throws(()=>n.make(symbol,25),/原版不支持/);
}
assert.deepEqual(C.numeric([7,1,3,20]).ops,['≥','<']);
assert.deepEqual(C.numeric([4,1,101,20]).ops,['≥','<','范围']);
assert.equal(C.numeric([4,3,101,20,20]).op,'范围'); // Native range has an exclusive upper bound.
for(let op=9001;op<=9006;op++)for(const type of [4,7]){const row=[type,op,101,20];assert.equal(C.numeric(row),null);assert.equal(C.evaluateExact(row,{attributes:{101:20},affection:{101:20}}),null);}
assert.equal(C.evaluateExact([999,1000]),true);assert.equal(C.evaluateExact([999,999]),false);assert.equal(C.evaluateExact([9000,600,7]),null);
assert(!templates.some(t=>[4,7].includes(t.template[0])&&t.template[1]>=9001&&t.template[1]<=9006));

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>{errors.push(e.message);console.error('Browser error:',e.message);});
  const refs={PersonCfg:{3:{id:3,name:'白雨'}},PersonAttrCfg:{101:{id:101,name:'智力'}},OtherRelationCfg:{},ConditionTypeCfg:{4:{id:4,name:'属性'},7:{id:7,name:'社交'}}};
  const staleTemplate={label:'旧好感等于',template:[7,9005,3,0],match:{0:7,1:9005},parameters:[]};
  await page.route('http://conditions.test/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><script src="/conditions.js"></script><script src="/condition-library.js"></script>'});
   if(url.pathname.startsWith('/api/')){
    const data=url.pathname==='/api/table'?{rows:refs[url.searchParams.get('name')]||{}}:url.pathname==='/api/condition-presets'?{entries:[],warnings:[route.request().method()==='POST'?'保存时已迁移原版比较。':'旧配置中未转换的比较请手动修改。']}:{templates:[staleTemplate],entries:[{origin:'original',key:'stale-numeric',title:'旧版比较组合',rows:[[7,9003,3,20]]}]};
    return route.fulfill({json:data});
   }
   return route.fulfill({contentType:'text/javascript; charset=utf-8',body:fs.readFileSync(path.join(__dirname,'..',url.pathname.slice(1)),'utf8')});
  });
  await page.goto('http://conditions.test/');
  await page.addStyleTag({path:path.join(__dirname,'../styles.css')});
  await page.evaluate(({templates,refs,staleTemplate})=>{
   window.StudentAgeSearch={matches:(q,...values)=>values.some(v=>String(v).includes(q))};
   window.STUDIO_CURRENT_PROJECT=()=> 'qa-only';window.STUDIO_PROJECTS=()=>[];
   window.qaOptions={templates:[staleTemplate,...templates],refs,projectId:'qa-only'};
   window.qaResult=null;window.StudentAgeConditionLibrary.open({...window.qaOptions,rows:[[9000,600,7],[4,9007,101,5]]}).then(value=>window.qaResult=value);
  },{templates,refs,staleTemplate});
  await page.locator('.condition-library-search').fill('智力');
  await page.locator('[data-library-key="attr:101"]').click({timeout:5000});
  const attr=page.locator('.condition-selected-card').nth(2);
  await assert.equal(await attr.locator('[data-library-operator]').textContent(),'≥');
  await attr.locator('[data-library-param="3"]').fill('20');
  await attr.locator('[data-library-operator]').click();assert.equal(await attr.locator('[data-library-operator]').textContent(),'<');
  await attr.locator('[data-library-operator]').click();assert.equal(await attr.locator('[data-library-operator]').textContent(),'范围');
  assert.match(await attr.textContent(),/上限（不含）/);
  assert.match(await attr.textContent(),/≥ 下限且 < 上限/);
  await attr.locator('[data-library-param="4"]').fill('30');
  await attr.locator('[data-library-operator]').click();assert.equal(await attr.locator('[data-library-operator]').textContent(),'≥');
  await page.locator('.condition-library-search').fill('人物好感度');
  await page.locator('[data-library-key="favor"]').click({timeout:5000});
  const favor=page.locator('.condition-selected-card').nth(3);
  assert.equal(await favor.locator('[data-library-operator]').textContent(),'≥');
  await favor.locator('[data-library-param="3"]').fill('12');
  await favor.locator('[data-library-operator]').click();assert.equal(await favor.locator('[data-library-operator]').textContent(),'<');
  await favor.locator('[data-library-operator]').click();assert.equal(await favor.locator('[data-library-operator]').textContent(),'≥');
  await page.locator('[data-library-mode="configs"]').click();
  await page.locator('[data-library-config="user"]').click();
  await page.waitForFunction(()=>document.querySelector('.condition-library-status').textContent.includes('旧配置中未转换的比较请手动修改。'));
  await page.locator('[data-preset-save]').click();
  await page.waitForFunction(()=>document.querySelector('.condition-library-status').textContent.includes('已保存用户配置。保存时已迁移原版比较。'));
  await page.locator('[data-library-apply]').click();
  assert.deepEqual(await page.evaluate(()=>window.qaResult),[[9000,600,7],[4,9007,101,5],[4,1,101,20],[7,1,3,12]]);
  await page.evaluate(()=>{window.qaResult=null;window.StudentAgeConditionLibrary.open({...window.qaOptions,rows:[[7,9003,3,20]]}).then(value=>window.qaResult=value);});
  await page.locator('.condition-library-search').fill('旧版比较组合');
  assert.equal(await page.locator('[data-library-key="stale-numeric"]').count(),0);
  assert.equal(await page.locator('[data-library-operator]').count(),0);
  assert.equal(await page.locator('[data-library-raw]').inputValue(),'7,9003,3,20');
  assert.match(await page.locator('.condition-selected-card').textContent(),/尚未转换为原版判断，请手动修改/);
  await page.locator('[data-library-apply]').click();
  assert.deepEqual(await page.evaluate(()=>window.qaResult),[[7,9003,3,20]]);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',checks:'Native defaults/operator cycles and submitted rows; exclusive range upper bound and no false equality; stale editor template/sample filtering; plugin rows unchanged; manual notice and saved preservation for unconverted legacy >; obsolete 900x preview returns unknown; preset load/save migration warnings shown; no browser errors',evidence:'Isolated real condition-library dialog in Chrome; no native app or Unity game acceptance'}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
