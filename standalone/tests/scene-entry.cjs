'use strict';
// “初始站位”改哪一句：换场景、退场或分支复位都会重建人物记录，重建之前的登场指令
// 对当前画面已经无效；编辑器必须改建立这条记录的登场句，否则预览不动还会改动上一幕。
// 这些检查只需要 scene.js 的状态机，不启动游戏、不读用户模组、不写盘。
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const sandbox={window:{},setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../scene.js'),'utf8'),sandbox);
const Scene=sandbox.window.StudentAgeScene,clone=v=>JSON.parse(JSON.stringify(v));
function make(){
  return {persons:{3:{id:3,name:'小明',gender:1},4:{id:4,name:'小红',gender:2}},faces:{},cgs:{},papers:{},
    backgrounds:{1:{id:1,name:'教室',url:'bg/class'},2:{id:2,name:'公园',url:'bg/park'}},
    events:{1:{id:1,talkId:[1]}},options:{},branchFolders:{},protagonistGender:1,talks:{}};
}
const stage=(doc,trace)=>Scene.reconstruct(doc,trace[trace.length-1],{trace,roots:[1],grade:1,reference:[2560,1440]});
const visible=(doc,trace,id)=>{const role=stage(doc,trace).roles[id];return role?.visible?role:null;};
// 编辑器的一次“初始站位”点击：读归属 → 只改那一条 → 立刻还原给预览。
const click=(doc,trace,id,axis)=>{const entry=Scene.roleEntry(doc,stage(doc,trace),id);if(!entry||entry.axis===axis)return null;assert(Scene.setRoleEntry(doc.talks[entry.talkId],entry,axis));return entry.talkId;};
let checks=0;function test(name,fn){fn();checks++;console.log('PASS '+name);}

test('换场景后说话人自动再登场：站位改当前这一幕，预览跟随且不改上一幕',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,1002,1,1,0]],nextTalk:[2]};
  doc.talks[2]={id:2,bg:2,roleIds:[3],roles:[],nextTalk:[]};
  assert.equal(visible(doc,[1,2],3).x,-800);
  assert.equal(click(doc,[1,2],3,2),2,'必须改写第 2 句');
  assert.equal(visible(doc,[1,2],3).x,800);
  assert.equal(visible(doc,[1],3).x,-800,'上一幕不能被连带改动');
});
for(const [name,last] of [['第三句',3],['第四句',4]]){
  test('换场景后隔句再登场，停在'+name+'编辑：站位改再登场那一句',()=>{
    const doc=make();
    doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,1002,1,1,0]],nextTalk:[2]};
    doc.talks[2]={id:2,bg:2,roleIds:[],roles:[],nextTalk:[3]};
    doc.talks[3]={id:3,bg:0,roleIds:[3],roles:[],nextTalk:[4]};
    doc.talks[4]={id:4,bg:0,roleIds:[3],roles:[],nextTalk:[]};
    const trace=[1,2,3,4].slice(0,last);
    assert.equal(visible(doc,trace,3).x,-800);
    assert.equal(click(doc,trace,3,2),3);
    assert.equal(visible(doc,trace,3).x,800);
    assert.equal(visible(doc,[1],3).x,-800);
  });
}
test('退场后再登场（同一场景）同样改再登场那一句',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,1002,1,1,0]],nextTalk:[2]};
  doc.talks[2]={id:2,bg:0,roleIds:[],roles:[[3,2002,0]],nextTalk:[3]};
  doc.talks[3]={id:3,bg:0,roleIds:[3],roles:[],nextTalk:[]};
  assert.equal(click(doc,[1,2,3],3,2),3);
  assert.equal(visible(doc,[1,2,3],3).x,800);
});
test('同场景内的显式登场句仍是编辑目标',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,1002,1,1,0]],nextTalk:[2]};
  doc.talks[2]={id:2,bg:0,roleIds:[3],roles:[],nextTalk:[]};
  assert.equal(click(doc,[1,2],3,2),1);
  assert.equal(visible(doc,[1,2],3).x,800);
});
test('换场景后用“人物登场”写入的显式登场句仍是编辑目标',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,1002,1,1,0]],nextTalk:[2]};
  doc.talks[2]={id:2,bg:2,roleIds:[],roles:[[3,1002,1,1,0]],nextTalk:[]};
  assert.equal(click(doc,[1,2],3,2),2);
  assert.equal(visible(doc,[1,2],3).x,800);
  assert.equal(visible(doc,[1],3).x,-800);
});
test('黑场保留（bg=-2）不重建记录：仍由原登场句决定站位',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,1002,1,1,0]],nextTalk:[2]};
  doc.talks[2]={id:2,bg:-2,roleIds:[3],roles:[],nextTalk:[]};
  assert.equal(click(doc,[1,2],3,2),1);
  assert.equal(visible(doc,[1,2],3).x,800);
});
test('换场景那一句有多位说话人：写入后同伴补全登场且不串位',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,1002,1,1,0]],nextTalk:[2]};
  doc.talks[2]={id:2,bg:2,roleIds:[3,4],roles:[],nextTalk:[]};
  const peer=visible(doc,[1,2],4);assert(peer);
  assert.equal(click(doc,[1,2],3,2),2);
  assert.deepEqual(clone(doc.talks[2].roles),[[3,1001,1,2,0],[4,1001,1,1,0]],'两位人物的隐式登场都要写明');
  assert.equal(visible(doc,[1,2],4).visible,true,'同伴不能因为这次修改而退场');
  assert.equal(visible(doc,[1,2],4).axis,peer.axis);
});
test('服装等动作带回的人物：补写登场指令且原指令保留',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,3006,2]],nextTalk:[]};
  assert.equal(click(doc,[1],3,2),1);
  assert.deepEqual(clone(doc.talks[1].roles),[[3,1001,1,2,0],[3,3006,2]]);
  const role=visible(doc,[1],3);assert.equal(role.x,800);assert.equal(role.cloth,2);
});
test('同句登场后还有位移：只改登场站位，位移指令保留',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,1002,1,1,0],[3,3004,200,0,0,.5]],nextTalk:[]};
  assert.equal(click(doc,[1],3,2),1);
  assert.deepEqual(clone(doc.talks[1].roles),[[3,1002,1,2,0],[3,3004,200,0,0,.5]]);
  assert.equal(visible(doc,[1],3).x,1000);
});
test('人物记录携带登场来源，还原过程不改写对话数据',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[3],roles:[],nextTalk:[]};
  const before=JSON.stringify(doc),role=stage(doc,[1]).roles[3];
  assert.equal(role.entryTalkId,1);assert.equal(role.entryImplicit,true);
  assert.deepEqual(clone(role.entryBlock),[[3,1001,1,1,0]]);
  assert.equal(JSON.stringify(doc),before);
});
test('没有来源记录的状态仍沿用按路径查找（兼容旧调用）',()=>{
  const doc=make();
  doc.talks[1]={id:1,bg:1,roleIds:[],roles:[[3,1002,1,2,0]],nextTalk:[]};
  const state=stage(doc,[1]);delete state.roles[3].entryTalkId;
  const entry=Scene.roleEntry(doc,state,3);
  assert.equal(entry.talkId,1);assert.equal(entry.index,0);assert.equal(entry.axis,2);
  assert.equal(Scene.roleEntry(doc,{...state,roles:{}},3),null);
});
console.log('\nSCENE_ENTRY_OWNERSHIP_OK '+checks+' checks');
