'use strict';
// Display labels only. Python reads the same marked JSON; neither helper edits configuration rows.
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.StudentAgeAssetNames=api;})(typeof window==='object'?window:globalThis,()=>{
const LABELS = /* ASSET_LABELS_START */ {
  "background": {
    "img_ktv":"卡拉OK包厢", "img_woshi":"卧室", "img_future":"未来场景", "img_memory":"回忆场景",
    "img_chengxuyuan":"程序员工作场景", "img_gongdi":"建筑工地", "img_hospital":"医院", "img_room":"房间",
    "img_waimai":"外卖工作场景", "img_lab":"实验室", "img_futureclass":"未来教室", "img_controlroom":"控制室",
    "img_spaceship":"飞船内部", "img_dnd_town":"冒险小镇", "img_jiuguan":"酒馆", "img_huiketing":"会客厅",
    "img_map_2":"地图（二）", "img_bowuguan":"博物馆", "img_quanjiafu2":"全家福（二）", "img_shuju":"数据画面",
    "img_xxzoulang":"小学教学楼走廊", "img_xxjiaoshi":"小学教室", "img_jiaoshi":"教室", "classroom":"教室", "corridor":"走廊", "bedroom":"卧室", "hospital":"医院"
  },
  "cg": {
    "shudianqingshu":"书店情书", "kaixuechuyu":"开学初遇", "fengkuangdexiangji":"疯狂的相机", "quanjiafu":"全家福",
    "youxikaichang":"游戏开场", "youxikaichang_b":"游戏开场（二）", "toukanlimuqing":"偷看场景", "zhuangjianqinglvqinwen":"撞见情侣亲吻",
    "jiawawa":"夹娃娃", "weimao":"喂猫", "xinyuanhe2":"心愿盒（二）", "xueshileishuaidao":"薛诗蕾摔倒",
    "chengliangdajia":"程良打架", "linjiayupaobu":"林嘉宇跑步", "chengliangwucan":"程良的午餐", "guigushi":"鬼故事",
    "xiaojunbl":"谭梓君插画", "xiaoshengchu":"小升初", "xueshileipaidui":"薛诗蕾排队", "jiegexiaohuangshu":"梁超杰看书",
    "chengliangxihuan":"程良的心意", "xiaoqingyamao":"肖清雅与猫", "linjiayuduguo":"林嘉宇插画（990026）", "linjiayuheshui":"林嘉宇喝水",
    "chenglianghejiu":"程良喝酒", "honggehui":"红歌会", "mengshipin":"孟怀安插画（990030）", "chunshafa":"罗晓纯坐沙发",
    "chunzhaili":"罗晓纯插画（990032）", "chunweikele":"罗晓纯喂可乐", "jiegesongli":"梁超杰送礼", "mengtiaowu":"孟怀安跳舞",
    "linbinggan":"林嘉宇与饼干", "junhuamao":"谭梓君与猫", "xiejiaolian":"谢辰晖与教练", "xiezhuazaolian":"谢辰晖插画（999002）",
    "chenchifan":"陈心慈吃饭", "chenbaba":"陈心慈与爸爸"
  },
  "audio": {
    "door/open":"开门声", "door_open":"开门声", "open_door":"开门声", "opendoor":"开门声",
    "door/close":"关门声", "door_close":"关门声", "close_door":"关门声", "closedoor":"关门声",
    "door/knock":"敲门声", "door_knock":"敲门声", "knock_door":"敲门声", "knockdoor":"敲门声",
    "footsteps":"脚步声", "footstep":"脚步声", "rain":"雨声", "thunder":"雷声", "wind":"风声",
    "bell":"铃声", "click":"点击声", "typing":"打字声", "telephone_ring":"电话铃声"
  },
  "speakers": {"jiege":"梁超杰", "chun":"罗晓纯", "xue":"薛诗蕾", "chen":"陈心慈", "jun":"谭梓君", "qingya":"肖清雅", "meng":"孟怀安", "lin":"林嘉宇", "chengliang":"程良", "xie":"谢辰晖"},
  "voiceActions": {"greeting":"问候", "talk":"对话语音", "bye":"告别"}
} /* ASSET_LABELS_END */;
const text=value=>typeof value==='string'?value.trim():'';
const han=value=>/[\u3400-\u9fff]/.test(value);
function normalize(value){return text(value).replace(/\\/g,'/').replace(/[?#].*$/,'').replace(/^\.?\//,'').replace(/^assets\/(?:resources\/)?/i,'').replace(/\.(?:png|jpe?g|webp|gif|bmp|wav|ogg|mp3|flac|aac|prefab)$/i,'').toLowerCase();}
function paths(row){const out=[];for(const field of ['url','urls','assetPath','icon','icon_xx','url2']){const value=row?.[field];for(const item of Array.isArray(value)?value:[value]){const path=normalize(item);if(path&&!out.includes(path))out.push(path);}}return out;}
function explicit(row){const name=text(row?.name)||text(row?.title);if(!name)return '';const normalized=normalize(name),resources=paths(row);if(/[\\/]/.test(name)&&resources.includes(normalized))return '';if(resources.some(path=>path.startsWith('mods/')))return name;return resources.some(path=>normalized===path||normalized===path.split('/').pop())&&!han(name)?'':name;}
function name(row,kind,records){
  row=row&&typeof row==='object'?row:{};const given=explicit(row);if(given)return given;
  const resources=paths(row),values=Array.isArray(records)?records:Object.values(records||{});
  // Reuse actual game names before translating technical filenames. This also
  // resolves older low-ID background rows through their named high-ID peers.
  for(const other of values){const label=explicit(other);if(han(label)&&paths(other).some(path=>resources.includes(path)))return label;}
  const labels=LABELS[kind]||{};
  for(const resource of resources){const stem=resource.split('/').pop();if(labels[resource]||labels[stem])return labels[resource]||labels[stem];
    if(kind==='audio'){
      const voice=resource.match(/(?:^|\/)npc\/(xx_)?([a-z]+)_(greeting|talk|bye)(?:_(\d+))?$/);
      if(voice&&LABELS.speakers[voice[2]])return (voice[1]?'小学 · ':'')+LABELS.speakers[voice[2]]+' · '+LABELS.voiceActions[voice[3]]+(voice[4]?' '+Number(voice[4]):'');
      const numbered=stem.match(/^(.*?)[_-]?(\d+)$/);if(numbered&&labels[numbered[1]])return labels[numbered[1]]+' '+Number(numbered[2]);
    }
    if(han(stem))return stem;
  }
  const type=kind==='audio'?(Number(row.type)===1?'背景音乐':'音效'):({background:'场景',cg:'插画',portrait:'人物立绘'}[kind]||'素材');
  return type+(row.id!==undefined&&row.id!==null&&String(row.id)!==''?' '+String(row.id):'（未命名）');
}
return {name};
});
