import save_review
"""Native PhoneMsgCfg graph authoring. Preview timing stays outside game data."""
import copy
import math

TABLE='PhoneMsgCfg'
STATE='StudentAgeStudio/message-state.json'
DEFAULT={'id':0,'role':0,'content':'','next':[],'option':'','cond':[],'effect':[]}

def load(store, project_id, token, api):
    with store.lock, store.catalog_scope():
        project=store.project(project_id)
        commands=store.workshop_info(project_id)['commands']
        names={'PersonCfg',TABLE,'ConditionTypeCfg','EffectTypeCfg'}
        for templates in commands.values():
            if isinstance(templates,list):
                names.update(p['range']['table'] for t in templates for p in t.get('parameters',[]) if p.get('range',{}).get('table'))
        refs={};local_ids={}
        for name in names:
            table=store.table(project_id,name);refs[name]=table['rows'];local_ids[name]=table['localIds']
        hidden=api.read_json(project.path/'StudentAgeStudio/goal-images.json',{})
        accounts=[r for r in store.social.accounts(project,token) if str(r['id']) not in hidden]
        return {'table':store.table(project_id,TABLE),'accounts':accounts,'refs':refs,'localIds':local_ids,
                'commands':commands,'editor':api.read_json(project.path/STATE,{'titles':{},'previewDelays':{}}),
                'revision':store.revision(project),'defaults':DEFAULT}

def save(store,payload,api):
    with store.lock,store.catalog_scope():
        project=store.project(payload.get('projectId'),writable=True);revision=store.revision(project)
        save_review.revision(payload, revision, api.ApiError, '短信配置已变化，请重新读取。')
        path='Cfgs/zh-cn/'+TABLE+'.json';old=store.preserve_editing_rows(project,TABLE,store.editing_rows(project,TABLE))
        rows=store.preserve_editing_rows(project,TABLE,api.validate_map(payload.get('rows'),TABLE));base=store.catalog_rows(TABLE)
        all_rows={**base,**rows};previous={**base,**old};store.validate_fields(TABLE,rows,previous)
        people=store.table(project.id,'PersonCfg')['rows'];changed={k for k,r in rows.items() if r!=previous.get(k)}
        removed=set(old)-set(rows)-set(base)
        with save_review.checking(api.ApiError, '短信内容与回复连接'):
            for key in changed:
                row=rows[key];role=row.get('role');nexts=row.get('next') or []
                if type(role)is not int or str(role)not in people:raise api.ApiError('请选择短信发送人物。')
                if not isinstance(row.get('content',''),str):raise api.ApiError('短信内容必须是文字。')
                if not isinstance(nexts,list) or any(type(i)is not int for i in nexts) or len(set(nexts))!=len(nexts):raise api.ApiError('短信后续连接无效。')
                if nexts!=previous.get(key,{}).get('next',[]) and len(nexts)>2:raise api.ApiError('白雨每次最多提供两个回复选项。')
                for ident in nexts:
                    if str(ident)not in all_rows:raise api.ApiError('下一条短信不存在：'+str(ident))
                if len(nexts)>1 and any(all_rows[str(i)].get('role')!=0 for i in nexts):raise api.ApiError('分支选项必须是白雨发出的短信。')
                if role==0 and not str(row.get('option')or'').strip():row['option']=row['content']
                for field in ('cond','effect'):
                    if not isinstance(row.get(field,[]),list) or any(not isinstance(c,list) or any(type(v)not in (int,float) or not math.isfinite(v) for v in c) for c in row.get(field,[])):
                        raise api.ApiError('短信条件或效果参数无效。')
            # Traverse changed components only; unrelated legacy records are retained.
            seen=set();visiting=set()
            def visit(key):
                if key in visiting:raise api.ApiError('短信分支不能循环引用。')
                if key in seen:return
                visiting.add(key)
                for ident in all_rows.get(key,{}).get('next')or[]:visit(str(ident))
                visiting.remove(key);seen.add(key)
            for key in changed:visit(key)
            incoming={str(i) for row in all_rows.values() for i in row.get('next')or[]}
            for key in changed:
                if key not in incoming and key not in previous:
                    if int(key)%1000!=1 or rows[key]['role']==0:raise api.ApiError('首条短信必须由联系人发送，编号以 001 结尾。')
                if key not in incoming and rows[key].get('next') and all_rows[str(rows[key]['next'][0])].get('role')!=0 and rows[key].get('next')!=previous.get(key,{}).get('next'):
                    raise api.ApiError('原版首条来信后需要白雨回复；连续开场内容请写在首条来信中。')
        editor=copy.deepcopy(payload.get('editor',{}));old_editor=api.read_json(project.path/STATE,{})
        if not isinstance(editor,dict):raise api.ApiError('短信编辑记录无效。')
        for field in ('titles','previewDelays'):
            entries=editor.setdefault(field,{})
            if not isinstance(entries,dict):raise api.ApiError('短信编辑记录无效。')
            for key,value in list(entries.items()):
                if key not in all_rows:del entries[key];continue
                if field=='titles' and (not isinstance(value,str) or len(value)>120):raise api.ApiError('短信标题最长 120 字。')
                if field=='previewDelays' and (type(value)not in (int,float) or not math.isfinite(value) or not 0<=value<=120):raise api.ApiError('预览等待时间应在 0 至 120 秒之间。')
        proposed={name:api.read_json(p,{}) for name,p in store.cfg_table_files(project).items()};proposed[TABLE+'.json']=rows
        refs=store.deletion_references(project,TABLE,removed,{**base,**rows},proposed)
        if refs:raise api.ApiError('短信仍被以下内容引用：'+'；'.join(refs),409,'referenced')
        changes={}
        if rows!=old:changes[path]=api.json_bytes(rows)
        if editor!=old_editor:changes[STATE]=api.json_bytes(editor)
        if changes:store.commit(project,changes,revision)
        return {'ok':True,'rows':store.editing_rows(project,TABLE),'editor':editor,'revision':store.revision(project)}
