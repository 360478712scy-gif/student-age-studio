"""Merge several local mods into one new mod. Source mods are never modified.

preview(): reads every mod's configuration tables and files, reports where they
disagree (same record id or same file path with different content) and where a
choice is needed. merge(): creates a new mod (store.create) and fills it with the
union of all sources, taking the chosen source for each conflict. Resource paths
that name a source package are rewritten to the new package.
"""
import copy
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

PERSON_TABLES = {'PersonCfg': '人物', 'PersonGrowCfg': '人物成长', 'KZoneProfileCfg': '企鹅个人档', 'ModFaceCfg': '人物表情',
                 'BirthdayPaintGuessCfg': '生日画作'}
TABLE_LABELS = {'EvtCfg': '事件', 'TalkCfg': '对话', 'OptionCfg': '选项', 'BgCfg': '场景', 'CGCfg': 'CG', 'ActionCfg': '行动',
                'ActionEvtCfg': '行动事件', 'InteractCfg': '社交文本', 'GiftEvtCfg': '礼物事件', 'ItemCfg': '物品', 'PaperCfg': '纸条',
                'IntentCfg': '目标', 'PhoneMsgCfg': '短信', 'KZoneContentCfg': '企鹅动态', 'KZoneCommentCfg': '企鹅评论',
                'ShopCfg': '商店', 'MinigameActionCfg': '小游戏关卡'}
STATE_DIR = 'StudentAgeStudio'
MAX_TOTAL = 4 * 1024 * 1024 * 1024


def _api(store):
    return sys.modules[type(store).__module__]


def _label(table):
    return PERSON_TABLES.get(table) or TABLE_LABELS.get(table) or table


def _row_name(table, row):
    if not isinstance(row, dict):
        return ''
    for key in ('name', 'title', 'content', 'desc', 'text'):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:40]
    return ''


def _digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _projects(store, project_ids):
    api = _api(store)
    seen, projects = set(), []
    for ident in project_ids or []:
        if not isinstance(ident, str) or ident in seen:
            continue
        seen.add(ident)
        project = store.project(ident)
        if project.readonly or project.original_mode:
            raise api.ApiError('只能合并可编辑的本地模组：' + project.name, 422)
        projects.append(project)
    if len(projects) < 2:
        raise api.ApiError('请至少选择两个模组。', 422)
    return projects


def _tables(store, project):
    """table name -> rows (dict). Unreadable tables are reported, not merged."""
    api = _api(store)
    result, problems = {}, []
    for name, path in store.cfg_table_files(project).items():
        table = name[:-5]
        try:
            rows = api.read_json(path, {})
            if not isinstance(rows, dict):
                raise api.ApiError(table + ' 不是以编号为键的配置表')
            result[table] = {str(k): v for k, v in rows.items()}
        except api.ApiError as error:
            problems.append(f'{project.name}：{table} 无法读取（{error.message}），合并时会跳过这张表。')
    return result, problems


def _files(store, project):
    """relative path -> (size, digest) for everything that is not a configuration table."""
    api = _api(store)
    found = {}
    for root, directories, files in os.walk(project.path, followlinks=False):
        base = Path(root)
        directories[:] = [d for d in directories if not (base / d).is_symlink() and not api.excluded_entry(base / d, project.path)]
        for filename in files:
            file = base / filename
            if file.is_symlink() or api.excluded_entry(file, project.path) or not api.inside(file, project.path):
                continue
            relative = file.relative_to(project.path).as_posix()
            if relative == 'manifest.json' or relative.startswith('Cfgs/') or relative.startswith(STATE_DIR + '/'):
                continue
            found[relative] = file
    return found


def preview(store, project_ids):
    api = _api(store)
    with store.lock:
        projects = _projects(store, project_ids)
        problems, conflicts = [], []
        tables_by_project, files_by_project = {}, {}
        for project in projects:
            tables, table_problems = _tables(store, project)
            problems += table_problems
            tables_by_project[project.id] = tables
            files_by_project[project.id] = _files(store, project)
        names = {p.id: p.name for p in projects}
        # Records: the same id in several mods with different content needs a choice.
        all_tables = sorted({t for tables in tables_by_project.values() for t in tables})
        for table in all_tables:
            holders = {}
            for project in projects:
                for key, row in tables_by_project[project.id].get(table, {}).items():
                    holders.setdefault(key, []).append((project.id, row))
            for key, entries in holders.items():
                if len(entries) < 2:
                    continue
                if all(json.dumps(row, sort_keys=True, ensure_ascii=False) == json.dumps(entries[0][1], sort_keys=True, ensure_ascii=False) for _, row in entries):
                    continue
                conflicts.append({'kind': 'person' if table in PERSON_TABLES else 'record', 'table': table, 'label': _label(table), 'id': key,
                                  'options': [{'projectId': pid, 'projectName': names[pid], 'name': _row_name(table, row)} for pid, row in entries]})
        # Files: same path, different bytes.
        holders = {}
        for project in projects:
            for relative, file in files_by_project[project.id].items():
                holders.setdefault(relative, []).append((project.id, file))
        digests = {}
        for relative, entries in holders.items():
            if len(entries) < 2:
                continue
            sizes = {file.stat().st_size for _, file in entries}
            if len(sizes) == 1:
                hashes = {}
                for pid, file in entries:
                    hashes[pid] = digests.setdefault(str(file), _digest(file))
                if len(set(hashes.values())) == 1:
                    continue
            conflicts.append({'kind': 'file', 'table': '', 'label': '文件', 'id': relative,
                              'options': [{'projectId': pid, 'projectName': names[pid], 'name': str(file.stat().st_size) + ' 字节'} for pid, file in entries]})
        # Cross-mod checks that are not choices: a dialogue/option owned by one mod's event but overridden by another.
        talk_owner = {}
        for project in projects:
            for key in tables_by_project[project.id].get('TalkCfg', {}):
                talk_owner.setdefault(key, set()).add(project.id)
        shared = sum(1 for owners in talk_owner.values() if len(owners) > 1)
        if shared:
            problems.append(f'有 {shared} 句对话编号同时存在于多个模组，合并后只保留所选模组的那一版，其他模组接到这些对话的连接会指向保留下来的内容。')
        total = sum(f.stat().st_size for files in files_by_project.values() for f in files.values())
        if total > MAX_TOTAL:
            problems.append('素材总量超过 4 GB，无法合并。')
        summary = {'records': sum(len(rows) for tables in tables_by_project.values() for rows in tables.values()),
                   'files': sum(len(f) for f in files_by_project.values()), 'bytes': total}
        return {'projects': [{'id': p.id, 'name': p.name, 'package': p.package} for p in projects],
                'conflicts': conflicts, 'problems': problems, 'summary': summary}


def _choose(choices, kind, table, key, entries):
    wanted = (choices or {}).get(f'{kind}:{table}:{key}')
    for pid, value in entries:
        if pid == wanted:
            return value
    return entries[0][1]


def _merge_state(states):
    """editor-state.json across mods: unions where keys are ids, concatenation for order."""
    merged = {}
    for state in states:
        if not isinstance(state, dict):
            continue
        for key, value in state.items():
            if key == 'order' and isinstance(value, list):
                merged.setdefault('order', [])
                merged['order'] += [v for v in value if v not in merged['order']]
            elif key == 'pinnedIds' and isinstance(value, dict):
                target = merged.setdefault('pinnedIds', {})
                for kind, ids in value.items():
                    if isinstance(ids, list):
                        target.setdefault(kind, [])
                        target[kind] += [v for v in ids if v not in target[kind]]
            elif key == 'premises' and isinstance(value, dict):
                target = merged.setdefault('premises', {})
                for pid, premise in value.items():
                    if not isinstance(premise, dict):
                        continue
                    new_id = pid
                    while new_id in target:
                        new_id = str(int(new_id) + 1000) if str(new_id).isdigit() else new_id + '_'
                    target[new_id] = {**premise, 'id': int(new_id) if str(new_id).isdigit() else premise.get('id')}
            elif isinstance(value, dict):
                target = merged.setdefault(key, {})
                if isinstance(target, dict):
                    for k, v in value.items():
                        target.setdefault(k, v)
            elif key not in merged:
                merged[key] = value
    return merged


def merge(store, project_ids, choices=None, name=''):
    api = _api(store)
    with store.lock:
        projects = _projects(store, project_ids)
        report = preview(store, project_ids)
        if any('无法合并' in p for p in report['problems']):
            raise api.ApiError('；'.join(p for p in report['problems'] if '无法合并' in p), 413)
        title = api.display_name(name or '合并：' + '＋'.join(p.name for p in projects))
        created = store.create(title)
        destination = store.project(created['id'], writable=True)
        try:
            packages = {p.package.casefold() for p in projects} | {p.path.name.casefold() for p in projects}

            def remap(value):
                if isinstance(value, dict):
                    return {k: remap(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [remap(v) for v in value]
                if isinstance(value, str):
                    match = re.match(r'^(Mods[\\/])([^\\/]+)([\\/].*)$', value, re.IGNORECASE)
                    if match and match.group(2).casefold() in packages:
                        return match.group(1) + destination.package + match.group(3)
                return value

            # Tables: union, chosen source on conflict, first mod otherwise.
            tables_by_project = {p.id: _tables(store, p)[0] for p in projects}
            all_tables = sorted({t for tables in tables_by_project.values() for t in tables})
            for table in all_tables:
                merged = {}
                holders = {}
                for project in projects:
                    for key, row in tables_by_project[project.id].get(table, {}).items():
                        holders.setdefault(key, []).append((project.id, row))
                for key, entries in holders.items():
                    merged[key] = copy.deepcopy(_choose(choices, 'person' if table in PERSON_TABLES else 'record', table, key, entries))
                    if isinstance(merged[key], dict) and str(key).isdigit():
                        merged[key]['id'] = int(key)
                api.atomic_write(destination.path / 'Cfgs/zh-cn' / (table + '.json'), api.json_bytes(remap(merged)))
            # Files: copy every source file; a path present in several mods takes the chosen one.
            total = 0
            holders = {}
            for project in projects:
                for relative, file in _files(store, project).items():
                    holders.setdefault(relative, []).append((project.id, file))
            for relative, entries in holders.items():
                source = _choose(choices, 'file', '', relative, entries)
                total += source.stat().st_size
                if total > MAX_TOTAL:
                    raise api.ApiError('素材总量超过 4 GB，合并已停止。', 413)
                target = api.safe_path(destination.path, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                api.stable_copy(source, target)
            # Editor state and other JSON bookkeeping.
            states, others = [], {}
            for project in projects:
                folder = project.path / STATE_DIR
                if not folder.is_dir():
                    continue
                for file in folder.iterdir():
                    if file.is_symlink() or not file.is_file():
                        continue
                    if file.name == 'editor-state.json':
                        try: states.append(api.read_json(file, {}))
                        except api.ApiError: pass
                    elif file.suffix == '.json':
                        try: data = api.read_json(file, {})
                        except api.ApiError: continue
                        current = others.get(file.name)
                        if isinstance(data, dict) and isinstance(current, dict):
                            for k, v in data.items(): current.setdefault(k, v)
                        elif file.name not in others:
                            others[file.name] = data
            state_dir = destination.path / STATE_DIR
            state_dir.mkdir(exist_ok=True)
            if states:
                api.atomic_write(state_dir / 'editor-state.json', api.json_bytes(remap(_merge_state(states))))
            for filename, data in others.items():
                api.atomic_write(state_dir / filename, api.json_bytes(remap(data)))
            manifest = api.read_json(destination.path / 'manifest.json', {})
            dependencies = []
            for project in projects:
                for dep in (api.read_json(project.path / 'manifest.json', {}).get('dependencies') or []):
                    if dep not in dependencies: dependencies.append(dep)
            manifest['dependencies'] = dependencies
            manifest['description'] = '由 ' + '、'.join(p.name for p in projects) + ' 合并而成'
            api.atomic_write(destination.path / 'manifest.json', api.json_bytes(manifest))
            result = store.project(created['id']).public()
            result['problems'] = report['problems']
            return result
        except Exception:
            shutil.rmtree(destination.path, ignore_errors=True)
            raise
