'use strict';
// 3003 强调放大：原版参数为 0 时缩成 0，其他情况放大到 1.1 倍；插件编辑模式（UP 非官方补丁）按参数倍数缩放。
// 3012/3013 黑影与取消黑影只切换状态。只用 scene.js 的状态机，不读模组、不写盘。
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const sandbox={window:{},setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../scene.js'),'utf8'),sandbox);
const Scene=sandbox.window.StudentAgeScene;
const doc={persons:{3:{id:3,name:'小明',gender:1}},faces:{},cgs:{},papers:{},backgrounds:{},events:{1:{id:1,talkId:[1]}},options:{},branchFolders:{},protagonistGender:1,
  talks:{1:{id:1,content:'一',roleIds:[3],roles:[[3,1002,1,3,0]],nextTalk:[2]},2:{id:2,content:'二',roleIds:[3],roles:[[3,3003,1.5,0],[3,3012]],nextTalk:[3]},3:{id:3,content:'三',roleIds:[3],roles:[[3,3013]],nextTalk:[]}}};
const role=(trace)=>Scene.reconstruct(doc,trace[trace.length-1],{trace,roots:[1],grade:1,reference:[2560,1440]}).roles[3];
let checks=0;const test=(name,fn)=>{fn();checks++;console.log('PASS '+name);};
test('原版：3003 放大到 1.1 倍，参数 0 缩成 0',()=>{
  sandbox.window.STUDIO_WORKSHOP_NAV={pluginEditing:()=>false};
  assert.equal(Math.round(role([1,2]).scale*100)/100,1.1);
  doc.talks[2].roles[0][2]=0;assert.equal(role([1,2]).scale,0);doc.talks[2].roles[0][2]=1.5;
});
test('插件编辑模式：3003 按倍数缩放',()=>{
  sandbox.window.STUDIO_WORKSHOP_NAV={pluginEditing:()=>true};
  assert.equal(role([1,2]).scale,1.5);
  doc.talks[2].roles[0]=[3,3003];assert.equal(Math.round(role([1,2]).scale*100)/100,1.1,'没有参数时仍按原版 1.1 倍');doc.talks[2].roles[0]=[3,3003,1.5,0];
});
test('3012 变黑影，3013 恢复',()=>{
  assert.equal(role([1,2]).shadow,true);
  assert.equal(role([1,2,3]).shadow,false);
});
console.log(checks+' checks passed');
