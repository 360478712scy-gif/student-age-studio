'use strict';
const assert=require('assert/strict'),T=require('../timeline.js');
// Compare bulk rewiring with existing single deletion on fully specified native graph fields.
for(let n=0;n<200;n++){
 const doc={talks:{},events:{1:{id:1,talkId:[1,2]}},options:{7:{id:7,talkId:[3,4],talkId2:[2]}},future:'keep'};
 for(let i=1;i<=12;i++)doc.talks[i]={id:i,nextTalk:[(i+n)%12+1],nextTalk2:i%3?[2,4]:[],custom:{preserve:i}};
 const folders={a:{kind:'condition',baseNext:[1,2],failureNext:[3,4],continuation:{kind:'talk',talkId:1}},b:{kind:'option',continuation:{kind:'targets',targets:[1,2,3]}}};
 const replacements={1:[8],2:[],3:[9],4:[8,10]},oldDoc=structuredClone(doc),oldFolders=structuredClone(folders);
 for(const [id,to]of Object.entries(replacements))T.replace(oldDoc,oldFolders,Number(id),to);
 T.replaceMany(doc,folders,replacements);assert.deepEqual(doc,oldDoc);assert.deepEqual(folders,oldFolders);
}
const untouched={id:7,custom:{nested:[9]}};const doc={talks:{7:untouched},events:{},options:{}};T.replaceMany(doc,{}, {1:[2]});assert.deepEqual(untouched,{id:7,custom:{nested:[9]}});
console.log('BULK_REFERENCES_OK 201 cases');
