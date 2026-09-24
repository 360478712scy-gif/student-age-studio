(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeConditions=api;})(typeof window==='object'?window:globalThis,()=>{
'use strict';
const copy=value=>JSON.parse(JSON.stringify(value)),escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Keep native numeric instructions intact; editing never drops an invalid token.
function parseCommand(text){
 text=String(text).replace(/，/g,',');let body=text.trim();
 if(body.startsWith('[')&&body.endsWith(']'))body=body.slice(1,-1).trim();
 if(!body)return {text,error:'请输入参数，用逗号隔开。'};
 const parts=body.split(',').map(v=>v.trim()),numeric=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
 if(parts.some(v=>!numeric.test(v)||!Number.isFinite(Number(v))))return {text,error:'每项都应为数字，用逗号隔开；当前输入尚未应用。'};
 return {text,values:parts.map(Number)};
}
// Compact editors for arrays without a dedicated visual control. Strings use JSON
// quoting only when needed, so commas/newlines inside an existing value survive.
function parameterText(values){return values.map(v=>typeof v==='string'?(/[，,"\n\r]|^\s|\s$/.test(v)||v===''?JSON.stringify(v):v):JSON.stringify(v)).join(',');}
function parameterHTML(values,attribute,type){return `<span class="command-inline"><input type="text" ${attribute} data-parameter-type="${escape(type)}" value="${escape(parameterText(values))}" placeholder="用逗号分隔参数" autocomplete="off" spellcheck="false"><small class="command-input-error" role="status"></small></span>`;}
function readParameterInput(input){
 let text=input.value,quoted=false,escaped=false,normalized='';for(const c of text){if(c==='"'&&!escaped)quoted=!quoted;normalized+=c==='，'&&!quoted?',':c;escaped=c==='\\'&&!escaped;}
 if(normalized!==text){const pos=input.selectionStart;input.value=normalized;if(pos!==null)input.setSelectionRange(pos,pos);}text=normalized;
 let values=[],error='',token='',quote=false,slash=false;const parts=[];
 for(const c of text){if(c==='"'&&!slash)quote=!quote;if(c===','&&!quote){parts.push(token.trim());token='';}else token+=c;slash=c==='\\'&&!slash;}if(text.trim())parts.push(token.trim());
 try{if(quote)throw Error('引号尚未闭合。');values=parts.map(v=>{if(!v)throw Error('逗号之间需要填写参数。');const type=input.dataset.parameterType;if(type==='string')return v.startsWith('"')?JSON.parse(v):v;if(type==='bool'||type==='boolean'){if(!['true','false'].includes(v))throw Error('请填写 true 或 false。');return v==='true';}const result=parseCommand(v);if(result.error||result.values.length!==1)throw Error('每项都应为数字。');const n=result.values[0];if(/int|long/.test(type)&&(!Number.isSafeInteger(n)||type==='int'&&(n>2147483647||n<-2147483648)))throw Error('请填写有效的整数。');return n;});}catch(e){error=e.message;}
 input.setCustomValidity(error);input.setAttribute('aria-invalid',String(!!error));input.parentElement.querySelector('.command-input-error').textContent=error;return {values,error};
}
function rawCommandHTML(row,attribute){return `<span class="command-inline"><input type="text" ${attribute} value="${escape((row||[]).join(','))}" aria-label="完整指令参数" placeholder="例如：3,-1,720637" autocomplete="off" spellcheck="false"><small class="command-input-error" role="status"></small></span>`;}
function readCommandInput(input){const result=parseCommand(input.value);if(result.text!==input.value){const start=input.selectionStart,end=input.selectionEnd;input.value=result.text;if(start!==null)input.setSelectionRange(start,end);}input.setCustomValidity(result.error||'');input.setAttribute('aria-invalid',String(!!result.error));const message=input.parentElement.querySelector('.command-input-error');if(message)message.textContent=result.error||'';return result;}
function match(row,t){return Array.isArray(row)&&row.length===t.template?.length&&Object.entries(t.match||{}).every(([index,value])=>Number(row[index])===Number(value));}
function label(row){const value=row?.name||row?.title||(globalThis.StudentAgeRemoteTalks?.summary(row)??row?.content)||row?.desc;return (Array.isArray(value)?value[0]:value)||'未命名内容';}
function allowed(row,range){const id=Number(row.id);return (!range?.startId||id>=range.startId)&&(!range?.endId||id<=range.endId)&&!range?.skips?.includes(id)&&(!range?.filter||range.filter.values?.includes(row[range.filter.field]));}
function summary(rows,templates,refs){return (rows||[]).map(row=>{if(Number(row[0])===52&&Number(row[1])===1&&row.length===3)return Number(row[2])===1?'恋爱状态：有恋人':'恋爱状态：单身（没有恋人）';if(Number(row[0])===52&&Number(row[1])===2&&row.length===4)return '恋爱关系：'+(Number(row[2])===1?'恋人是':'恋人不是')+(refs?.PersonCfg?.[row[3]]?.name||'人物 '+row[3]);const t=(templates||[]).find(t=>match(row,t));if(!t)return '自定义条件：'+row.join(',');return t.label+'：'+(t.parameters||[]).map(p=>p.range?.table?label(refs?.[p.range.table]?.[row[p.index]])||row[p.index]:p.choices?.find(c=>Number(c.id)===Number(row[p.index]))?.label??row[p.index]).join(' / ');}).join('，且 ');}
function mount(host,options){
 const templates=options.templates||[],refs=options.refs||{};let rows=copy(options.rows||[]),opening=false;
 function paint(){host.classList.add('condition-editor');host.innerHTML=`<p class="condition-logic">${escape(options.description||'')} ${escape(options.emptyText||'空列表表示不限制。')}</p><div class="condition-compact-list">${rows.map((row,index)=>`<div class="condition-compact-row"><button type="button" data-condition-edit="${index}">${index+1}. ${escape(summary([row],templates,refs))}</button><button type="button" data-condition-delete="${index}" aria-label="删除条件">×</button></div>`).join('')||'<p class="condition-empty">未设置条件</p>'}</div><button type="button" class="primary" data-condition-library>＋ 添加条件</button>`;if(options.readOnly)host.querySelectorAll('button').forEach(b=>b.disabled=true);}
 host.onclick=async event=>{if(options.readOnly||opening)return;const remove=event.target.closest('[data-condition-delete]');if(remove){rows.splice(Number(remove.dataset.conditionDelete),1);options.onChange?.(copy(rows));paint();return;}if(!event.target.closest('[data-condition-library],[data-condition-edit]'))return;opening=true;try{await options.loadReferences?.();if(!host.isConnected)return;const result=await window.StudentAgeConditionLibrary.open({templates,refs,localIds:options.localIds,rows,projectId:options.projectId});if(result&&host.isConnected){rows=copy(result);options.onChange?.(copy(rows));paint();}}catch(e){options.onError?.(e);}finally{opening=false;}};
 host.oninput=null;host.onchange=null;paint();return {getRows:()=>copy(rows),update(next){rows=copy(next);paint();}};
}

// ---- Official command categories: ConditionTypeCfg / EffectTypeCfg from the game's own tables (names
// simplified where the table is in traditional characters). Builtin copies cover a missing table. ----
const T2S={'齡':'龄','屬':'属','專':'专','長':'长','價':'价','觀':'观','狀':'状','態':'态','與':'与','壓':'压','學':'学','習':'习','戀':'恋','愛':'爱','關':'关','動':'动','閱':'阅','讀':'读','標':'标','機':'机','間':'间','戰':'战','遊':'游','戲':'戏','創':'创','畫':'画','棄':'弃','籃':'篮','慶':'庆','導':'导','結':'结','斷':'断','個':'个','這':'这','為':'为','說':'说','話':'话','時':'时','開':'开','門':'门','錢':'钱','點':'点','選':'选','項':'项','條':'条','數':'数','據':'据','級':'级','體':'体','記':'记','錄':'录','達':'达','認':'认','識':'识','對':'对','過':'过','進':'进','還':'还','沒':'没','從':'从','會':'会','讓':'让','們':'们','東':'东','車':'车','電':'电','腦':'脑','網':'网','絡':'络','樂':'乐','節':'节','業':'业','務':'务','產':'产','場':'场','員':'员','語':'语','裡':'里','頭':'头','發':'发','風':'风','雲':'云','顯':'显','設':'设','統':'统','計':'计','圖':'图','書':'书','館':'馆','課':'课','師':'师','較':'较','參':'参','賽':'赛','獎':'奖','勵':'励','罰':'罚','錯':'错','誤':'误','復':'复','試':'试','驗':'验','題':'题','難':'难','簡':'简','單':'单','複':'复','雜':'杂','總':'总','額':'额','幾':'几','種':'种','類':'类','別':'别','隊':'队','組':'组','織':'织','聯':'联','繫':'系','續':'续','傳':'传','變':'变','換':'换','轉':'转','運':'运','輸':'输','階':'阶','層':'层','線':'线','邊':'边','圓':'圆','區':'区','圍':'围','範':'范','準':'准','確':'确','誰':'谁','響':'响','應':'应','執':'执','鎖':'锁','啟':'启','禮':'礼','贈':'赠','歡':'欢','週':'周','連':'连','觸':'触','滿':'满','檢':'检','證':'证','訊':'讯','談':'谈','論':'论','討':'讨','寫':'写','練':'练','藝':'艺','術':'术','繪':'绘','攝':'摄','競':'竞','遠':'远','離':'离','親':'亲','係':'系','侶':'侣','約':'约','獨':'独','處':'处','見':'见','幫':'帮','請':'请','絕':'绝','購':'购','買':'买','賣':'卖','貨':'货','價':'价','費':'费','資':'资','財':'财','務':'务','劇':'剧','終':'终','擊':'击','擁':'拥','獲':'获','減':'减','斷':'断','決':'决','擇':'择','務':'务','銷':'销','審':'审','聽':'听','聲':'声','音':'音','樓':'楼','廳':'厅','務':'务','醫':'医','藥':'药','護':'护','傷':'伤','險':'险','壞':'坏','壽':'寿','歲':'岁','齊':'齐'};
const plainText=v=>String(v??'').replace(/<\/?(?:color|size|b|i|u|s|sup|sub|font|material|align|link|sprite)(?:=[^>]*)?>/gi,'');
const simplify=v=>String(v??'').replace(/[一-鿿]/g,c=>T2S[c]||c);
const CONDITION_TYPES={0:'概率',1:'年龄限制',2:'年月限制',3:'事件限制',4:'属性限制',5:'技能/成就/专长',6:'性格/人格/价值观',7:'社交',8:'状态与压力',10:'学习',11:'恋爱相关',12:'行动',13:'阅读',15:'目标',22:'同学机制',23:'空间',31:'舌战',34:'游戏',35:'创作',36:'动画（弃用）',38:'手工',42:'篮球',52:'恋爱',60:'物品限制',90:'庆典',100:'其他属性',101:'UI与引导',111:'事件值限制',200:'结局/全局',333:'概率判断',999:'特殊'};
const EFFECT_TYPES={1:'改变属性',2:'价值观与人格',3:'改变技能',4:'学习',5:'改变性格',6:'改变技能',7:'改变状态',8:'人生观',10:'压力相关',20:'社交',21:'社交活动',22:'NPC相关',23:'空间',30:'学习相关',31:'话术相关',32:'创作相关',33:'阅读',34:'游戏相关',36:'动画相关',38:'手工',40:'改变行动',41:'创作',42:'篮球',50:'改变事件',52:'恋爱',60:'改变物品',61:'商店相关',70:'改变目标、抱负',80:'金钱购物',90:'庆典',100:'常用',101:'UI',160:'需求',998:'NPC改变',999:'特殊效果'};
const tidyName=v=>simplify(v).replace(/,/g,'、').replace(/\s+/g,' ').trim();
function typeName(table,id,refs){const row=refs?.[table]?.[id];const raw=row&&(row.name||row.title);return raw?tidyName(plainText(raw)):(table==='ConditionTypeCfg'?CONDITION_TYPES:EFFECT_TYPES)[id]||null;}
// Condition categories shown to modders: the official ConditionTypeCfg types folded into a few plain groups
// (the trailing official types are opaque names, so they all land in 其他).
const CONDITION_GROUPS=[['时间与概率',[0,1,2,333]],['剧情与事件',[3,111,200]],['属性与状态',[4,6,8,100]],['技能与学习',[5,10,13,31,34,35,36,38,42]],['社交与恋爱',[7,11,22,23,52]],['行动与目标',[12,15]],['物品',[60]],['其他',[90,101,999]]];
const CONDITION_GROUP_OF=Object.fromEntries(CONDITION_GROUPS.flatMap(([label,ids])=>ids.map(id=>[id,label])));
function conditionCategory(row){const id=Number(row?.[0]);return CONDITION_GROUP_OF[id]||'其他';}
// Any category left with a single entry is folded into 其他 so no tab holds just one item.
function foldSingles(items,getCategory){const counts=new Map();for(const item of items){const c=getCategory(item);counts.set(c,(counts.get(c)||0)+1);}return item=>{const c=getCategory(item);return counts.get(c)>1?c:'其他';};}
function effectCategory(row,refs){const id=Number(row?.[0]);return typeName('EffectTypeCfg',id,refs)||(Number.isFinite(id)?'类型 '+id:'其他');}
function categoryOrder(table,names,refs){if(table==='ConditionTypeCfg'){const rank=new Map(CONDITION_GROUPS.map(([label],i)=>[label,i]));return [...new Set(names)].sort((a,b)=>(rank.get(a)??1e9)-(rank.get(b)??1e9)||a.localeCompare(b,'zh'));}const known=new Map();const source=refs?.[table]&&Object.keys(refs[table]).length?Object.fromEntries(Object.values(refs[table]).map(r=>[r.id,r.name||r.title])):(table==='ConditionTypeCfg'?CONDITION_TYPES:EFFECT_TYPES);for(const [id,raw]of Object.entries(source)){const label=tidyName(plainText(raw));if(!known.has(label))known.set(label,Number(id));}return [...new Set(names)].sort((a,b)=>(a==='其他')-(b==='其他')||(known.get(a)??1e9)-(known.get(b)??1e9)||a.localeCompare(b,'zh'));}
// OtherRelationCfg (关系判断用的关系组) is not part of the extracted catalogue in older caches; the game's rows are
// stable, so a bundled copy fills the reference table when the game's own file is unavailable.
const OTHER_RELATIONS=[{"id":-12,"name":"异性","groups":[-1]},{"id":-11,"name":"同性","groups":[-1]},{"id":-3,"name":"认识的人","groups":[1,2,3,4,5,6]},{"id":-2,"name":"不认识的人","groups":[0]},{"id":-1,"name":"所有人","groups":[-1]},{"id":0,"name":"无","groups":[0]},{"id":1,"name":"熟人","groups":[1]},{"id":2,"name":"朋友","groups":[2]},{"id":3,"name":"好友","groups":[3]},{"id":4,"name":"密友","groups":[4]},{"id":5,"name":"挚友","groups":[5]},{"id":6,"name":"至交","groups":[6]},{"id":10,"name":"朋友/好友/密友/挚友/至交","groups":[2,3,4,5,6]},{"id":11,"name":"好友/密友/挚友/至交","groups":[3,4,5,6]},{"id":12,"name":"密友/挚友/至交","groups":[4,5,6]},{"id":13,"name":"挚友/至交","groups":[5,6]},{"id":21,"name":"好感最高的人","groups":[1,2,3,4,5,6]},{"id":22,"name":"好感最低的人","groups":[1,2,3,4,5,6]},{"id":23,"name":"好感最高的异性","groups":[6,5,4,3,2,1]},{"id":520,"name":"恋人","groups":[]}];
function otherRelations(){return Object.fromEntries(OTHER_RELATIONS.map(r=>[String(r.id),{...r}]));}
if(typeof window!=='undefined')window.StudentAgeCommandTypes={simplify,conditionCategory,effectCategory,categoryOrder,typeName,otherRelations,foldSingles};
function family(row,t={}){
 const a=Number(row?.[0]),b=Number(row?.[1]);
 if(t.premiseId&&Number(row?.[0])===3)return {key:'premise-talk:'+Number(row[2]),title:(t.label||'前提').replace(/^前提[已未]达成：|^[已未]达成：/,''),category:conditionCategory(row)};
 if(t.premiseId||(Number(row?.[0])===111&&t.match?.[2]!==undefined&&t.match?.[3]!==undefined&&/^(?:前提)?[已未]达成/.test(t.label||'')))return {key:'premise:'+Number(row[2])+':'+Number(row[3]),title:(t.label||'前提').replace(/^前提[已未]达成：|^[已未]达成：/,''),category:conditionCategory(row)};
 let key,title,category='其他';
 if(a===4&&([1,2,3].includes(b)||(b>=9001&&b<=9006))){key='attribute';title='属性数值';category='数值';}
 else if(a===7&&b===0){key='relationship';title='人物关系';category='前提';}
 else if(a===7&&([1,-1].includes(b)||(b>=9001&&b<=9006))){key='favor';title='人物好感度';category='数值';}
 else if(a===1&&[1,2,3].includes(b)){key='age';title='年龄';category='数值';}
 else if(a===10&&b===50){key='exam-rank';title='考试排名';category='数值';}
 else if(a===1&&b===12){key='grade';title='年级';category='数值';}
 else if(a===8&&b===5){key='mood';title='心情等级';category='数值';}
 else if(a===111){key='record';title='剧情记录值';category='前提';}
 else if(a===3){key='event:'+Math.abs(b);title=({1:'剧情触发',2:'选项选择',3:'对话到达',4:'价值观激活',5:'短信发送',30:'本回合对话'})[Math.abs(b)];category='剧情';}
 else if(a===8&&Math.abs(b)===1){key='state';title='人物状态';category='前提';}
 else if(a===60&&[1,2].includes(Math.abs(b))){key='item:'+Math.abs(b);title=Math.abs(b)===1?'持有物品':'持有书籍';}
 else if(a===2){key=({10:'year',20:'year',3:'season-year',30:'season-year',11:'month-year',110:'month-year',4:'season','-4':'season',0:'round',100:'round','-100':'round'})[b];title=({year:'年份','season-year':'年份与季节','month-year':'年月',season:'季节',round:'游戏回合'})[key];if(key==='round')category='数值';}
 else if(a===999&&[999,1000].includes(b)){key='constant';title='固定判断';}
 return {key:key||t.family||'native:'+a+':'+Math.abs(b)+':'+row?.length,title:title||t.family||t.label||'自定义条件',category:conditionCategory(row)};
}
function numeric(row){
 const [a,b]=row.map(Number),f=family(row);let ops,valueIndex,op,make,upperIndex;
 if(f.key==='attribute'||f.key==='favor'){
  ops=['=','>','≥','<','≤','≠'];if(a===4)ops.push('范围');valueIndex=3;upperIndex=b===3?4:null;
  op=({9001:'≥',9002:'<',9003:'>',9004:'≤',9005:'=',9006:'≠',1:'≥',2:'<','-1':'<',3:'范围'})[b];
  make=(symbol,value,upper)=>symbol==='范围'?[a,3,row[2],value,upper??value]:[a,({'=':9005,'>':9003,'≥':9001,'<':9002,'≤':9004,'≠':9006})[symbol],row[2],value];
 }else if(f.key==='age'){
  ops=['=','≥','≤','范围'];valueIndex=2;upperIndex=b===3?3:null;op=b===1?'≥':b===2?'≤':row[2]===row[3]?'=':'范围';
  make=(symbol,value,upper)=>symbol==='='?[1,3,value,value]:symbol==='范围'?[1,3,value,upper??value]:[1,symbol==='≥'?1:2,value];
 }else if(f.key==='grade'){
  ops=['=','≥','≤','范围'];valueIndex=3;upperIndex=row[2]===101?4:null;op=({0:'=',1:'≥','-1':'≤',101:'范围'})[row[2]];
  make=(symbol,value,upper)=>symbol==='范围'?[1,12,101,value,upper??value]:[1,12,({'=':0,'≥':1,'≤':-1})[symbol],value];
 }else if(f.key==='exam-rank'){ops=['≤'];valueIndex=2;op='≤';make=(symbol,value)=>[10,50,value];
 }else if(f.key==='mood'){ops=['=','≥','≤'];valueIndex=3;op=({0:'=',1:'≤',2:'≥'})[row[2]];make=(symbol,value)=>[8,5,({'=':0,'≥':2,'≤':1})[symbol],value];}
 else if(f.key==='record'&&[1,2,-1].includes(b)){ops=['=','≥','≤'];valueIndex=4;op=({1:'≥',2:'=','-1':'≤'})[b];make=(symbol,value)=>[111,({'=':2,'≥':1,'≤':-1})[symbol],row[2],row[3],value];}
 else if(f.key==='year'){ops=['=','范围'];valueIndex=2;upperIndex=b===20?3:null;op=b===10?'=':'范围';make=(symbol,value,upper)=>symbol==='='?[2,10,value]:[2,20,value,upper??value];}
 else if(f.key==='round'){ops=['=','≥','<'];valueIndex=2;op=({0:'=',100:'≥','-100':'<'})[b];make=(symbol,value)=>[2,({'=':0,'≥':100,'<':-100})[symbol],value];}
 return op?{ops,valueIndex,upperIndex,op,make}:null;
}
function categoryOf(rows,templates=[],refs){return rows.length?conditionCategory(rows[0],refs):'其他';}
function evaluateExact(row,context={}){if(!Array.isArray(row))return null;if(Number(row[0])===999&&Number(row[1])===1000)return true;if(Number(row[0])===999&&Number(row[1])===999)return false;if(![4,7].includes(Number(row[0]))||Number(row[1])<9001||Number(row[1])>9006)return null;const input=(Number(row[0])===4?context.attributes:context.affection)?.[row[2]];if(input===undefined)return null;const a=Math.fround(Number(input)),b=Math.fround(Number(row[3]));if(!Number.isFinite(a)||!Number.isFinite(b))return null;return ({9001:()=>a>=b,9002:()=>a<b,9003:()=>a>b,9004:()=>a<=b,9005:()=>a===b,9006:()=>a!==b})[Number(row[1])]();}
return {match,summary,mount,evaluateExact,family,numeric,categoryOf,parseCommand,parameterText,parameterHTML,readParameterInput,rawCommandHTML,readCommandInput};
});
