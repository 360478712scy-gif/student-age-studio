'use strict';
// Full editor + real music API. Point STUDIO_TEST_READY at an isolated server's ready JSON.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const address=new URL(JSON.parse(fs.readFileSync(process.env.STUDIO_TEST_READY,'utf8')).url);
 const headers={'X-Studio-Token':address.hash.slice(1),'Content-Type':'application/json'};
 const preferences=async()=>{const response=await fetch(address.origin+'/api/editor-music',{headers});assert(response.ok);return (await response.json()).preferences;};
 const waitSaved=async expected=>{const end=Date.now()+5000;while(Date.now()<end){const value=await preferences();if(Object.entries(expected).every(([key,want])=>value[key]===want))return value;await new Promise(done=>setTimeout(done,25));}assert.fail('Saved preferences did not reach '+JSON.stringify(expected)+': '+JSON.stringify(await preferences()));};
 const seed=await fetch(address.origin+'/api/editor-music',{method:'POST',headers,body:JSON.stringify({playing:true,volume:.35,collapsed:false,mode:'list'})});assert(seed.ok);
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{}),args:['--autoplay-policy=no-user-gesture-required']});
 const errors=[],checks=[];let page;
 const open=async()=>{page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',error=>errors.push(error.message));await page.goto(address.href);await page.waitForFunction(()=>window.StudentAgeEditorMusic?.getState().tracks.length>0&&!STUDIO_BOOTSTRAPPING);};
 const playing=()=>page.waitForFunction(()=>!StudentAgeEditorMusic.audio.paused&&StudentAgeEditorMusic.audio.currentTime>0);
 const paused=()=>page.waitForFunction(()=>StudentAgeEditorMusic.audio.paused&&!StudentAgeEditorMusic.getState().wantsPlayback);
 try{
  await open();await playing();
  await page.locator('#editor-music .vinyl').click();await page.close();
  await waitSaved({playing:false});await open();await paused();checks.push('Manual pause survives closing before debounce and reopening');
  await page.locator('#editor-music [data-volume]').evaluate(input=>{input.value='0.18';input.dispatchEvent(new Event('input',{bubbles:true}));});await page.close();
  await waitSaved({playing:false,volume:.18});await open();await paused();assert.equal(await page.evaluate(()=>StudentAgeEditorMusic.audio.volume),.18);checks.push('Last volume survives immediate close and paused restart');
  await page.locator('#editor-music .vinyl').click();await page.close();await waitSaved({playing:true});await open();await playing();assert.equal(await page.evaluate(()=>StudentAgeEditorMusic.audio.volume),.18);checks.push('Manual play survives immediate close and resumes on startup');
  const position=await page.evaluate(()=>{window.releaseA=StudentAgeAudioFocus.hold();window.releaseB=StudentAgeAudioFocus.hold();return StudentAgeEditorMusic.audio.currentTime;});
  assert.equal(await page.evaluate(()=>StudentAgeEditorMusic.audio.paused),true);await page.evaluate(()=>releaseA());await page.waitForTimeout(250);assert.equal(await page.evaluate(()=>StudentAgeEditorMusic.audio.paused),true);
  await page.evaluate(()=>releaseB());await playing();assert((await page.evaluate(()=>StudentAgeEditorMusic.audio.currentTime))>=position);assert.equal((await preferences()).playing,true);checks.push('Overlapping previews resume from position without saving automatic pause');
  await page.evaluate(()=>window.releaseA=StudentAgeAudioFocus.hold());await page.close();await open();await playing();checks.push('Closing during automatic pause preserves playback intent');
  await page.evaluate(()=>window.releaseA=StudentAgeAudioFocus.hold());await page.locator('#editor-music .vinyl').click();await page.evaluate(()=>releaseA());await page.waitForTimeout(250);await paused();await waitSaved({playing:false});await page.close();await open();await paused();checks.push('Manual pause during preview cancels recovery and persists');
  await page.locator('#editor-music [data-music="next"]').click();await playing();await waitSaved({playing:true});checks.push('Manual track switch saves playback intent');
  await page.locator('#editor-music .vinyl').click();await waitSaved({playing:false});await page.locator('#editor-music [data-music="playlist"]').click();await page.locator('#editor-music [data-track="0"]').click();await playing();await waitSaved({playing:true});checks.push('Manual playlist selection saves playback intent');
  await page.evaluate(async()=>{window.audition=new Audio(StudentAgeEditorMusic.audio.src);StudentAgeAudioFocus.track(audition);await audition.play();});await page.waitForFunction(()=>StudentAgeEditorMusic.audio.paused&&StudentAgeEditorMusic.getState().interrupted);
  await page.evaluate(()=>audition.pause());await playing();assert.equal((await preferences()).playing,true);checks.push('Actual detached audio audition pauses then restores personal playback');
  await page.evaluate(()=>STUDIO_WORKSHOP_NAV?.hide?.());
  const result={ok:true,checks,errors};assert.deepEqual(errors,[]);
  if(process.env.STUDIO_TEST_OUTPUT){fs.mkdirSync(process.env.STUDIO_TEST_OUTPUT,{recursive:true});fs.writeFileSync(path.join(process.env.STUDIO_TEST_OUTPUT,'music-preferences-results.json'),JSON.stringify(result,null,2));await page.screenshot({path:path.join(process.env.STUDIO_TEST_OUTPUT,'music-preferences-full-editor.png')});}
  console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
