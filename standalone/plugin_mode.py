"""UP owns social stage registration; CampusMinigames only supplies implementations."""
import copy
import math
import secrets
from pathlib import Path

UP='sa.EC2B.UnofficialPatch'
CAMPUS='studio.studentage.campusuno'
STATE='StudentAgeStudio/plugins.json'
REG='EC2BUnofficialPatch/CustomMinigamecfg.json'
_editing=set()

def editing(project):return str(project.path.resolve()) in _editing

def game_ids(project,api):
    cfg=state(project,api);_,entries=registration(project,api)
    return list(dict.fromkeys(list(catalog(api)['games'])+[str(g['id']) for g in cfg.get('groups',[])]+[str(e['id']) for e in entries if type(e.get('id'))==int]))

def visible(project,api,name,rows):
    if name not in ('MinigameCfg','MinigameActionCfg'):return rows
    ids=set(game_ids(project,api));active=set(references(project,api)[2])
    return {k:v for k,v in rows.items() if str(int(k)//100 if name=='MinigameActionCfg' else k) not in ids-active}

SECTIONS=dict(zip(range(9101,9113),('UNO','Gomoku','Bubble','Box','TwentyFour','Tetris','Landlord','Snake','Pacman','Mario','Contra','Mahjong')))

def runtime_rows(store,project,name):
    return store.preserve_editing_rows(project,name,store.editing_rows(project,name))

def catalog(api):
    return api.read_json(Path(__file__).with_name('plugin-catalog.json'))

def state(project,api):
    value=api.read_json(api.safe_path(project.path,STATE),{'enabled':[],'groups':[]})
    if (not isinstance(value,dict) or not isinstance(value.get('enabled',[]),list)
        or not isinstance(value.get('groups',[]),list)
        or any(not isinstance(g,dict) or type(g.get('id'))!=int for g in value.get('groups',[]))):
        raise api.ApiError('插件配置无法读取，请检查 plugins.json。')
    return value

def registration(project,api):
    value=api.read_json(api.safe_path(project.path,REG),{'minigames':[]})
    entries=value if isinstance(value,list) else value.get('minigames',[]) if isinstance(value,dict) else None
    if not isinstance(entries,list) or any(not isinstance(r,dict) for r in entries):
        raise api.ApiError('UP 小游戏注册表格式无效，请修复后重新打开。')
    return value,entries

def hydrate(cfg,project,store,api,data,entries=None):
    # Editor metadata only records ownership. Runtime cfg is authoritative.
    if entries is None:_,entries=registration(project,api)
    cfg=copy.deepcopy(cfg)
    games=runtime_rows(store,project,'MinigameCfg');stages=runtime_rows(store,project,'MinigameActionCfg')
    for group in cfg.get('groups',[]):
        ident=group['id'];matches=[r for r in entries if r.get('id')==ident]
        if len(matches)!=1:raise api.ApiError('关卡组 '+str(ident)+' 的插件注册缺失或重复，请检查实际配置。')
        reg=matches[0];template=reg.get('targetId');parameters=reg.get('parameters',{})
        if (reg.get('type')!='template' or type(template)!=int or str(template) not in data['games']
            or not isinstance(parameters,dict) or not isinstance(parameters.get('tuning',{}),dict)):
            raise api.ApiError('关卡组 '+str(ident)+' 的外部配置已改变，当前编辑界面无法安全编辑。')
        if str(ident) not in games:raise api.ApiError('关卡组 '+str(ident)+' 的 MinigameCfg 记录缺失。')
        group['template']=template;group['name']=games[str(ident)].get('name',group.get('name',''))
        group['levels']=[v for k,v in sorted(stages.items(),key=lambda kv:int(kv[0])) if int(k)//100==ident]
        group['tuning']=copy.deepcopy(parameters.get('tuning',{}))
    return cfg

def references(project,api):
    cfg=state(project,api);data=catalog(api)
    if not editing(project):return {},{},[]
    if CAMPUS not in cfg.get('enabled',[]):return {},{},[str(e['id']) for e in registration(project,api)[1] if type(e.get('id'))==int] if UP in cfg.get('enabled',[]) else []
    games=data['games'];stages=data['stages']
    ids=game_ids(project,api)
    return games,stages,ids

def load(store,project_id,api):
    with store.lock:
        project=store.project(project_id);revision=store.revision(project);cfg=state(project,api);data=catalog(api)
        # Read the actual cfg on every open, including edits made outside the editor.
        cfg=hydrate(cfg,project,store,api,data)
        builtin=builtin_groups(store,project,api,data);ids=game_ids(project,api)
        if revision!=store.revision(project):raise api.ApiError('读取期间模组发生变化，请重新打开。',409,'conflict')
        return {**cfg,'editing':editing(project),'allPluginGameIds':ids,'builtin':builtin,'catalog':data,'sections':SECTIONS,'revision':revision,'readOnly':project.readonly,
                'plugins':[{'id':UP,'name':'UP 非官方补丁','description':'模组自建关卡、人物绑定与独立进度'},
                           {'id':CAMPUS,'name':'校园小游戏拓展','description':'12 种玩法与各自参数','requires':[UP]}]}

def builtin_groups(store,project,api,data):
    reg,_=registration(project,api)
    overrides=reg.get('overrides',{}) if isinstance(reg,dict) else {}
    if not isinstance(overrides,dict) or any(not isinstance(v,dict) or not isinstance(v.get('tuning',{}),dict) for v in overrides.values()):raise api.ApiError('插件参数覆盖表格式无效。')
    games=runtime_rows(store,project,'MinigameCfg');stages=runtime_rows(store,project,'MinigameActionCfg')
    return [dict(id=int(k),template=int(k),name=games.get(k,v).get('name',v['name']),
        levels=[copy.deepcopy(stages.get(i,row)) for i,row in data['stages'].items() if int(i)//100==int(k)],
        tuning=copy.deepcopy(overrides.get(k,{}).get('tuning',{}))) for k,v in data['games'].items()]

def save_builtin(store,project,payload,api):
    data=catalog(api);reg,_=registration(project,api);old=state(project,api)
    if CAMPUS not in old.get('enabled',[]):raise api.ApiError('请先启用校园小游戏前置。')
    if isinstance(reg,list):reg={'minigames':reg}
    value=payload['builtin'];ident=value.get('id') if isinstance(value,dict) else None
    if type(ident)!=int or str(ident) not in data['games']:raise api.ApiError('插件小游戏编号无效。')
    current=next(g for g in builtin_groups(store,project,api,data) if g['id']==ident)
    tuning=value.get('tuning',{});rules={r['section']+'.'+r['key']:r for r in data['settings'] if r['section']==SECTIONS[ident]}
    if not isinstance(tuning,dict):raise api.ApiError('玩法参数格式无效。')
    for k,v in tuning.items():
        r=rules.get(k)
        if not r or type(v) not in (float,int) or not math.isfinite(v) or not r['min']<=v<=r['max'] or r['integer'] and v!=int(v):raise api.ApiError('玩法参数超出范围：'+k)
    levels=value.get('levels',[])
    if not isinstance(levels,list) or len(levels)!=len(current['levels']):raise api.ApiError('原有关卡数量不能改变，请创建模组关卡。')
    stages=runtime_rows(store,project,'MinigameActionCfg');changed=False
    for source,row in zip(current['levels'],levels):
        if not isinstance(row,dict) or row.get('id')!=source['id']:raise api.ApiError('原有关卡编号不能改变。')
        nextrow=copy.deepcopy(source)
        for k in ('needRelation','cost','startTalk','winTalk','loseTalk'):
            v=row.get(k,source.get(k,0))
            if type(v) not in (int,float) or not math.isfinite(v) or v<0 or (k!='cost' and (type(v)!=int or v>2147483647)):raise api.ApiError('关卡数值无效：'+k)
            if k.endswith('Talk') and v and str(v) not in runtime_rows(store,project,'TalkCfg') and str(v) not in store.catalog_rows('TalkCfg'):raise api.ApiError('对话编号不存在：'+str(v))
            nextrow[k]=v
        if nextrow!=source:stages[str(source['id'])]=nextrow;changed=True
    overrides=copy.deepcopy(reg.get('overrides',{}))
    overrides[str(ident)]={**overrides.get(str(ident),{}),'tuning':copy.deepcopy(tuning)}
    changes={REG:api.json_bytes({**reg,'overrides':overrides})}
    if changed:changes['Cfgs/zh-cn/MinigameActionCfg.json']=api.json_bytes(stages)
    store.commit(project,changes,payload['revision'])
    return {**load(store,project.id,api),'ok':True}

def save(store,payload,api):
    with store.lock,store.catalog_scope():
        if 'editing' in payload:
            project=store.project(payload.get('projectId'))
            if type(payload['editing'])!=bool:raise api.ApiError('插件编辑模式设置无效。')
            if payload['editing'] and not state(project,api).get('enabled'):raise api.ApiError('请先选择前置插件。')
            result=load(store,project.id,api)
            key=str(project.path.resolve())
            if payload['editing']:_editing.add(key)
            else:_editing.discard(key)
            return {**result,'editing':payload['editing'],'ok':True}
        project=store.project(payload.get('projectId'),writable=True)
        if payload.get('revision')!=store.revision(project):raise api.ApiError('模组已被其他窗口修改，请重新打开。',409,'conflict')
        if 'builtin' in payload:return save_builtin(store,project,payload,api)
        data=catalog(api);reg,entries=registration(project,api)
        old=state(project,api);current=hydrate(old,project,store,api,data,entries)
        enabled=payload.get('enabled',old.get('enabled',[]));groups=payload.get('groups',current.get('groups',[]))
        if not isinstance(enabled,list) or any(p not in (UP,CAMPUS) for p in enabled):raise api.ApiError('前置插件无效。')
        if CAMPUS in enabled and UP not in enabled:raise api.ApiError('校园小游戏需要同时启用 UP 前置。')
        if groups and CAMPUS not in enabled:raise api.ApiError('已有插件关卡，请保留校园小游戏和 UP 前置。')
        if not isinstance(groups,list) or len(groups)>1000:raise api.ApiError('关卡组格式无效。')
        oldids={g['id'] for g in old.get('groups',[])};oldgroups={g['id']:g for g in current.get('groups',[])};seen=set();accepted=[]
        native={n:runtime_rows(store,project,n) for n in ('MinigameCfg','MinigameActionCfg')}
        unknown=[r for r in entries if r.get('id') not in oldids]
        for group in groups:
            if not isinstance(group,dict):raise api.ApiError('关卡组格式无效。')
            ident=group.get('id');template=group.get('template');name=group.get('name','')
            if type(ident)!=int or not 10000<=ident<=20000000 or ident in seen or type(template)!=int or str(template) not in data['games'] or not isinstance(name,str) or not name.strip():raise api.ApiError('关卡组编号、玩法或名称无效。')
            name=name.strip()
            if ident in oldgroups and template!=oldgroups[ident]['template']:raise api.ApiError('已有关卡组的玩法不能直接替换，请新建关卡组后重新绑定人物。')
            if ident not in oldids and (str(ident) in native['MinigameCfg'] or str(ident) in store.catalog_rows('MinigameCfg') or any(r.get('id')==ident for r in unknown)):raise api.ApiError('关卡组编号已被使用。')
            seen.add(ident);levels=group.get('levels',[])
            maxlevel=min(5,sum(int(k)//100==template for k in data['stages']))
            if not isinstance(levels,list) or not 1<=len(levels)<=maxlevel:raise api.ApiError('此玩法关卡数量无效。')
            checked=[]
            for i,row in enumerate(levels,1):
                rid=ident*100+i
                if not isinstance(row,dict) or row.get('id',rid)!=rid:raise api.ApiError('关卡编号必须按顺序连续，不能重新编号已有的关卡。')
                if ident not in oldids and str(rid) in native['MinigameActionCfg']:raise api.ApiError('关卡编号已被使用。')
                basis=copy.deepcopy(native['MinigameActionCfg'].get(str(rid),data['stages'][str(template*100+i)]))
                for key in ('needRelation','cost','startTalk','winTalk','loseTalk'):
                    value=row.get(key,basis.get(key,0))
                    if type(value) not in (int,float) or not math.isfinite(value) or value<0 or (key!='cost' and (type(value)!=int or value>2147483647)):raise api.ApiError('关卡数值无效：'+key)
                    if key.endswith('Talk') and value and str(value) not in runtime_rows(store,project,'TalkCfg') and str(value) not in store.catalog_rows('TalkCfg'):raise api.ApiError('对话编号不存在：'+str(value))
                    basis[key]=value
                basis['id']=rid
                # Stage mode/parms/effect retain the real template, never synthetic visual fields.
                checked.append(basis)
            tuning=group.get('tuning',{});settings={s['section']+'.'+s['key']:s for s in data['settings'] if s['section']==SECTIONS[template]}
            if not isinstance(tuning,dict):raise api.ApiError('玩法参数格式无效。')
            for key,value in tuning.items():
                rule=settings.get(key)
                if not rule or type(value) not in (int,float) or not math.isfinite(value) or not rule['min']<=value<=rule['max'] or rule['integer'] and value!=int(value):raise api.ApiError('玩法参数超出允许范围：'+key)
            accepted.append({'id':ident,'name':name,'template':template,'levels':checked,'tuning':copy.deepcopy(tuning)})
        removed=oldids-seen
        growth={**store.catalog_rows('PersonGrowCfg'),**runtime_rows(store,project,'PersonGrowCfg')}
        if any(r.get('minigame') in removed for r in growth.values()):raise api.ApiError('关卡组仍绑定人物，请先在人​​物界面解除绑定。')
        changes={};regs=list(unknown)
        for g in accepted:
            ident=g['id'];key=str(ident)
            native['MinigameCfg'][key]={**data['games'][str(g['template'])],**native['MinigameCfg'].get(key,{}),'id':ident,'name':g['name']}
            native['MinigameActionCfg']={k:v for k,v in native['MinigameActionCfg'].items() if int(k)//100!=ident}
            native['MinigameActionCfg'].update({str(v['id']):v for v in g['levels']})
            previous=next((r for r in entries if r.get('id')==ident),{})
            regs.append({**previous,'id':ident,'type':'template','targetId':g['template'],'parameters':{**previous.get('parameters',{}),'tuning':g['tuning']}})
        for ident in removed:native['MinigameCfg'].pop(str(ident),None)
        native['MinigameActionCfg']={k:v for k,v in native['MinigameActionCfg'].items() if int(k)//100 not in removed}
        if oldids or accepted:
            for name,rows in native.items():changes['Cfgs/zh-cn/'+name+'.json']=api.json_bytes(rows)
            changes[REG]=api.json_bytes(regs if isinstance(reg,list) else {**reg,'minigames':regs})
        changes[STATE]=api.json_bytes({**old,'enabled':list(dict.fromkeys(enabled)),'groups':[{'id':g['id'],'name':g['name'],'template':g['template']} for g in accepted]})
        store.commit(project,changes,payload['revision'])
        return {**load(store,project.id,api),'ok':True}
