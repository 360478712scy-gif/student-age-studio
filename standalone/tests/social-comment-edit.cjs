// Production social components; isolated fixtures exercise edits and persistence.
const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{const browser=await chromium.launch({executablePath:process.env.CHROME_PATH,headless:true});try{
const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('http://studio.test/',route=>route.fulfill({contentType:'text/html',body:'<div id="host"></div>'}));await page.goto('http://studio.test/');
for(const file of ['branch-tree.js','social-media.js','social.js'])await page.addScriptTag({path:path.resolve(__dirname,'..',file)});
await page.evaluate(async()=>{window.StudentAgeCharacterUI={esc:String};window.StudentAgeSearch={matches:()=>true};window.StudentAgeRecordLabels={html:(id,name)=>name,attrs:()=>''};window.STUDIO_SAVE_REVIEW={confirm:async()=>true};
window.data={project:{},revision:'a',posts:{101:{id:101,role:1,content:'动态',comments:[[10101,2]],options:[10104],thumbs:[],imgs:[],cond:[],future:{keep:true}}},comments:{10101:{id:10101,roles:[2],parent:0,content:'杰哥原评论',comments:[[10102,3],[10103,4]],options:[],condition:[],effect:[],future:{keep:true}},10102:{id:10102,roles:[1,2],parent:10101,content:'已有回复',comments:[],options:[],condition:[],effect:[]},10104:{id:10104,roles:[0],parent:0,content:'白雨选项',comments:[],options:[],condition:[],effect:[]}},accounts:[{id:0,name:'白雨'},{id:1,name:'小雅'},{id:2,name:'杰哥'},{id:3,name:'小夏'}],referencePosts:{},referenceComments:{10103:{id:10103,roles:[3,2],parent:10101,content:'继承的回复',comments:[],options:[],condition:[],effect:[],future:{original:true}}},editor:{disabledOptions:{}}};
window.social=StudentAgeSocial.create(document.querySelector('#host'),{project:{id:'test'},status:(message,error)=>window.lastStatus={message,error},api:async(url,body)=>{if(body){Object.assign(data,structuredClone(body));data.revision+='x';}return structuredClone(data);}});await social.load();});
await page.click('[data-comment-card="10101"] [data-social="settings"]');
if(process.env.EXPECT_REPRO){assert.equal(await page.locator('[data-social-comment-delay]').count(),0);console.log('REPRO: existing comment settings have no delay control');return;}
assert.equal(await page.locator('[data-social-comment-delay]').inputValue(),'2');
await page.fill('[data-social-comment-delay]','1');assert.equal(await page.evaluate(()=>social.state.posts[101].comments[0][1]),1);
await page.evaluate(()=>social.undo());assert.equal(await page.locator('[data-social-comment-delay]').inputValue(),'2');await page.evaluate(()=>social.redo());
await page.fill('#social-current-comment','修改后的杰哥评论');
await page.click('[data-social="choose-comment-author"]');await page.click('[data-social-account="3"]');
assert.deepEqual(await page.evaluate(()=>social.state.comments[10102].roles),[1,3]);
await page.click('[data-comment-card="10102"] .social-comment-text');assert.equal(await page.locator('#social-current-comment').inputValue(),'已有回复');
await page.fill('[data-social-comment-delay]','1');assert.equal(await page.evaluate(()=>social.state.comments[10101].comments[0][1]),1);
await page.fill('[data-social-comment-delay]','-2');assert.equal(await page.evaluate(()=>social.state.comments[10101].comments[0][1]),1);assert.equal(await page.evaluate(()=>lastStatus.error),true);
await page.fill('[data-social-comment-delay]','2');await page.click('[data-comment-card="10103"] .social-comment-text');await page.fill('[data-social-comment-delay]','1');await page.fill('#social-current-comment','修改继承的回复');
assert.deepEqual(await page.evaluate(()=>social.state.comments[10103].future),{original:true});
await page.evaluate(async()=>{await social.save();await social.load();});
assert.equal(await page.evaluate(()=>social.state.posts[101].comments[0][1]),1);assert.equal(await page.evaluate(()=>social.state.comments[10101].content),'修改后的杰哥评论');assert.deepEqual(await page.evaluate(()=>social.state.comments[10101].future),{keep:true});
assert.equal(await page.evaluate(()=>social.state.comments[10101].comments[0][1]),2);assert.equal(await page.evaluate(()=>social.state.comments[10101].comments[1][1]),1);assert.equal(await page.evaluate(()=>social.state.comments[10103].content),'修改继承的回复');
await page.click('[data-comment-card="10104"] .social-comment-text');assert.equal(await page.locator('[data-social-comment-delay]').count(),0);
await page.click('[data-social="source"][data-source="reference"]');assert.equal(await page.locator('[data-social-comment-delay]:not([disabled])').count(),0);assert.deepEqual(errors,[]);
console.log('PASS: root/reply/inherited delay edits, text/author, undo/redo, invalid delay, save/reload, player and read-only guards');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
