"""Native entry bindings for event-less dialogue folders. Writes join Store.save's transaction."""
import copy
import json
from pathlib import Path

META = 'externalDialogueFolders'
SCHEMAS = json.loads(Path(__file__).with_name('external-usage-schema.json').read_text(encoding='utf-8'))
DEFINITIONS = []
def define(kind, label, table, field, shape='pair', fields=(), **extra):
    DEFINITIONS.append(dict(kind=kind, label=label, table=table, field=field, shape=shape, fields=list(fields), **extra))

define('gift', '送礼对话', 'GiftEvtCfg', 'talkId', 'gift', ('cond','redpoint'), create=True,
       help='选择收礼人和具体礼物；默认无额外条件，赠送该礼物时播放。赠送方式可选择实际交付或仅播放对话。')
define('interact', '闲聊互动结束', 'InteractCfg', 'talkId', 'scalar', ('npc','name','text','map','cond','effect'), create=True,
       help='角色的闲聊进度条完成时播放；条件为空时不限制，地点为空时不限地点。')
define('item', '使用物品', 'ItemCfg', 'talkId', 'scalar', (), help='在已有物品的原版使用流程中播放，不改变物品类型及使用效果。')
for kind,label,field in [('goal-finish','目标完成','finishTalk'),('goal-fail','目标失败','failTalk')]:
    define(kind,label,'IntentCfg',field,fields=('name','npc','condition','demand','reward','fail','round'),help='在所选目标判定完成或失败时播放，不改变目标本身的达成规则。')
for kind,label,field in [('mini-start','小游戏开场','startTalk'),('mini-win','小游戏胜利','winTalk'),('mini-lose','小游戏失败','loseTalk')]:
    define(kind,label,'MinigameActionCfg',field,'mini',(),help='沿用人物界面绑定的小游戏，选择第 1～5 关。同一小游戏被多个人物共用时，这些人物也共用关卡对话。')
define('cg','CG 回忆开场','CGCfg','startTalks','first',(),help='从回忆画廊打开所选 CG 时播放；不改变 CG 图片与剧情中的插图。')
define('love-draw','恋爱画作获得','LoveDrawCfg','talkId',fields=('cond',),help='沿用已有画作和解锁条件，获得画作并展示时播放。')
for gender,field in [('男主','talks'),('女主','talks2')]:
    for stage,label in enumerate(('开场','成功','失败')):
        define('negotiation-'+field+'-'+str(stage),'交涉 · '+gender+label,'NegotiationCfg',field,'phase',(),slot=stage,
               help='对应所选交涉的开场、成功或失败。女主列表为空时原版沿用男主列表，设置后会保留其他阶段的回退值。')
define('input-match','输入答案 · 匹配','TalkInputMinigameCfg','jumps','answer',(),help='精确匹配所填答案时播放；保留同一题的其他答案及默认分支。')
define('input-default','输入答案 · 未匹配','TalkInputMinigameCfg','talkId',fields=(),help='输入内容不匹配该题任何预设答案时播放。')
for table,prefix,fields in [('TalkCfg','对话',('check','effect','effect2')),('OptionCfg','选项',('check','effect','effect2'))]:
    for kind,label,field in [('success','继续／成功','nextTalk' if table=='TalkCfg' else 'talkId'),('failure','另一分支／失败','nextTalk2' if table=='TalkCfg' else 'talkId2')]:
        define(table+'-'+kind,prefix+' · '+label,table,field,fields=fields,help='绑定已有对话或选项的原版跳转。含小游戏时由其成功／失败结果选择分支；不会自动创建小游戏。')
for kind,label,table in [('love-greeting','恋爱问候（原版预留）','LoveGreetingCfg'),('npc-activity','人物活动（原版预留）','NpcActivityCfg')]:
    define(kind,label,table,'talkId',disabled=True,help='当前游戏只找到配置声明，未找到启用的播放入口；暂不提供会造成“已绑定却不触发”的配置。')
KINDS = {d['kind']:d for d in DEFINITIONS}
EXTRA_TABLES = ('LoveDrawCfg','LoveGreetingCfg','NpcActivityCfg','TalkInputMinigameCfg')


def rows_for(store, project, name):
    native = {}
    if name in EXTRA_TABLES:
        from character_rules import native_rules
        native = native_rules(store.game).get(name,{})
    return {**native, **store.table(project.id,name)['rows']}


def catalog(store, project_id, api):
    with store.lock, store.catalog_scope():
        project = store.project(project_id)
        commands = store.workshop_info(project.id)['commands']
        names = {d['table'] for d in DEFINITIONS if not d.get('disabled')}
        names.update(('PersonCfg','PersonGrowCfg','ItemCfg','BookCfg','MapCfg','BgCfg','MinigameCfg'))
        for schema in SCHEMAS.values():
            names.update(f['range']['table'] for f in schema['fields'] if f.get('range',{}).get('table') and ' / ' not in f['range']['table'])
        for templates in commands.values():
            if isinstance(templates,list):
                names.update(p['range']['table'] for t in templates for p in t.get('parameters',[]) if p.get('range',{}).get('table') and ' / ' not in p['range']['table'])
        refs = {n: rows_for(store,project,n) for n in sorted(names)}
        return dict(definitions=DEFINITIONS, schemas=SCHEMAS, refs=refs, commands=commands, revision=store.revision(project))


def read_path(row, path):
    value=row
    for part in path:
        if isinstance(part,int):
            if not isinstance(value,list) or part>=len(value):return None
            value=value[part]
        else:
            if not isinstance(value,dict):return None
            value=value.get(part)
    return copy.deepcopy(value)


def write_path(row,path,value):
    node=row
    for index,part in enumerate(path):
        if isinstance(part,int):
            while len(node)<=part:node.append([] if index+1<len(path) else 0)
        if index==len(path)-1:
            node[part]=copy.deepcopy(value);return
        if isinstance(node,dict) and (part not in node or node[part] is None):node[part]=[] if isinstance(path[index+1],int) else {}
        node=node[part]


def _int(value, label, api, minimum=1, maximum=2147483647):
    if type(value)!=int or not minimum<=value<=maximum:raise api.ApiError(label+'无效。')
    return value


def apply(store,project,groups,previous,all_maps,touched,api):
    """Resolve real CFG targets, merge only edited fields, reject collisions, then write atomically."""
    groups=copy.deepcopy(groups)
    old={}
    for fid,folder in previous.items():
        for u in folder.get('uses',[]):
            if isinstance(u,dict) and u.get('id'):old[(fid,u['id'])]=u
    refs={}; changed={}; claims=[]; result=[]; seen=set()
    def table(name):
        if name not in refs:refs[name]={**rows_for(store,project,name),**copy.deepcopy(all_maps.get(name+'.json',{}))}
        return refs[name]
    def claim(name,rid,path,identity):
        for t,i,p,who in claims:
            if t==name and i==rid and (p[:len(path)]==path or path[:len(p)]==p) and who!=identity:
                raise api.ApiError('多个用途写入同一个游戏入口，请保留一个绑定或分别选择男主、女主分支。')
        claims.append((name,rid,path,identity))
    desired={(fid,u.get('id')) for fid,f in groups.items() for u in f.get('uses',[]) if isinstance(u,dict)}
    # Restore displaced entry values before installing the complete desired set.
    # Compare with the current native value so external changes are never silently undone.
    for identity,u in old.items():
        d=KINDS.get(u.get('kind'));target=u.get('_target')
        if not d or not target:continue
        name=d['table'];rid=str(target['recordId']);row=table(name).get(rid)
        if row is None:raise api.ApiError('已绑定的配置被移除，请重新载入并处理用途。',409,'conflict')
        actual=read_path(row,target['path'])
        if actual!=target['written']:
            if identity not in desired:continue
            raise api.ApiError('用途对应的游戏入口已被其他编辑修改。请移除此用途并保存，再重新绑定；外部修改会被保留。',409,'conflict')
        write_path(row,target['path'],target['previous'])
        changed[(name,rid)]=row
    for fid,folder in groups.items():
        uses=folder.get('uses',[])
        if not isinstance(uses,list) or len(uses)>100:raise api.ApiError('每个对话夹最多配置 100 个用途。')
        for u in uses:
            if not isinstance(u,dict):raise api.ApiError('对话用途格式无效。')
            uid=u.get('id');identity=(fid,uid)
            if not isinstance(uid,str) or not uid or len(uid)>120 or identity in seen:raise api.ApiError('对话用途编号无效。')
            seen.add(identity);d=KINDS.get(u.get('kind'))
            if not d or d.get('disabled'):raise api.ApiError('该用途尚无可用的原版触发入口。')
            entry=_int(u.get('entryId'),'起始对话',api)
            if entry not in folder['talkIds']:raise api.ApiError('用途的起始对话必须位于当前对话夹；删除此句前请先修改用途。')
            name=d['table'];rows=table(name);shape=d['shape'];rid=u.get('recordId',0)
            params=u.get('params',{})
            if not isinstance(params,dict):raise api.ApiError('用途参数无效。')
            if shape=='mini':
                npc=_int(u.get('npc'),'小游戏人物',api);level=_int(u.get('level'),'小游戏关卡',api,1,5)
                game=table('PersonGrowCfg').get(str(npc),{}).get('minigame',0)
                if not game or str(game) not in table('MinigameCfg'):raise api.ApiError('该人物尚未绑定小游戏，请先到人物界面设置。')
                rid=game*100+level
                if str(rid) not in rows:raise api.ApiError('该人物绑定的小游戏没有第 '+str(level)+' 关，请在已有的 1～5 关中选择。')
            if shape=='gift':
                npc=_int(u.get('npc'),'收礼人',api);item=_int(u.get('item'),'礼物',api)
                if str(npc) not in table('PersonCfg'):raise api.ApiError('收礼人不存在。')
                gift=table('ItemCfg').get(str(item)) or table('BookCfg').get(str(item))
                if not gift:raise api.ApiError('礼物不存在。')
                if gift.get('value',0)<0:raise api.ApiError('该物品在原版中不可赠送，请选择可赠送的礼物。')
                matches=[r for r in rows.values() if r.get('item')==item and npc in (r.get('npc') or [])]
                if len(matches)>1:raise api.ApiError('该人物和礼物已有多条送礼规则，原版会优先匹配其中一条。请先在送礼配置中合并重复入口，再绑定用途。')
                if matches:rid=matches[0]['id']
                else:rid=0  # A changed recipient/item gets its own entry; never edits another recipient.
            if not rid:
                if not d.get('create'):raise api.ApiError('请选择已有的'+d['label']+'配置。')
                rid=store.record_ids.allocate(name,rows)
                row={f['name']:copy.deepcopy(f.get('default')) for f in SCHEMAS[name]['fields']}
                row['id']=rid;rows[str(rid)]=row
            rid=_int(rid,'用途配置编号',api);row=rows.get(str(rid))
            if row is None:raise api.ApiError('用途配置不存在，请重新选择。')
            prior=old.get(identity,{});base=u.get('baseParams',{});prior_params=prior.get('params',{})
            if not isinstance(base,dict):raise api.ApiError('用途参数基线无效。')
            allowed={f['name']:f for f in SCHEMAS[name]['fields'] if f['name'] in d['fields']}
            for key,value in params.items():
                if key not in allowed:raise api.ApiError('不支持的用途参数：'+key)
                f=allowed[key];kind=f.get('type','')
                valid=(isinstance(value,list) if kind.startswith('list') else isinstance(value,str) if kind=='string' else type(value) in (int,float))
                if not valid:raise api.ApiError(f.get('label',key)+'的格式无效。')
                # Unchanged fields are not ownership claims on a shared native row.
                if value==base.get(key) and (not prior or value==prior_params.get(key)):continue
                claim(name,rid,[key],identity)
                row[key]=copy.deepcopy(value)
            path=[d['field']]
            if shape=='gift':
                row.setdefault('npc',[]);slot=row['npc'].index(npc) if npc in row['npc'] else len(row['npc'])
                if slot==len(row['npc']):row['npc'].append(npc)
                row['item']=item;path.append(slot)
                mode=_int(u.get('giftMode',0),'赠送方式',api,0,1)
                claim(name,rid,['type',slot],identity);write_path(row,['type',slot],mode)
            if shape=='answer':
                answer=u.get('answer','')
                if not isinstance(answer,str) or not answer or len(answer)>500:raise api.ApiError('请填写要精确匹配的答案。')
                inputs=row.setdefault('inputs',[])
                slot=inputs.index(answer) if answer in inputs else len(inputs)
                if slot==len(inputs):inputs.append(answer)
                path.append(slot)
            if shape=='phase':
                if d['field']=='talks2' and not row.get('talks2'):row['talks2']=copy.deepcopy(row.get('talks') or [])
                path.append(d['slot'])
            if shape=='first':path.append(0)
            if shape in ('pair','gift','answer'):
                gender=u.get('gender','both')
                if gender not in ('both','male','female'):raise api.ApiError('请选择适用的主角性别。')
                current=read_path(row,path) or []
                if gender=='both':value=[entry]
                else:
                    # Preserve the game's one-entry fallback before writing one gender.
                    pair=list(current)
                    while len(pair)<2:pair.append(pair[0] if pair else 0)
                    write_path(row,path,pair)
                    path.append(0 if gender=='male' else 1);value=entry
            else:value=entry
            claim(name,rid,path,identity)
            previous_value=read_path(row,path)
            target={'recordId':rid,'path':path,'previous':previous_value if previous_value is not None else ([] if isinstance(value,list) else 0),'written':value}
            write_path(row,path,value)
            changed[(name,str(rid))]=row
            u.update(recordId=rid,_target=target)
            result.append((u,row,d))
        if uses:folder['uses']=uses
    for (name,rid),row in changed.items():
        local=all_maps.setdefault(name+'.json',{})
        if local.get(rid)!=row:local[rid]=copy.deepcopy(row);touched.add(name+'.json')
    # Base values come from the final merged record, not an earlier panel snapshot.
    for u,row,d in result:
        u['params']={k:copy.deepcopy(row.get(k)) for k in d['fields'] if k in row}
        u['baseParams']=copy.deepcopy(u['params'])
    return groups
