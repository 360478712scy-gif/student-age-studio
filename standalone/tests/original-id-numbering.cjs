// Synthetic rows only: never open or copy a user's project or original game data.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('standalone/app.js','utf8');
const take=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
function fixture(original=false){
 const S={event:'12',project:{},autoRenumber:true,order:[71,70],branchFolders:{},
  catalogAll:{events:new Set(original?['12']:[]),talks:new Set(),options:new Set()},
  catalogIds:{events:new Set(),talks:new Set(),options:new Set()},catalogTalkIds:new Set(),
  localIds:{events:[12],talks:[70,71],options:[90]},pinned:{talks:new Set(),options:new Set()},
  doc:{events:{12:{id:12,talkId:[71]}},talks:{70:{id:70},71:{id:71,option:[90]}},options:{90:{id:90,next:70}},talkOwners:{70:[12],71:[12]}}};
 const c={S,ids:v=>(v||[]).map(Number),values:Object.values,Timeline:{internals:()=>new Set()},conditionFolderIndex:()=>new Map(),branchBlock:()=>[],Remote:{info:()=>null},IndexedTalks:{keysWithField:(table,key)=>Object.keys(table).filter(id=>table[id][key])},renumberWarned:new Set(),toast(){},document:{querySelector:()=>null},conditionEditing:()=>false,editable:()=>true,renumberPending:false,renumberDeferred:false,runRenumber:async()=>{throw Error('original IDs must never reach mapping API');}};
 vm.createContext(c);vm.runInContext(take('function eventTraversal(', 'async function renameEvent(')+take('async function renumberEvent(', 'function conditionEditing(')+take('function renumberableEvent(', '// ---- Speakers:'),c);return c;
}
(async()=>{
 // An original event remains original even after its override becomes local on save/reopen.
 const original=fixture(true);
 assert.equal(original.renumberPlan(12),null,'locally overridden original event must retain its native dialogue/option IDs');
 assert.equal(original.renumberableEvent(),null,'adding dialogue in an original event must not enable event-range numbering');
 assert.equal(await original.renumberEvent(12),false);
 original.S.doc.talks[71].content='编辑后的台词';original.S.order.reverse();
 assert.equal(original.renumberPlan(12),null,'editing and reordering must not rename original IDs');
 assert.deepEqual(Object.keys(original.S.doc.talks),['70','71']);
 // Newly authored events still get automatic numbering, including options.
 const custom=fixture();
 assert.deepEqual(JSON.parse(JSON.stringify(custom.renumberPlan(12))),{TalkCfg:{70:12002,71:12001},OptionCfg:{90:1201}});
 assert.equal(custom.renumberableEvent(),12);
 // Original dialogue and option overrides reused in a custom event also retain their identity.
 custom.S.catalogAll.talks.add('70');custom.S.catalogAll.options.add('90');
 assert.deepEqual(JSON.parse(JSON.stringify(custom.renumberPlan(12))),{TalkCfg:{71:12001},OptionCfg:{}});
 custom.S.project.originalMode=true;assert.equal(custom.renumberPlan(12),null);
 console.log('original-id-numbering: original overrides preserved; custom numbering retained');
})().catch(e=>{console.error(e);process.exitCode=1;});
