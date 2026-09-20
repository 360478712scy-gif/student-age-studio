const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
 const classes=new Set(),fonts=[],files=['male','female','neutral'].flatMap(g=>['dialogue','name','history','history-name'].map(k=>k+'-'+g+'.png')).concat(['key-bg','key-tab','key-shift','key-esc'].map(k=>k+'.png'));
 const context={window:{},innerWidth:1920,innerHeight:1080,addEventListener(){},console:{warn(){}},encodeURIComponent,
  document:{documentElement:{style:{setProperty(){}},classList:{add:n=>classes.add(n)}},fonts:{add(){}}},
  fetch:async()=>({ok:true,json:async()=>({files,colors:{}})}),
  Image:class{set src(url){queueMicrotask(()=>url.includes('history-male.png')?this.onerror():this.onload());}},
  FontFace:class{load(){return new Promise(resolve=>fonts.push(()=>resolve(this)));}}
 };
 vm.runInNewContext(fs.readFileSync('standalone/preview-ui.js','utf8'),context);
 let finished=false;const task=context.window.StudentAgePreviewUI.load().then(()=>finished=true);await new Promise(setImmediate);
 assert(classes.has('game-ui-ready'),'dialogue must become ready before fonts');assert(classes.has('game-controls-ready'),'native controls must not wait for history');assert(!classes.has('game-history-ready'),'missing history frame retains its own fallback');assert.equal(finished,false);assert.equal(fonts.length,2);
 fonts.forEach(done=>done());await task;assert(classes.has('game-ui-ready'),'unrelated failed image must not remove ready dialogue');
 console.log('preview-ui-loading: late fonts and missing history do not block dialogue or controls');
})().catch(e=>{console.error(e);process.exitCode=1;});
