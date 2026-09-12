"""Read-only diagnosis and explicit, backed-up safe JSON separator repair."""
import hashlib
import json
from pathlib import Path


def inspect(store, project_id, api):
    project = store.project(project_id)
    revision = store.revision(project)
    digest = hashlib.sha256()
    issues, changes = [], {}
    files = store.json_document_files(project)
    for relative, path in files.items():
        digest.update(relative.encode('utf-8'))
        try:
            if path.stat().st_size > store.JSON_SOURCE_LIMIT:
                digest.update(str(path.stat().st_size).encode())
                issues.append({'path':relative,'message':'文件超过内置文本检查范围，请用外部编辑器检查。','fixable':False})
                continue
            data = path.read_bytes()
            digest.update(data)
            text = data.decode('utf-8-sig')
            analysis = api.analyze_json_text(text)
            if not analysis['valid']:
                repair = api.analyze_json_text(text, repair=True)
                fixable = bool(repair['valid'] and repair['fixes'])
                message = '；'.join('第 %s 行第 %s 列：%s' % (e['line'], e['col'], e['message']) for e in analysis['errors'])
                issues.append({'path':relative,'message':message,'fixable':fixable,'action':('补齐 %s 处缺失逗号'%len(repair['fixes'])) if fixable else '无法可靠自动修复，请打开 JSON 定位修改。'})
                if fixable:
                    changes[relative] = (b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b'') + repair['text'].encode('utf-8')
                continue
            # Known table naming is separate from auxiliary mappings such as CustomKeyMap.
            if relative.startswith('Cfgs/') and path.name.endswith('Cfg.json'):
                rows=json.loads(api.compatible_json(text),strict=False)
                try: api.validate_map(rows,path.name,allow_zero=True)
                except api.ApiError as error:
                    issues.append({'path':relative,'message':error.message,'fixable':False,'action':'键与行编号哪一个正确无法自动确定，保留原文，请在 JSON 中修改。'})
        except (OSError, UnicodeError, ValueError, RecursionError) as error:
            issues.append({'path':relative,'message':'无法读取：'+str(error),'fixable':False})
    if revision != store.revision(project):
        raise api.ApiError('检查期间模组发生变化，请重新检查。',409,'conflict')
    return {'revision':revision,'scanToken':digest.hexdigest(),'filesChecked':len(files),'issues':issues,'repairable':len(changes),'readOnly':project.readonly}, changes


def check(store,payload,api):
    with store.lock:
        result,_=inspect(store,payload.get('projectId'),api)
        return result


def repair(store,payload,api):
    with store.lock:
        project=store.project(payload.get('projectId'),writable=True)
        result,changes=inspect(store,project.id,api)
        if payload.get('revision') != result['revision'] or payload.get('scanToken') != result['scanToken']:
            raise api.ApiError('检查后的文件已经变化，请重新检查再修复。',409,'conflict')
        if not changes:return {**result,'fixed':[],'backup':None}
        backup=store.commit(project,changes,result['revision'],raw=True)
        after,_=inspect(store,project.id,api)
        return {**after,'fixed':list(changes),'backup':backup}
