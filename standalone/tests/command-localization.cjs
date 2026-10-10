'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const C=require('../conditions.js'),E=require('../effects.js');
const templates=JSON.parse(fs.readFileSync(path.join(__dirname,'../condition-templates.json'),'utf8'));
const effects=JSON.parse(fs.readFileSync(path.join(__dirname,'../effect-templates.json'),'utf8'));
const refs={PersonCfg:{111234:{id:111234,name:'测试人物'}},MapCfg:{3:{id:3,name:'学校操场'},12:{id:12,name:'客运站'}}};
const row=[7,101,111234,3,12],before=JSON.stringify(row);
const title=C.summary([row],templates,refs);
assert.match(title,/人物所在地点/);assert.match(title,/测试人物/);assert.match(title,/学校操场/);assert.match(title,/客运站/);
assert.equal(JSON.stringify(row),before);assert.deepEqual(C.resolveTemplate(row,templates).parameters.map(p=>p.index),[2,3,4]);
assert.match(C.summary([[7,101,123456,999]],templates,refs),/编号 123456/);
assert.match(C.summary([[7,101,123456,999]],templates,refs),/编号 999/);
for(const rows of [templates,effects])for(const t of rows){assert.match(t.label,/[\u4e00-\u9fff]/);for(const p of t.parameters||[])assert.match(p.label,/[\u4e00-\u9fff]/);}
for(const r of [[52,1,111234,100],[52,3,111234],[61,98],[999,20,5105]])assert.ok(effects.find(t=>E.match(r,t)),String(r));
assert.equal(templates.find(t=>C.match([100,99,4],t)).displayOnly,true);
assert.match(C.summary([[98765,8,3]],templates,refs),/未识别条件.*参数 1 = 3/);
console.log('PASS: translated parameters, variable location lists, missing references, unknown commands, read-only semantics');
