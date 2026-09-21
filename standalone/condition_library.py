"""Index real condition groups without guessing names or changing native parameters."""
from storage_paths import game_cache, auxiliary_cache
import argparse
import copy
import hashlib
import json
import math
import subprocess
import threading
from pathlib import Path
from platform_support import worker_command, process_options, replace_file

VERSION = 1
FIELDS = {'condition': '触发条件', 'cond': '出现条件', 'check': '分支条件',
          'precondition': '选项限制', 'unlockCondition': '解锁条件'}


def text(value):
    if isinstance(value, list): value = next((v for v in value if isinstance(v, str)), '')
    return ' '.join(str(value or '').split())[:90]


def collect(table, rows, schema=None):
    fields = dict(FIELDS)
    for field in (schema or {}).get('fields', []):
        if str(field.get('editorType', '')).lower() == 'condition':
            fields[field['name']] = field.get('label') or '条件'
    result = []
    for key, row in rows.items():
        if not isinstance(row, dict): continue
        title = next((text(row.get(k)) for k in ('title', 'name', 'content', 'desc') if text(row.get(k))), '')
        category = (schema or {}).get('label') or table
        for field, label in fields.items():
            group = row.get(field)
            if not isinstance(group, list) or not group: continue
            if not all(isinstance(command, list) and command and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in command) for command in group): continue
            result.append({'rows': copy.deepcopy(group), 'title': title or category + '（原配置未命名）',
                           'table': table, 'recordId': str(key), 'field': field, 'fieldLabel': label, 'category': category})
    return result


def compact(entries):
    groups = {}
    for entry in entries:
        # Native condition numbers are doubles: 1 and 1.0 describe the same rule.
        key = json.dumps([[float(v) for v in row] for row in entry['rows']], separators=(',', ':'))
        if key not in groups:
            groups[key] = dict(entry, key=hashlib.sha256(key.encode()).hexdigest()[:24], uses=1, sources=[])
        else:
            groups[key]['uses'] += 1
        group = groups[key]
        source = {k: entry[k] for k in ('table', 'recordId', 'field', 'title', 'fieldLabel', 'category')}
        if len(group['sources']) < 5 and source not in group['sources']: group['sources'].append(source)
    return list(groups.values())


def bundles(game):
    return sorted((p for folder in (game / 'StudentAge_Data/StreamingAssets', game / 'DLC') for p in folder.rglob('*cfgs*.bundle')), key=lambda p: ('dlc' in str(p).lower(), str(p)))


def bundle_stamp(game):
    return [[str(p.relative_to(game)), p.stat().st_size, p.stat().st_mtime_ns] for p in bundles(game)]


def extract(game):
    from extract_game_assets import UnityPy
    game = Path(game)
    schemas = json.loads(Path(__file__).with_name('catalog-schema.json').read_text(encoding='utf-8'))['schemas']
    by_lower = {key.lower(): key for key in schemas}
    tables = {}
    stamp = bundle_stamp(game)
    for bundle in bundles(game):
        env = UnityPy.load(str(bundle))
        for name, obj in env.container.items():
            lower = name.lower().replace('\\', '/')
            if '/cfgs/' not in lower or not any('/' + language + '/' in lower for language in ('zh-cn', 'dlc_zh-cn')) or not lower.endswith('.json') or obj.type.name != 'TextAsset': continue
            table = by_lower.get(Path(lower).stem, Path(name).stem)
            rows = json.loads(obj.read().m_Script, strict=False)
            if isinstance(rows, list): rows = {str(r['id']): r for r in rows if isinstance(r, dict) and 'id' in r}
            if isinstance(rows, dict): tables.setdefault(table, {}).update(rows)
    entries = compact([e for table, rows in tables.items() for e in collect(table, rows, schemas.get(table))])
    if stamp != bundle_stamp(game): raise RuntimeError('读取时游戏配置发生变化，请重新读取。')
    target = game_cache(game) / 'condition-library.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.reading.tmp')
    temp.write_text(json.dumps({'version': VERSION, 'stamp': stamp, 'entries': entries}, ensure_ascii=False), encoding='utf-8')
    replace_file(temp, target)
    return {'conditions': len(entries), 'tables': len(tables)}


def named_entries(premises):
    result = []
    for p in premises.values():
        if not isinstance(p, dict) or not all(isinstance(p.get(k), int) for k in ('eventId', 'slot')): continue
        talk = p.get('talkId') if type(p.get('talkId')) is int else None
        for reached in (True, False):
            title = ('已达成：' if reached else '未达成：') + text(p.get('name') or '前提' + str(p.get('id', '')))
            if talk is not None:
                # Dialogue-bound premise: the game's own "talk reached" check.
                result.append({'rows': [[3, 3 if reached else -3, talk]], 'title': title, 'category': '命名前提',
                               'fieldLabel': '前提条件', 'table': 'TalkCfg', 'recordId': str(talk), 'field': 'check', 'origin': 'named'})
                continue
            result.append({'rows': [[111, 1 if reached else 2, p['eventId'], p['slot'], 1 if reached else 0]],
                           'title': title, 'category': '命名前提', 'fieldLabel': '前提条件', 'table': 'EvtCfg',
                           'recordId': str(p['eventId']), 'field': 'condition', 'origin': 'named'})
    return compact(result)


class ConditionLibrary:
    def __init__(self, store, api):
        self.store, self.api = store, api
        self.thread = None
        self.error = None
        self.lock = threading.Lock()
        self.cache_key = None
        self.cache = []
        self.mod_cache = {}
        self.table_cache = {}
        self.table_lock = threading.RLock()

    def local_entries(self, project):
        # A title/text edit must not invalidate conditions in every other JSON file.
        entries, failures = [], {}
        with self.table_lock, self.store.catalog_scope():
            schema_stamp=self.store.catalog_stamp()
            for filename,path in self.store.cfg_table_files(project).items():
                key=(str(project.path),filename)
                stamp=(self.api.file_fingerprint(path),schema_stamp)
                cached=self.table_cache.get(key)
                if cached and cached[0]==stamp:
                    entries.extend(copy.deepcopy(cached[1]));continue
                maps, errors=self.store.readable_maps(project,{filename})
                failures.update(errors)
                if errors:
                    self.table_cache.pop(key,None);continue
                rows=maps.get(filename,{})
                found=collect(filename[:-5],rows,self.store.table_schema(filename[:-5],rows))
                if self.api.file_fingerprint(path)==stamp[0]:
                    self.table_cache[key]=(stamp,found)
                    while len(self.table_cache)>256:self.table_cache.pop(next(iter(self.table_cache)))
                entries.extend(copy.deepcopy(found))
        return entries,failures

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive() or self.error: return
            def run():
                try:
                    done = subprocess.run(worker_command(Path(__file__), self.store.game), capture_output=True, text=True, encoding='utf-8', timeout=180, **process_options())
                    if done.returncode: raise RuntimeError((done.stderr or done.stdout or '读取游戏条件失败')[-800:])
                except Exception as error:
                    self.error = str(error)
            self.thread = threading.Thread(target=run, daemon=True)
            self.thread.start()

    def get_mods(self, project_id, mod_id='all'):
        self.store.project(project_id)
        projects = self.store.projects()
        selected = projects if mod_id == 'all' else [p for p in projects if p.id == mod_id]
        if not selected and mod_id != 'all': raise self.api.ApiError('找不到选择的模组。', 404)
        entries, warnings = [], []
        with self.store.catalog_scope():
            for project in selected:
                try:
                    revision = self.store.revision(project)
                    cached = self.mod_cache.get(project.id)
                    if not cached or cached[0] != revision:
                        rows, failures = self.local_entries(project)
                        rows = compact(rows)
                        state = self.api.read_json(self.api.safe_path(project.path, 'StudentAgeStudio/editor-state.json'), {})
                        premises = state.get('premises', {}) if isinstance(state, dict) else {}
                        for entry in rows:
                            entry['premises'] = [{'eventId': p['eventId'], 'slot': p['slot'], 'name': text(p.get('name') or '前提'+str(p.get('id', '')))} for p in premises.values() if isinstance(p, dict) and type(p.get('eventId')) is int and type(p.get('slot')) is int and any(len(r) == 5 and r[0] == 111 and r[2:4] == [p['eventId'], p['slot']] for r in entry['rows'])] if isinstance(premises, dict) else []
                        self.mod_cache[project.id] = (revision, rows, bool(failures))
                        cached = self.mod_cache[project.id]
                    entries.extend(dict(e, origin='mod', projectId=project.id, projectName=project.name) for e in cached[1])
                    if cached[2]: warnings.append(project.name + '：部分配置未能读取')
                except (OSError, self.api.ApiError) as error:
                    warnings.append(project.name + '：' + str(error))
        available = {p.id for p in projects}
        self.mod_cache = {key:value for key,value in self.mod_cache.items() if key in available}
        return {'entries':entries, 'projects':[p.public() for p in projects], 'warnings':warnings}

    def get(self, project_id):
        project = self.store.project(project_id)
        cache_file = game_cache(self.store.game) / 'condition-library.json'
        try:
            stamp = bundle_stamp(self.store.game)
            cached = self.api.read_json(cache_file, {})
        except (OSError, self.api.ApiError):
            stamp, cached = [], {}
        complete = cached.get('version') == VERSION and cached.get('stamp') == stamp
        if not complete and stamp: self.start()
        revision = self.store.revision(project)
        key = (project.id, revision, cache_file.stat().st_mtime_ns if cache_file.exists() else None)
        if key != self.cache_key:
            catalog = self.store.catalog()
            original = cached.get('entries', []) if complete else compact([e for table, rows in catalog.get('tables', {}).items() if isinstance(rows, dict) for e in collect(table, rows, catalog.get('schemas', {}).get(table))])
            local, _ = self.local_entries(project)
            state = self.api.read_json(self.api.safe_path(project.path, 'StudentAgeStudio/editor-state.json'), {})
            premises = state.get('premises', {}) if isinstance(state, dict) else {}
            self.cache = [dict(e, origin=origin) for origin, rows in [('original', original), ('local', compact(local)), ('named', named_entries(premises))] for e in rows]
            self.cache_key = key
        return {'templates': self.api.read_json(Path(__file__).with_name('condition-templates.json'), []), 'entries': self.cache, 'indexing': bool(self.thread and self.thread.is_alive()),
                'complete': complete, 'warning': self.error, 'revision': revision}


class UserConditionPresets:
    """Personal reusable groups, outside all mods and protected across app windows."""
    def __init__(self, path, api):
        self.path, self.api = Path(path), api
        self.lock = threading.RLock()

    def validate_rows(self, rows):
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
            raise self.api.ApiError('请先添加条件；每个配置最多保存 1000 条条件。')
        if any(not isinstance(row, list) or not 2 <= len(row) <= 256 or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in row) for row in rows):
            raise self.api.ApiError('条件参数无效，请检查右侧已添加条件。')
        return copy.deepcopy(rows)

    def access(self, payload=None):
        import uuid
        from platform_support import lock_file, unlock_file
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix('.lock').open('a+b') as handle:
                try:
                    lock_file(handle)
                except BlockingIOError as error:
                    raise self.api.ApiError('另一个窗口正在保存用户条件配置，请稍后重试。', 409, 'condition_busy') from error
                try:
                    data = self.api.read_json(self.path, {'entries': []})
                    if not isinstance(data, dict) or not isinstance(data.get('entries'), list):
                        raise self.api.ApiError('用户条件配置文件格式无效，未覆盖原文件。')
                    entries = data['entries']
                    if payload is not None:
                        action = payload.get('action')
                        if action == 'save':
                            rows = self.validate_rows(payload.get('rows'))
                            title = payload.get('title', '')
                            if not isinstance(title, str) or len(title) > 120 or any(c in title for c in '\r\n'):
                                raise self.api.ApiError('配置名称最多 120 个字，不能换行。')
                            title = title.strip()
                            if not title:
                                number = 1
                                while any(e.get('title') == '配置'+str(number) for e in entries): number += 1
                                title = '配置'+str(number)
                            names = payload.get('premises', [])
                            if not isinstance(names, list) or len(names) > 1000:
                                raise self.api.ApiError('前提名称格式无效。')
                            clean = []
                            for item in names:
                                if not isinstance(item, dict) or type(item.get('eventId')) is not int or type(item.get('slot')) is not int or not isinstance(item.get('name'), str) or len(item['name']) > 120:
                                    raise self.api.ApiError('前提名称格式无效。')
                                if any(row[0] == 111 and len(row) == 5 and row[2:4] == [item['eventId'],item['slot']] for row in rows): clean.append(copy.deepcopy(item))
                            entries.append({'key': uuid.uuid4().hex, 'title': title, 'rows': rows, 'premises': clean})
                        elif action == 'delete':
                            key = payload.get('key')
                            if not any(e.get('key') == key for e in entries):
                                raise self.api.ApiError('该配置已被删除，请刷新后重试。', 404)
                            entries = [e for e in entries if e.get('key') != key]
                        else:
                            raise self.api.ApiError('不支持的配置操作。')
                        self.api.atomic_write(self.path, self.api.json_bytes({**data, 'entries': entries}))
                    return {'entries': copy.deepcopy(entries)}
                finally:
                    unlock_file(handle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--game', required=True)
    print(json.dumps(extract(parser.parse_args().game)), flush=True)
