"""Event-less TalkCfg editing and editor-only folders, without synthetic events."""
import copy
META='externalDialogueFolders'

def folders(value,talks,api):
    if not isinstance(value,dict) or len(value)>2000:raise api.ApiError('对话夹格式无效。')
    result={};used=set()
    for key,row in value.items():
        if not isinstance(key,str) or not key or len(key)>80 or not isinstance(row,dict):raise api.ApiError('对话夹格式无效。')
        name=row.get('name');ids=row.get('talkIds',[])
        if not isinstance(name,str) or not name.strip() or len(name)>120 or not isinstance(ids,list):raise api.ApiError('请填写对话夹名称。')
        kept=[]
        for ident in ids:
            if type(ident)!=int or str(ident) not in talks:raise api.ApiError('对话夹包含不存在或事件所属的对话。')
            if ident in used:raise api.ApiError('一条对话只能归属一个对话夹。')
            used.add(ident);kept.append(ident)
        result[key]={**copy.deepcopy(row),'name':name.strip(),'talkIds':kept}
    return result

def load(store,project_id,api):
    with store.lock,store.catalog_scope():
        project=store.project(project_id);doc=store.load(project.id);table=store.table(project.id,'TalkCfg')
        state=api.read_json(api.safe_path(project.path,'StudentAgeStudio/editor-state.json'),{})
        groups=copy.deepcopy(state.get(META,{}));used=set()
        shared={str(i) for f in groups.values() if f.get('uses') for i in f.get('talkIds',[])} | {str(i) for i in state.get('externalDialogueIds',[])}
        talks={k:v for k,v in table['localRows'].items() if not doc.get('talkOwners',{}).get(k) or k in shared}
        for group in groups.values():
            keep=[]
            for ident in group.get('talkIds',[]):
                if str(ident) in talks and ident not in used:keep.append(ident);used.add(ident)
            group['talkIds']=keep
        refs={n:store.table(project.id,n)['rows'] for n in ('PersonCfg','BgCfg','MapCfg','ModFaceCfg','CGCfg','ItemCfg')}
        return {'talks':talks,'folders':groups,'doc':doc,'refs':refs,'revision':store.revision(project)}

def save(store,payload,api):
    with store.lock,store.catalog_scope():
        project=store.project(payload.get('projectId'),writable=True);current=load(store,project.id,api)
        if current['revision']!=payload.get('revision'):raise api.ApiError('对话已经被其他窗口修改，请重新打开。',409,'conflict')
        incoming=api.validate_map(payload.get('talks',{}),'TalkCfg.json')
        if any(current['doc'].get('talkOwners',{}).get(k) and k not in current['talks'] for k in incoming):raise api.ApiError('事件所属对话请在剧情编辑中修改。',409)
        groups=folders(payload.get('folders',{}),incoming,api)
        removed=set(current['talks'])-set(incoming)
        talks={k:v for k,v in current['doc']['talks'].items() if k not in removed};talks.update(incoming)
        result=store.save({'projectId':project.id,'revision':payload['revision'],'talks':talks,'deletedIds':[int(k) for k in removed],META:groups,'externalDialogueIds':[int(k) for k in incoming]})
        return {**load(store,project.id,api),'ok':True,'warnings':result.get('warnings',[])}
