const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('standalone/app.js','utf8'),start=source.indexOf('const storyClaims='),end=source.indexOf('function nextId',start);
const reserved=new Set(),S={project:{id:'a'},doc:{talks:{}},deleted:[],replacements:{}};
const context={S,STUDIO_IDS:{release:ids=>ids.forEach(id=>reserved.delete(id))}};vm.createContext(context);vm.runInContext(source.slice(start,end),context);
const claim=id=>{reserved.add(id);context.trackStoryClaim(id,'talks');S.doc.talks[id]={id};};
claim(101);delete S.doc.talks[101];S.deleted=[101,7];S.replacements={101:[7],7:[8]};context.reconcileStoryClaims();assert(!reserved.has(101));assert.deepEqual(S.deleted,[7]);assert.deepEqual(S.replacements,{7:[8]});
// Redo restores the same draft row; deleting it again must still release its tombstone.
S.doc.talks[101]={id:101};context.reconcileStoryClaims();delete S.doc.talks[101];S.deleted.push(101);context.reconcileStoryClaims();assert.deepEqual(S.deleted,[7]);
claim(102);S.project={id:'b'};S.doc={talks:{}};context.reconcileStoryClaims();assert(!reserved.has(102));S.deleted=[101];context.reconcileStoryClaims();assert.deepEqual(S.deleted,[101]);console.log('story-id-claims: undo/redo/delete and project isolation passed');
