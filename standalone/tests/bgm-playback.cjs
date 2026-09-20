'use strict';
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const ctx={window:{},setTimeout,clearTimeout};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../scene.js'),'utf8'),ctx);
const cues={bgm:[{id:'a',audioId:7,talkIds:[1,2],loop:true,volume:1},{id:'continue',audioId:0,talkIds:[3],loop:true,volume:1},{id:'a-again',audioId:7,talkIds:[4],loop:true,volume:1},{id:'silence',audioId:9,talkIds:[5,6],loop:true,volume:1},{id:'silent-continue',audioId:0,talkIds:[7,8],loop:true,volume:1},{id:'b',audioId:8,talkIds:[9],loop:true,volume:1}],sfx:{}};
let made=[];const player=new ctx.window.StudentAgeScene.AudioPlayer({getCues:()=>cues,getUrl:id=>'test/'+id,createAudio:url=>{const audio={url,currentTime:0,plays:0,ended:false,play(){this.plays++;this.paused=false;return {catch(){}};},pause(){this.paused=true;}};made.push(audio);return audio;}});
player.enter(1,[1]);const first=player.bgm;first.currentTime=12;
for(const id of [2,3,4]){player.enter(id,Array.from({length:id},(_,i)=>i+1));assert.equal(player.bgm,first);assert.equal(first.currentTime,12);assert.equal(first.plays,1);}
player.enter(5,[1,2,3,4,5]);const silent=player.bgm;assert.equal(silent.url,'test/9');silent.currentTime=1.1;
for(const id of [6,7,8]){player.enter(id,Array.from({length:id},(_,i)=>i+1));assert.equal(player.bgm,silent);assert.equal(silent.currentTime,1.1);assert.equal(silent.plays,1);}
player.enter(9,[1,2,3,4,5,6,7,8,9]);assert.equal(player.bgm.url,'test/8');assert.equal(made.length,3);player.stop();
console.log('Music, 0, same-track range, silence, 0 after silence and new music: no replay or lost position.');
