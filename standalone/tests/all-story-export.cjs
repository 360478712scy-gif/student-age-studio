const assert=require('node:assert/strict'),H=require('../history.js'),Timeline=require('../timeline.js'),Branches=require('../branches.js'),text=require('../dialogue-text.js'),Remote=require('../remote-talks.js');
(async()=>{
 const talks={},summaries={};for(let n=1;n<=230;n++){const id=1000+n,row={id,content:'正文'+n,roleIds:[1],nextTalk:n===230?[]:[id+1],option:[]};talks[id]=row;const {content,...record}=row;summaries[id]={record,fields:Object.keys(row)};}
 const pages=[];const remote=Remote.create({version:1,generation:'test',ids:Object.keys(talks),summaries},async(_,p)=>{pages.push(p.ids);return {generation:'test',revision:'r1',rows:p.ids.map(id=>[id,JSON.stringify(talks[id])]),remaining:[]};},'r1');remote[1001].content='未保存的修改';
 const doc={talks:remote,events:{1:{id:1,title:'小雅剧情',talkId:[1001]},2:{id:2,title:'共享事件',talkId:[1229]},3:{id:3,title:'通知',content:'通知正文'},4:{id:4,title:'空事件',talkId:[]}},persons:{1:{id:1,name:'小雅'}},options:{}};
 const result=await H.allStories(doc,[4,2,1,3],{Timeline,Branches,text,load:keys=>Remote.ensure(remote,keys)});
 assert(result.indexOf('空事件')<result.indexOf('共享事件'));assert(result.includes('小雅 未保存的修改'));assert(result.includes('小雅 正文230'));assert.equal(result.match(/小雅 正文230/g).length,2);assert(result.includes('通知正文'));assert(result.includes('（暂无对话）'));assert(pages.every(p=>p.length<=100));assert.equal(remote[1001].content,'未保存的修改');
 const branchDoc={events:{1:{id:1,title:'分支',talkId:[1]}},persons:{},options:{10:{id:10,content:'去公园',talkId:[2]}},talks:{1:{id:1,content:'选择',option:[10],nextTalk:[3]},2:{id:2,content:'选项内容',nextTalk:[3]},3:{id:3,content:'后文',nextTalk:[4]},4:{id:4,content:'内部',nextTalk:[5],nextTalk2:[6]},5:{id:5,content:'条件正文',nextTalk:[6]},6:{id:6,content:'内部退出',nextTalk:[1]}}};
 const f={'3:b1':{kind:'condition',parentTalkId:3,branchId:1,routerId:4,exitId:6,endId:99,talkIds:[5],baseNext:[]}};
 const branchText=await H.allStories(branchDoc,[1],{Timeline,Branches,text,branchFolders:f});assert(branchText.includes('选项 去公园'));assert(branchText.includes('分支1'));assert(branchText.includes('条件正文'));assert(!branchText.includes('内部'));assert.equal(branchText.match(/旁白 选择/g).length,1);
 await assert.rejects(()=>H.allStories(doc,[],{Timeline,Branches,text}),/没有/);
 await assert.rejects(()=>H.allStories(doc,[1],{Timeline,Branches,text,load:()=>{throw Error('读取失败');}}),/读取失败/);
 console.log('all-story-export: pages, drafts, sort, shared/cyclic paths, options, branches, empty/notice and failure passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
