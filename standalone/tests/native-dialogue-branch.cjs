'use strict';
// Execute the production entry point; all edits stay in synthetic in-memory docs.
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm'),path=require('path');
const T=require('../timeline.js'),B=require('../branches.js'),R=require('../remote-talks.js');
const source=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const cut=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const entry=cut('function addConditionalBranch(', 'function openConditionSettings(');
function fixture(mode=false){
 const row={id:311001003,content:'已有对白',bg:113,roleIds:[111],roles:[[111,1002,0,1,0]],screenEffect:[4001],effect:[[1163,8,1]],nextTalk:[311001004],nextTalk2:[],check:[],future:{keep:true}};
 const d={talks:{[row.id]:row,311001004:{id:311001004,content:'成功对白'},311001005:{id:311001005,content:'失败对白'}},options:{},events:{}};
 const calls=[],b={S:{selected:row.id,doc:d,branchFolders:{},folderOpen:{},project:{originalMode:mode}},Timeline:T,ids:v=>Array.isArray(v)?v:[],editable:()=>true,talk:()=>row,openConditionSettings:(...args)=>calls.push(args),toast:m=>calls.push(m)};vm.runInNewContext(entry,b);return {b,row,d,calls};
}
for(const mode of [false,true]){
 const {b,row,d,calls}=fixture(mode),before=JSON.stringify(d);b.addConditionalBranch();b.addConditionalBranch();assert.equal(JSON.stringify(d),before);assert.equal(Object.keys(b.S.branchFolders).length,0);assert.equal(calls.length,2);assert.equal(calls[0][1],row.id);assert.equal(calls[0][2],'check');
 row.check=[[7,1,111,20]];row.nextTalk2=[311001005];const configured=JSON.stringify(d);b.addConditionalBranch();assert.equal(JSON.stringify(d),configured);assert.equal(calls.at(-1)[1],row.id);assert.equal(Object.keys(d.talks).length,3);
 const reopened=JSON.parse(configured);assert.deepEqual(reopened.talks[row.id],row);assert.equal(reopened.talks[row.id].future.keep,true);
}
{
 const {b,row,d,calls}=fixture();let id=900000001;const f=T.addCondition(d,b.S.branchFolders,row.id,()=>id++);const before=JSON.stringify(d),folders=JSON.stringify(b.S.branchFolders);b.addConditionalBranch();assert.equal(JSON.stringify(d),before);assert.equal(JSON.stringify(b.S.branchFolders),folders);assert.equal(calls[0][1],f.folder.routerId);
}
for(const field of ['option','miniGame']){const {b,row,d,calls}=fixture();row[field]=[1];const before=JSON.stringify(d);b.addConditionalBranch();assert.equal(JSON.stringify(d),before);assert.equal(typeof calls[0],'string');}
{
 const {b,calls}=fixture();b.editable=()=>false;b.addConditionalBranch();assert.equal(calls.length,0);
}
// Real modal callback writes the current row only; opening/dismissing makes no draft.
{
 const {b,row,d}=fixture();Object.assign(b,{modal:()=>{},closeModal:()=>{},$:()=>({}),allConditionTemplates:()=>[],Conditions:{mount:(_,config)=>b.config=config},mutate:(_,fn)=>fn(),renderList:()=>{},renderEditor:()=>{},scenePlayer:null});b.S.conditionRefs={};b.S.premises={};b.S.conditionsLoading=false;
 vm.runInNewContext(cut('function openConditionSettings(', 'function addOption('),b);const before=JSON.stringify(d);b.openConditionSettings('talks',row.id,'check','测试');assert.equal(JSON.stringify(d),before);b.config.onChange([[7,1,111,20]]);assert.deepEqual(row.check,[[7,1,111,20]]);assert.equal(Object.keys(d.talks).length,3);assert.deepEqual(row.roles,[[111,1002,0,1,0]]);
}
// Native gender targets stay separate, and failure empty means reuse, not end.
{
 const b={ids:v=>Array.isArray(v)?v:[],talkOptions:v=>'<option value="0">结束这段对话</option><option>'+v+'</option>'};vm.runInNewContext(cut('function targetSelect(', 'function syncTalkActionCodes('),b);
 assert.match(b.targetSelect({nextTalk2:[]},'nextTalk2','data-edit="nextTalk2"'),/沿用普通出口/);assert.doesNotMatch(b.targetSelect({nextTalk2:[]},'nextTalk2',''),/结束这段对话/);
 const html=b.targetSelect({nextTalk:[1,2]},'nextTalk','data-edit="nextTalk"');assert.match(html,/男主角去向/);assert.match(html,/女主角去向/);assert.match(html,/data-target-sex="1"/);
}
assert(!entry.includes('Timeline.addCondition('));assert(!entry.includes('newTalkId'));
console.log('NATIVE_DIALOGUE_BRANCH_OK: original/mod; repeat/cancel/read-only; native existing conditions; legacy preservation; gender targets; no generated rows');

// Native two-sex exits use the inspector, never the legacy single-target dropdown.
assert(source.includes('${conditional&&!d.legacy?`<label class="branch-continuation">'));
