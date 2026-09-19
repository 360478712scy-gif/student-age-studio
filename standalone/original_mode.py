"""Request-local original-resource view, saved as overrides in the selected mod."""
import copy
import json
import re
import threading
import sys
from contextlib import contextmanager
from dataclasses import replace

_context = threading.local()
STATE = 'StudentAgeStudio/original-edits.json'


@contextmanager
def scope(project_id=None):
    previous = getattr(_context, 'project_id', None)
    _context.project_id = project_id
    try:
        yield
    finally:
        _context.project_id = previous


def view_project(project):
    return replace(project, original_mode=True) if project.id == getattr(_context, 'project_id', None) else project


def read_state(store, project):
    """Read edit records tolerantly: corrupt state opens as empty with a warning."""
    api = sys.modules[type(store).__module__]
    target = api.safe_path(project.path, STATE)
    try: state = api.read_json(target, {})
    except api.ApiError as error:
        if error.status != 422: raise
        return {}, '原版资源编辑记录损坏，已按空记录打开；请恢复备份后再在原版模式下保存。'
    if not isinstance(state, dict) or any(not isinstance(v, list) or any(not isinstance(k, str) or not k.isdigit() for k in v) for v in state.values()):
        return {}, '原版资源编辑记录损坏，已按空记录打开；请恢复备份后再在原版模式下保存。'
    return state, None


def owned(store, project):
    api = sys.modules[type(store).__module__]
    state, warning = read_state(store, project)
    if warning is not None:
        raise api.ApiError('原版资源编辑记录损坏，请恢复备份后继续。', 422)
    return state


def _tolerant(store, project, warnings):
    state, warning = read_state(store, project)
    if warning is not None and warnings is not None and warning not in warnings:
        warnings.append(warning)
    return state


def visible_rows(store, project, table, local, warnings=None):
    if not project.original_mode:
        return local
    native = store.catalog_rows(table)
    keys = set(native) | set(_tolerant(store, project, warnings).get(table, []))
    return {**copy.deepcopy(native), **{k:v for k,v in local.items() if k in keys}}


def preserve_rows(store, project, table, rows, warnings=None):
    """Hidden custom records are outside this view's replacement scope."""
    if not project.original_mode:
        return rows
    api = sys.modules[type(store).__module__]
    read_json, safe_path, validate_map = api.read_json, api.safe_path, api.validate_map
    local = read_json(safe_path(project.path, 'Cfgs/zh-cn/'+table+'.json'), {})
    validate_map(local, table, allow_zero=True)
    keys = set(store.catalog_rows(table)) | set(owned(store, project).get(table, []))
    return {**{k:v for k,v in local.items() if k not in keys}, **rows}


def compact_changes(store, project, changes, api):
    result = dict(changes)
    state = owned(store, project)
    updated = copy.deepcopy(state)
    for relative, data in changes.items():
        match = re.fullmatch(r'Cfgs/zh-cn/([A-Za-z][A-Za-z0-9_]*Cfg)\.json', relative)
        if not match:
            continue
        table = match[1]
        rows = api.validate_map(json.loads(data), table, allow_zero=True)
        native = store.catalog_rows(table)
        if table in ('TalkCfg', 'OptionCfg') and hasattr(store, 'original_dialogue'):
            native = {**native, **store.original_dialogue.rows(table, list(rows))}
        local = api.read_json(api.safe_path(project.path, relative), {})
        api.validate_map(local, table, allow_zero=True)
        additions = set(rows) - set(native) - set(local)
        tracked = (set(state.get(table, [])) | additions) & set(rows)
        if tracked or table in state: updated[table] = sorted(tracked)
        overrides = {k:v for k,v in preserve_rows(store, project, table, rows).items() if v != native.get(k)}
        if not overrides and not (project.path / relative).exists():
            result.pop(relative)
        else:
            result[relative] = api.json_bytes(overrides)
    if updated != state: result[STATE] = api.json_bytes(updated)
    return result
