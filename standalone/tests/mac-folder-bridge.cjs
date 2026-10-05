'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const app=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const start=app.indexOf('if(window.webkit?.messageHandlers?.studioAssetFolder){');
const end=app.indexOf('window.STUDIO_PICKER_CONTEXT=',start);
assert(start>=0&&end>start,'Production Mac folder bridge was not found');
const bridge=app.slice(start,end);
const swift=fs.readFileSync(path.join(__dirname,'../../desktop/StudioApp.swift'),'utf8');
const script=swift.match(/source: "(window\.STUDIO_NATIVE_CAPABILITIES[^"\n]+)",\s*injectionTime: \.atDocumentStart, forMainFrameOnly: true/);
assert(script,'New Mac host must declare video folder support at document start');
const guard=swift.match(/let kind = request\["kind"\] as\? String, (\[[^\n]+\])\.contains\(kind\)/);
assert(guard,'Production Swift picker whitelist was not found');
const newKinds=JSON.parse(guard[1]);
// The full client shipped before video support silently ignores unknown kinds.
const oldKinds=['portrait','background','cg','audio','social','avatar','mods','game','cache'];
function host(kinds,capabilityScript){
 const sent=[],callbacks=[],window={};
 window.webkit={messageHandlers:{studioAssetFolder:{postMessage(message){
  sent.push(message);
  if(kinds.includes(message.kind)){
   const response={id:message.id,path:'/Users/test/Video Folder'};
   callbacks.push(response);
   window.STUDIO_ASSET_FOLDER_CHOSEN(response);
  }
 }}}};
 const context=vm.createContext({window});
 if(capabilityScript)vm.runInContext(capabilityScript,context);
 vm.runInContext(bridge,context);
 return {window,sent,callbacks};
}
async function choose(native,kind){
 let timer;
 try{return await Promise.race([native.window.STUDIO_CHOOSE_ASSET_FOLDER(kind),
  new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Native picker did not reply for '+kind)),250);})]);}
 finally{clearTimeout(timer);}
}
(async()=>{
 const old=host(oldKinds);
 assert.equal(await choose(old,'video'),'/Users/test/Video Folder');
 assert.equal(old.sent[0].kind,'audio');
 assert.equal(old.callbacks.length,1,'Old whitelist must actually invoke the production callback');
 const modern=host(newKinds,script[1]);
 assert.equal(await choose(modern,'video'),'/Users/test/Video Folder');
 assert.equal(modern.sent[0].kind,'video');
 assert.equal(modern.callbacks.length,1);
 for(const native of [old,modern]){
  assert.equal(await choose(native,'audio'),'/Users/test/Video Folder');
  assert.equal(native.sent[1].kind,'audio');
 }
 console.log('mac-folder-bridge: old whitelist video callback, document-start capability, new video title kind and unchanged audio passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
