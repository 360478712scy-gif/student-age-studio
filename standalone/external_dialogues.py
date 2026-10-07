"""Event-less TalkCfg editing and editor-only folders, without synthetic events."""
import save_review
import copy
META='externalDialogueFolders'

def folders(value,talks,api,issues=None):
    notes = issues if issues is not None else []
    def note(message):
        if message not in notes: notes.append(message)
        save_review.note(message)
    if not isinstance(value,dict):
        note('对话夹格式无效，已保留未完成草稿。'); return copy.deepcopy(value)
    if len(value)>2000: note('对话夹数量超过 2000，已保留草稿。')
    used=set()
    for key,row in value.items():
        if not isinstance(key,str) or not key or len(key)>80 or not isinstance(row,dict):
            note('对话夹格式无效，已保留未完成草稿。'); continue
        name=row.get('name');ids=row.get('talkIds',[])
        if not isinstance(name,str) or not name.strip() or len(name)>120: note('请填写对话夹名称。')
        if not isinstance(ids,list): note('对话夹内容必须是对话列表。'); continue
        for ident in ids:
            if type(ident)!=int: note('对话编号必须是整数。'); continue
            if str(ident) not in talks: note('对话夹包含不存在或事件所属的对话。')
            if ident in used: note('一条对话只能归属一个对话夹。')
            used.add(ident)
    return copy.deepcopy(value)

def load(store,project_id,api,metadata=False):
    with store.lock,store.catalog_scope():
        project=store.project(project_id)
        if metadata:
            doc=store.talk_segments.open(project.id)
            table={'localRows':dict.fromkeys(str(i) for i in doc.get('localIds',{}).get('talks',[]))}
        else:
            doc=store.load(project.id);table=store.table(project.id,'TalkCfg')
        state=api.read_json(api.safe_path(project.path,'StudentAgeStudio/editor-state.json'),{})
        groups=copy.deepcopy(state.get(META,{}))
        shared={str(i) for f in (groups.values() if isinstance(groups,dict) else [])
                if isinstance(f,dict) and f.get('uses') for i in (f.get('talkIds',[]) if isinstance(f.get('talkIds',[]),list) else [])}
        shared.update(str(i) for i in (state.get('externalDialogueIds',[]) if isinstance(state.get('externalDialogueIds',[]),list) else []))
        talks={k:v for k,v in table['localRows'].items() if not doc.get('talkOwners',{}).get(k) or k in shared}
        # Folder metadata is the user's draft. Missing/duplicate references are
        # advisory and must survive reopening without being silently discarded.
        if metadata:return {'talkIds':[int(k) for k in talks],'folders':groups,'revision':store.revision(project)}
        refs={n:store.table(project.id,n)['rows'] for n in ('PersonCfg','BgCfg','MapCfg','ModFaceCfg','CGCfg','ItemCfg')}
        return {'talks':talks,'folders':groups,'doc':doc,'refs':refs,'revision':store.revision(project)}

def save(store,payload,api):
    with store.lock,store.catalog_scope():
        project=store.project(payload.get('projectId'),writable=True);current=load(store,project.id,api)
        save_review.revision(payload, current['revision'], api.ApiError, '对话已经被其他窗口修改，请重新打开。')
        incoming=api.validate_map(payload.get('talks',{}),'TalkCfg.json')
        notes=[]
        if any(current['doc'].get('talkOwners',{}).get(k) and k not in current['talks'] for k in incoming):
            issue='事件所属对话请在剧情编辑中修改。';notes.append(issue);save_review.note(issue)
        groups=folders(payload.get('folders',{}),incoming,api,notes)
        removed=set(current['talks'])-set(incoming)
        talks={k:v for k,v in current['doc']['talks'].items() if k not in removed};talks.update(incoming)
        result=store.save({'projectId':project.id,'revision':payload['revision'],'talks':talks,'deletedIds':[int(k) for k in removed],META:groups,'externalDialogueIds':[int(k) for k in incoming]})
        return {**load(store,project.id,api),'ok':True,'warnings':list(dict.fromkeys([*result.get('warnings',[]),*notes]))}
