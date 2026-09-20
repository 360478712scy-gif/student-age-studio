"""Native objectives and user-provided head images, saved in one transaction."""
import save_review
import base64
import copy
from pathlib import Path

IMAGE_META = 'StudentAgeStudio/goal-images.json'
FIELD_LABELS = {'id':'目标编号','name':'目标标题','desc':'目标描述','npc':'目标图像',
                'finishType':'移除规则','round':'持续回合','demand':'完成要求','reward':'完成奖励',
                'condition':'出现条件','fail':'失败效果','failTalk':'失败后对话','finishTalk':'完成后对话',
                'before':'前置目标','next':'后续目标组','group':'目标组','renshengguan':'优先匹配的人生观',
                'tag':'目标分类','targetRound':'截止回合','weight':'同组随机权重'}

def load(store, project_id, api):
    with store.lock:
        project = store.project(project_id)
        return {'goals':store.table(project_id,'IntentCfg'), 'people':store.table(project_id,'PersonCfg'),
                'images':api.read_json(api.safe_path(project.path,IMAGE_META), {}), 'revision':store.revision(project)}

def save(store, payload, api):
    with store.lock, store.catalog_scope():
        project = store.project(payload.get('projectId'), writable=True)
        revision = store.revision(project)
        save_review.revision(payload, revision, api.ApiError, '目标配置已变化，请重新载入。')
        goal_path = 'Cfgs/zh-cn/IntentCfg.json'
        old = store.preserve_editing_rows(project,'IntentCfg',store.editing_rows(project,'IntentCfg'))
        base = store.catalog_rows('IntentCfg')
        rows = api.validate_map(payload.get('rows'), 'IntentCfg', allow_zero='0' in old or '0' in base)
        rows = store.preserve_editing_rows(project, 'IntentCfg', rows)
        store.validate_fields('IntentCfg', rows, {**base, **old})
        people_path = 'Cfgs/zh-cn/PersonCfg.json'
        local_people = api.read_json(api.safe_path(project.path,people_path), {})
        people = copy.deepcopy(local_people)
        images = api.read_json(api.safe_path(project.path,IMAGE_META), {})
        old_images = copy.deepcopy(images)
        changes = {}
        uploads = payload.get('images', [])
        if not isinstance(uploads,list) or len(uploads)>100:raise api.ApiError('目标图像列表无效。')
        for upload in uploads:
            ident = upload.get('id') if isinstance(upload,dict) else None
            if type(ident) is not int or not 1 <= ident <= 2147483647:raise api.ApiError('目标图像编号无效，请重新添加。')
            key = str(ident)
            if key in people or key in store.catalog_rows('PersonCfg'):raise api.ApiError('目标图像的编号已被占用，请重新添加。',409,'id_conflict')
            data = upload.get('data','')
            if not isinstance(data,str) or len(data)>12*1024*1024:raise api.ApiError('目标图像文件过大。')
            try:raw = base64.b64decode(data, validate=True)
            except (ValueError,TypeError):raise api.ApiError('目标图像编码无效。')
            normalized, extension, width, height = api.normalize_image(raw)
            stem = 'Textures/GoalImages/goal_' + key
            url = 'Mods\\' + project.package + '\\' + (stem + extension).replace('/', '\\')
            # IntentData.GetIntentIcon dereferences PersonCfg.npc, then GetHeadIcon appends _head.
            # Supply all static variants without creating a social/affection character.
            for suffix in ('','_head','_half'):
                changes[stem+suffix+extension] = normalized
            schema = store.table_schema('PersonCfg')
            person = {f['name']:copy.deepcopy(f.get('default', [] if f.get('type','').startswith('list') else '' if f.get('type')=='string' else 0)) for f in schema.get('fields',[])}
            person.update(id=ident,name=('目标配图 · '+str(upload.get('name') or '图像'))[:120],init=[1],gender=1,url=[url],url2=[url],l2d=[],l2d2=[])
            people[key] = person
            images[key] = {'name':person['name'], 'url':url,'head':url[:-len(extension)]+'_head'+extension}
        all_people = {**store.catalog_rows('PersonCfg'), **people}
        for key,row in rows.items():
            previous = {**base, **old}.get(key,{})
            if row == previous:continue
            if not isinstance(row.get('name',''),str):raise api.ApiError('目标标题必须是文字。')
            if row.get('finishType',0) not in (0,1,2):save_review.warn(api.ApiError, '请从三种移除规则中选择一项。')
            if str(row.get('npc',0)) not in all_people:save_review.warn(api.ApiError, '请选择有效的目标图像。')
            for field in ('round','targetRound'):
                if type(row.get(field,0)) is not int or row.get(field,0)<0:save_review.warn(api.ApiError, '目标回合数应为非负整数。')
            before = row.get('before',0)
            if before and (str(before) == key or str(before) not in {**base,**rows}):save_review.warn(api.ApiError, '请选择存在且不同于自己的前置目标。')
            if row.get('weight',0)<0:save_review.warn(api.ApiError, '同组随机权重不能小于零。')
        proposed = {filename:api.read_json(path,{}) for filename,path in store.cfg_table_files(project).items()}
        proposed['IntentCfg.json'] = rows;proposed['PersonCfg.json'] = people
        removed = set(old) - set(rows) - set(base)
        refs = store.deletion_references(project,'IntentCfg',removed,{**base,**rows},proposed)
        if refs:save_review.warn(api.ApiError, '目标仍被以下内容引用：'+'；'.join(refs),409,'referenced')
        # Only reclaim helpers we created, whose image and non-social identity
        # still match metadata, and which no proposed native record references.
        for key, image in list(images.items()):
            person=people.get(key,{})
            if key in store.catalog_rows('PersonCfg') or person.get('init') != [1] or person.get('url') != [image.get('url')]: continue
            if store.deletion_references(project,'PersonCfg',{key},people,proposed): continue
            people.pop(key,None);images.pop(key,None)
        if rows != old:changes[goal_path] = api.json_bytes(rows)
        if people != local_people:changes[people_path] = api.json_bytes(people)
        if images != old_images:changes[IMAGE_META] = api.json_bytes(images)
        if changes:store.commit(project,changes,revision)
        return {'ok':True,'revision':store.revision(project),'rows':store.editing_rows(project,'IntentCfg'), 'images':images, 'people':people}
