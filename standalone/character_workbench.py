import save_review
"""Character workspace: related records are validated and committed together."""
import copy
import json
from pathlib import Path

TABLES=('PersonCfg','PersonGrowCfg','ModFaceCfg','KZoneAvatarCfg','KZoneProfileCfg')

def load(store, project_id):
    with store.lock:
        result={name:store.table(project_id,name) for name in TABLES}
        project=store.project(project_id)
        from asset_labels import asset_name
        from headshots import scene_location
        bg=store.table(project_id,'BgCfg')['rows']
        outfits=json.loads((project.path/'StudentAgeStudio/character-outfits.json').read_text(encoding='utf-8-sig')) if (project.path/'StudentAgeStudio/character-outfits.json').exists() else {}
        places=[{'id':r['id'],'name':asset_name(r,'background'),'group':scene_location(asset_name(r,'background'))} for r in bg.values()]
        from goal_workbench import IMAGE_META
        image_path = project.path / IMAGE_META
        image_ids = list(json.loads(image_path.read_text(encoding='utf-8-sig'))) if image_path.is_file() else []
        from character_rules import references
        return {'tables':result,'outfits':outfits,'places':places,'rules':references(store, project),'goalImageIds':image_ids,'revision':result['PersonCfg']['revision'],'romance':store.api_romance(project)}

def save(store, payload, api):
    with store.lock:
        project=store.project(payload.get('projectId'),writable=True)
        revision=store.revision(project)
        save_review.revision(payload, revision, api.ApiError, '人物配置已被其他窗口修改，请重新打开。')
        supplied=payload.get('tables')
        if not isinstance(supplied,dict) or set(supplied)!=set(TABLES): raise api.ApiError('人物资料不完整，请重新打开人物编辑。')
        old={n:store.preserve_editing_rows(project,n,store.editing_rows(project,n)) for n in TABLES}
        base={n:store.catalog_rows(n) for n in TABLES}
        rows={n:api.validate_map(supplied[n],n,allow_zero='0' in old[n] or '0' in base[n]) for n in TABLES}
        rows={n:store.preserve_editing_rows(project,n,v) for n,v in rows.items()}
        from native_character import normalize_growth, default_growth
        rows['PersonGrowCfg']={k:normalize_growth({**old['PersonGrowCfg'].get(k,{}),**v}) if v!=old['PersonGrowCfg'].get(k) else copy.deepcopy(v) for k,v in rows['PersonGrowCfg'].items()}
        # Native social sorting indexes every social person's growth record.
        for key, person in rows['PersonCfg'].items():
            if person!=old['PersonCfg'].get(key) and (person.get('init') or [0])[0] in (2,3,4) and key not in rows['PersonGrowCfg'] and key not in base['PersonGrowCfg']:
                rows['PersonGrowCfg'][key]=default_growth(store,key)
        for n in TABLES:
            store.validate_fields(n,rows[n],{**base[n],**old[n]})
            rows[n]={k:{**old[n].get(k,{}),**copy.deepcopy(v)} for k,v in rows[n].items()}
        people={**base['PersonCfg'],**rows['PersonCfg']}
        removed=set(old['PersonCfg'])-set(rows['PersonCfg'])-set(base['PersonCfg'])
        for table in ('PersonGrowCfg','KZoneProfileCfg'):
            for key in set(rows[table])-set(old[table]):
                if key not in people: save_review.warn(api.ApiError, '成长与空间设置必须关联当前人物。')
        for key in set(rows['ModFaceCfg'])-set(old['ModFaceCfg']):
            if str(int(key)//1000) not in people: save_review.warn(api.ApiError, '自定义表情必须关联当前人物。')
        for key in set(rows['KZoneAvatarCfg'])-set(old['KZoneAvatarCfg'])-set(base['KZoneAvatarCfg']):
            if not 1<=int(key)<=2147483647: save_review.warn(api.ApiError, '头像编号超出可用范围。')
        with save_review.checking(api.ApiError, '人物生日与性别'):
            for key,row in rows['PersonCfg'].items():
                before={**base['PersonCfg'],**old['PersonCfg']}.get(key,{})
                if row.get('birthday')!=before.get('birthday') and row.get('birthday'):
                    from datetime import date
                    try: date(*row['birthday'])
                    except (ValueError,TypeError): raise api.ApiError('请选择有效的生日日期。')
                if row.get('gender')!=before.get('gender') and row.get('gender') not in (1,2): raise api.ApiError('请选择男或女。')
        rows['PersonGrowCfg']={k:v for k,v in rows['PersonGrowCfg'].items() if k not in removed}
        rows['ModFaceCfg']={k:v for k,v in rows['ModFaceCfg'].items() if str(int(k)//1000) not in removed}
        # Preserve all other tables for cross-reference checks, including dialogue and space profiles.
        proposed,unreadable=store.readable_maps(project)
        if removed and unreadable: raise api.ApiError('有关联配置无法读取，暂时不能删除人物；原文件已保留。')
        proposed.update({n+'.json':v for n,v in rows.items()})
        refs=store.deletion_references(project,'PersonCfg',removed,rows['PersonCfg'],proposed)
        avatar_removed=set(old['KZoneAvatarCfg'])-set(rows['KZoneAvatarCfg'])-set(base['KZoneAvatarCfg'])
        if avatar_removed and unreadable: raise api.ApiError('有关联配置无法读取，暂时不能删除头像；原文件已保留。')
        refs+=store.deletion_references(project,'KZoneAvatarCfg',avatar_removed,rows['KZoneAvatarCfg'],proposed)
        if refs: save_review.warn(api.ApiError, '以下内容仍被引用，保存删除后相关功能可能失效：'+'；'.join(refs),409,'referenced')
        outfit_path='StudentAgeStudio/character-outfits.json'
        old_outfits=api.read_json(api.safe_path(project.path,outfit_path),{})
        outfits=copy.deepcopy(payload.get('outfits',old_outfits))
        if not isinstance(outfits,dict): raise api.ApiError('服装配置无效。')
        for key in list(outfits):
            if key in removed: del outfits[key];continue
            if not isinstance(outfits[key],dict): raise api.ApiError('服装配置必须是对象。')
            if key not in rows['PersonCfg']: save_review.warn(api.ApiError, '服装必须关联模组内的人物。')
            used=set()
            for slot,outfit in outfits[key].items():
                if slot not in map(str,range(10)) or not isinstance(outfit,dict): raise api.ApiError('每个角色最多支持默认服装和九套其他服装。')
                if not isinstance(outfit.get('name'),str) or len(outfit['name'])>120: raise api.ApiError('请填写有效的服装名称。')
                places=outfit.get('backgrounds',[])
                if not isinstance(places,list) or any(type(n)!=int or n<=0 for n in places): raise api.ApiError('服装地点无效。')
                if used.intersection(places): save_review.warn(api.ApiError, '一个地点指定了多套服装，游戏可能只采用其中一套。')
                used.update(places);outfit['backgrounds']=list(dict.fromkeys(places))
                if int(slot)>0 and str(int(key)*1000+int(slot)*100) not in rows['ModFaceCfg']: save_review.warn(api.ApiError, '新增服装尚未选择立绘。')
        # nicknames[0]/[1] mean normal/lover names. Empty and duplicate slots
        # are meaningful; never split, compact or deduplicate the user's array.
        changes={'Cfgs/zh-cn/'+n+'.json':api.json_bytes(v) for n,v in rows.items() if v!=old[n]}
        if outfits!=old_outfits: changes[outfit_path]=api.json_bytes(outfits)
        from romance_settings import validate
        romance_path='StudentAgeStudio/character-romance.json'
        old_romance=store.api_romance(project)
        romance=validate(payload.get('romance',old_romance),rows['PersonCfg'],removed,old_romance,api)
        if romance!=old_romance:changes[romance_path]=api.json_bytes(romance)
        if changes: store.commit(project,changes,revision)
        rows = {name:store.editing_rows(project,name) for name in rows}
        return {'ok':True,'revision':store.revision(project),'tables':rows,'outfits':outfits,'romance':romance}

def import_media(store,payload,api):
    # A catalog selection copies only the image. It must not create a second character.
    with store.lock,store.catalog_scope():
        project=store.project(payload.get('projectId'),writable=True)
        revision=store.revision(project)
        if revision!=payload.get('revision'):raise api.ApiError('当前模组已变化，请重新选择图片。',409,'conflict')
        query={**payload,'projectId':project.id,'revision':revision}
        path=store.asset_catalog.preview(query)
        import base64
        if Path(path).stat().st_size>api.MAX_IMAGE:raise api.ApiError('图片超过大小限制。',413)
        return store.import_field_image({'projectId':project.id,'revision':revision,'fileName':Path(path).name,'data':base64.b64encode(Path(path).read_bytes()).decode()})
