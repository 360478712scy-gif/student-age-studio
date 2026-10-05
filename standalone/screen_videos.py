"""UP ScreenVideo library and transactional registration, separate from story drafts."""
from __future__ import annotations

import copy
import hashlib
import math
import os
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlencode

from platform_support import file_fingerprint
from video_transcode import EXTENSIONS

CONFIGS = ('EC2BUnofficialPatch/ScreenVideo/CustomVideo.json', 'ScreenVideo/CustomVideo.json')
RUNTIME_EXTENSIONS = {'.mp4', '.webm', '.mov', '.m4v'}
DEFAULTS = {'volume': 1, 'loop': False, 'skippable': True, 'roleOnTop': False, 'scale': 'fit'}
PAGE_SIZE = 36


def _conflict(api, text):
    raise api.ApiError(text, 409, 'conflict')


def _link(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def _within(api, root, relative):
    if not isinstance(relative, str) or '..' in relative:
        raise api.ApiError('视频必须使用 ScreenVideo 目录内的相对路径。', 422)
    path = api.safe_path(root, relative)
    cursor = root
    if _link(cursor):
        raise api.ApiError('视频目录不能使用符号链接或目录联接。', 403)
    for part in path.relative_to(root).parts:
        cursor = cursor / part
        if _link(cursor):
            raise api.ApiError('视频路径不能使用符号链接或目录联接。', 403)
    return path


def _registration(api, project, relative):
    path = _within(api, project.path, relative)
    value = api.read_json(path, {'videos': []})
    if not isinstance(value, dict) or not isinstance(value.get('videos'), list):
        raise api.ApiError('视频注册表格式无效，请先修复 ' + relative + '。', 422)
    seen = set()
    for row in value['videos']:
        if (not isinstance(row, dict) or type(row.get('id')) is not int
                or not 0 < row['id'] <= 2147483647 or row['id'] in seen):
            raise api.ApiError('视频注册表含无效或重复编号，请先修复 ' + relative + '。', 422)
        seen.add(row['id'])
    return path, value


def _normal_row(api, row):
    value = {**DEFAULTS, **copy.deepcopy(row)}
    if not isinstance(value.get('name', ''), str) or len(value.get('name', '')) > 200:
        raise api.ApiError('视频名称无效。')
    if (type(value['volume']) not in (float, int) or not math.isfinite(value['volume'])
            or not 0 <= value['volume'] <= 1):
        raise api.ApiError('视频音量必须在 0 到 1 之间。')
    if any(type(value[key]) is not bool for key in ('loop', 'skippable', 'roleOnTop')):
        raise api.ApiError('视频循环、跳过和人物置顶设置必须为布尔值。')
    if value['scale'] not in ('fit', 'fill', 'stretch'):
        raise api.ApiError('视频缩放方式无效。')
    return value


def _settings_path(store):
    return store.asset_catalog.settings_path.with_name('video-folders.json')


def _folder_settings(store, api):
    value = api.read_json(_settings_path(store), {'path': ''})
    if not isinstance(value, dict) or not isinstance(value.get('path'), str):
        raise api.ApiError('视频文件夹设置损坏，请先修复 video-folders.json。', 422)
    return value


def folder_get(store, api):
    with store.lock:
        value = _folder_settings(store, api)
        return {'path': value['path'], 'revision': hashlib.sha256(api.json_bytes(value)).hexdigest()}


def folder_set(store, api, payload):
    with store.lock:
        current = folder_get(store, api)
        if payload.get('revision') != current['revision']:
            _conflict(api, '视频文件夹设置已经变化，请刷新后再试。')
        value = payload.get('path')
        if not isinstance(value, str) or len(value) > 4096 or '\x00' in value:
            raise api.ApiError('请选择有效的视频文件夹。')
        value = os.path.expandvars(value.strip().strip('"\''))
        if value:
            path = Path(value).expanduser()
            if _link(path):
                raise api.ApiError('请选择实际视频文件夹，不能使用符号链接。', 403)
            path = path.resolve()
            if not path.is_dir():
                raise api.ApiError('视频文件夹不存在。', 404)
            try:
                next(path.iterdir(), None)
            except OSError as error:
                raise api.ApiError('无法读取视频文件夹，请检查权限。', 403) from error
            value = str(path)
        settings = _folder_settings(store, api)
        settings['path'] = value
        api.atomic_write(_settings_path(store), api.json_bytes(settings))
        return folder_get(store, api)


def _identity(api, path, config_digest=''):
    try:
        fingerprint = file_fingerprint(path) if path is not None else None
    except OSError:
        fingerprint = None
    return hashlib.sha256(api.json_bytes([fingerprint, config_digest])).hexdigest()


def _media(api, directory, relative, extensions):
    path = _within(api, directory, relative)
    if path.suffix.lower() not in extensions:
        raise api.ApiError('这个视频格式不可用。', 422)
    if not path.is_file() or path.stat().st_size == 0:
        raise api.ApiError('视频文件不存在或为空。', 404)
    return path


def _mod_items(store, api, project):
    result, seen = [], set()
    revision = store.revision(project)
    for relative in CONFIGS:
        config, database = _registration(api, project, relative)
        digest = hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else ''
        for row in database['videos']:
            if row['id'] in seen:
                raise api.ApiError('同一模组的两个视频注册表有重复编号，请先修复。', 422)
            seen.add(row['id'])
            asset_id = hashlib.sha256((project.id + '\0' + relative + '\0' + str(row['id'])).encode()).hexdigest()
            path, error, normal = None, '', copy.deepcopy(row)
            try:
                normal = _normal_row(api, row)
                path = _media(api, config.parent, row.get('video'), RUNTIME_EXTENSIONS)
            except (api.ApiError, OSError) as problem:
                error = str(problem)
            name = normal.get('name') or (Path(row.get('video', '')).stem if isinstance(row.get('video'), str) else '') or '视频 ' + str(row['id'])
            result.append({'assetId': asset_id, 'name': name, 'sourceProjectId': project.id,
                           'sourceRevision': revision, 'assetRevision': _identity(api, path, digest),
                           'videoId': row['id'], 'row': normal, 'available': path is not None,
                           'configPath': relative, 'assetPath': (str(config.parent.relative_to(project.path)) + '/' + row['video'].replace('\\', '/')) if path is not None else '',
                           'error': error, '_path': path})
    if store.revision(project) != revision:
        _conflict(api, '读取视频目录期间模组发生变化，请刷新。')
    return result


def _custom_items(store, api):
    settings = folder_get(store, api)
    root = Path(settings['path']) if settings['path'] else None
    if root is None or not root.is_dir() or _link(root):
        return []
    result = []
    for directory, folders, files in os.walk(root, followlinks=False):
        base = Path(directory)
        folders[:] = sorted(name for name in folders if not _link(base / name))
        for name in sorted(files):
            path = base / name
            if path.suffix.lower() not in EXTENSIONS or _link(path):
                continue
            relative = path.relative_to(root).as_posix()
            error = ''
            try:
                path = _media(api, root, relative, EXTENSIONS)
            except (api.ApiError, OSError) as problem:
                error, path = str(problem), None
            result.append({'assetId': hashlib.sha256(relative.encode()).hexdigest(),
                           'name': Path(name).stem, 'assetRevision': _identity(api, path, settings['revision']),
                           'available': path is not None, 'error': error, '_path': path})
    return result


def _library(store, api, query):
    project = store.project(query.get('projectId'))
    source = query.get('source', 'mod')
    if source not in ('mod', 'custom'):
        raise api.ApiError('视频来源无效；请选择模组或自定义视频文件夹。')
    projects, warnings = store.projects(), []
    if source == 'custom':
        items = _custom_items(store, api)
    else:
        source_id = query.get('sourceProjectId') or project.id
        selected = projects if source_id == 'all' else [store.project(source_id)]
        items = []
        for selected_project in selected:
            try:
                items.extend(_mod_items(store, api, selected_project))
            except api.ApiError as error:
                if source_id != 'all' or selected_project.id == project.id:
                    raise
                warnings.append({'projectId': selected_project.id, 'message': str(error)})
    return project, items, projects, warnings


def access(store, api, query):
    with store.lock:
        project, items, projects, warnings = _library(store, api, query)
        text = str(query.get('q', '')).strip().casefold()
        if text:
            items = [item for item in items if text in item['name'].casefold() or text in str(item.get('videoId', ''))]
        try:
            page = max(0, int(query.get('page', 0)))
        except (ValueError, TypeError):
            raise api.ApiError('视频目录页码无效。')
        total = len(items)
        page = min(page, max(0, (total - 1) // PAGE_SIZE))
        public = []
        for item in items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
            value = {key: copy.deepcopy(val) for key, val in item.items() if not key.startswith('_')}
            selection = {'projectId': project.id, 'source': query.get('source', 'mod'),
                         'assetId': item['assetId'], 'assetRevision': item['assetRevision']}
            selection.update({key: item[key] for key in ('sourceProjectId', 'sourceRevision') if key in item})
            value['previewUrl'] = '/api/video-file?' + urlencode(selection) if item['available'] else ''
            public.append(value)
        return {'items': public, 'total': total, 'page': page, 'pageSize': PAGE_SIZE,
                'revision': store.revision(project), 'projects': [{'id': p.id, 'name': p.name} for p in projects],
                'folder': folder_get(store, api), 'warnings': warnings}


def _selection(store, api, query, writable=False):
    project = store.project(query.get('projectId'), writable=writable)
    if writable and query.get('revision') != store.revision(project):
        _conflict(api, '导入前当前模组已经变化，请重新载入。')
    _, items, _, _ = _library(store, api, query)
    item = next((item for item in items if item['assetId'] == query.get('assetId')), None)
    if item is None:
        _conflict(api, '来源视频已移除或目录已经变化，请刷新视频库。')
    if not query.get('assetRevision') or query['assetRevision'] != item['assetRevision']:
        _conflict(api, '来源视频已经变化，请刷新视频库后再导入。')
    if 'sourceRevision' in item and query.get('sourceRevision') != item['sourceRevision']:
        _conflict(api, '来源模组已经变化，请刷新视频库。')
    if not item['available']:
        raise api.ApiError(item['error'] or '来源视频不可用。', 422)
    return item


def resolve_import(store, api, payload):
    with store.lock:
        item = _selection(store, api, payload, writable=True)
        return item['_path'], copy.deepcopy(item.get('row', {'name': item['name'], **DEFAULTS}))


def file_path(store, api, query):
    with store.lock:
        return _selection(store, api, query)['_path']


def _next_id(store, api, destination):
    used = set()
    for project in store.projects():
        for relative in CONFIGS:
            try:
                _, database = _registration(api, project, relative)
            except api.ApiError:
                if project.id == destination.id:
                    raise
                continue
            used.update(row['id'] for row in database['videos'])
    for attempt in range(100):
        candidate = secrets.randbelow(2147483647) + 1
        if candidate not in used:
            return candidate
    raise api.ApiError('暂时无法分配视频编号，请重试。', 409)


def commit_import(store, api, project, expected_revision, converted_bytes, metadata, payload):
    with store.lock:
        if expected_revision != store.revision(project):
            _conflict(api, '视频转换期间模组已经变化，请重新导入。')
        if project.readonly:
            raise api.ApiError('订阅模组只能浏览；请复制为本地副本后编辑。', 403, 'read_only')
        if not isinstance(converted_bytes, bytes) or not converted_bytes:
            raise api.ApiError('视频转换没有生成有效文件。', 422, 'video_conversion')
        # Conversion runs without the store lock. Reject any replaced source or
        # changed source registration before committing either destination file.
        selected = _selection(store, api, payload, writable=True) if 'assetId' in payload else None
        source_row = selected.get('row', payload.get('row', {})) if selected else payload.get('row', {})
        if not isinstance(source_row, dict):
            raise api.ApiError('来源视频配置无效。')
        row = copy.deepcopy(source_row)
        row.update({key: payload[key] for key in ('name', *DEFAULTS) if key in payload})
        row.setdefault('name', Path(str(payload.get('fileName', '视频')).replace('\\', '/')).stem or '视频')
        row = _normal_row(api, row)
        row['id'] = _next_id(store, api, project)
        row['video'] = 'video_' + uuid.uuid4().hex + '.mp4'
        relative = 'ScreenVideo/' + row['video']
        _within(api, project.path, relative)
        config, database = _registration(api, project, CONFIGS[1])
        database = copy.deepcopy(database)
        database['videos'].append(row)
        backup = store.commit(project, {relative: converted_bytes,
                              CONFIGS[1]: api.json_bytes(database)}, expected_revision)
        return {**metadata, 'ok': True, 'projectId': project.id, 'id': row['id'], 'videoId': row['id'],
                'row': row, 'assetPath': relative, 'url': 'Mods\\' + project.package + '\\' + relative.replace('/', '\\'),
                'revision': store.revision(project), 'previousRevision': expected_revision,
                'imported': True, 'importDelta': {}, 'backup': backup}


def settings_save(store, api, payload):
    with store.lock:
        project = store.project(payload.get('projectId'), writable=True)
        expected = payload.get('revision')
        if expected != store.revision(project):
            _conflict(api, '视频配置已经变化，请重新载入后保存。')
        if type(payload.get('id')) is not int or payload['id'] <= 0:
            raise api.ApiError('视频编号无效。')
        matches = []
        for relative in CONFIGS:
            config, database = _registration(api, project, relative)
            for index, row in enumerate(database['videos']):
                if row['id'] == payload['id']:
                    matches.append((relative, config, database, index, row))
        if len(matches) != 1:
            raise api.ApiError('视频注册缺失或编号重复，请刷新后检查配置。', 422)
        relative, config, database, index, row = matches[0]
        _media(api, config.parent, row.get('video'), RUNTIME_EXTENSIONS)
        changed = copy.deepcopy(row)
        changed.update({key: payload[key] for key in ('name', *DEFAULTS) if key in payload})
        changed = _normal_row(api, changed)
        database = copy.deepcopy(database)
        database['videos'][index] = changed
        backup = store.commit(project, {relative: api.json_bytes(database)}, expected)
        return {'ok': True, 'projectId': project.id, 'id': changed['id'], 'row': changed,
                'revision': store.revision(project), 'previousRevision': expected,
                'imported': True, 'importDelta': {}, 'backup': backup}
