"""Reconcile disposable condition-folder ownership against native dialogue rows.

Never repair Cfg edges or delete Cfg content here: another editor's current graph
is authoritative. Only the Studio folder record is released when it goes stale.
"""
import copy


def number(value):
    if isinstance(value, bool): return None
    try:
        ident = int(value)
        return ident if str(ident) == str(value) else None
    except (TypeError, ValueError, OverflowError): return None


def ids(value):
    return [ident for item in value for ident in [number(item)] if ident is not None] if isinstance(value, list) else []


def intact(talks, folder):
    parent = number(folder.get('parentTalkId'))
    if str(parent) not in talks: return False
    helpers = [number(folder.get(field)) for field in ('routerId', 'exitId', 'endId')]
    if any(ident is None or ident <= 0 or ident == parent for ident in helpers) or len(set(helpers)) != 3: return False
    for ident in helpers:
        row = talks.get(str(ident))
        if not isinstance(row, dict) or str(row.get('content') or '').strip(): return False
        if any(row.get(field) for field in ('roleIds', 'roles', 'option', 'effect', 'effect2', 'screenEffect', 'highlights', 'miniGame')): return False
    exit_row, end = talks[str(helpers[1])], talks[str(helpers[2])]
    if exit_row.get('check') or ids(exit_row.get('nextTalk2')) or any(end.get(field) for field in ('check', 'nextTalk', 'nextTalk2')): return False
    return all(str(ident) in talks and ident not in helpers for ident in ids(folder.get('talkIds')))


def condition_keys(talks, folders):
    groups, kept = {}, set()
    for key, folder in folders.items():
        if isinstance(folder, dict) and folder.get('kind') == 'condition' and intact(talks, folder):
            groups.setdefault(number(folder.get('parentTalkId')), []).append((key, folder))
    for parent, group in groups.items():
        row = talks[str(parent)]; start = ids(row.get('nextTalk'))
        if len(start) != 1 or any(row.get(field) for field in ('nextTalk2', 'check', 'option', 'miniGame')): continue
        group.sort(key=lambda entry: number(entry[1].get('branchId')) or 0)
        at = next((i for i, (_, folder) in enumerate(group) if number(folder.get('routerId')) == start[0]), None)
        if at is None: continue
        path = []
        for i in range(at, len(group)):
            key, folder = group[i]
            router, exit_row = talks[str(folder['routerId'])], talks[str(folder['exitId'])]
            members, base = ids(folder.get('talkIds')), ids(folder.get('baseNext'))
            continuation = folder.get('continuation') or {}
            kind = continuation.get('kind') if isinstance(continuation, dict) else None
            following = base if kind == 'following' else [number(continuation.get('talkId'))] if kind == 'talk' else ids(continuation.get('targets')) if kind == 'targets' else []
            if ids(router.get('nextTalk')) != [members[0] if members else number(folder['exitId'])] or ids(exit_row.get('nextTalk')) != following: break
            custom = isinstance(folder.get('failureNext'), list)
            if custom:
                expected = ids(folder['failureNext']) or [number(folder['endId'])]
            else:
                expected = [number(group[i + 1][1].get('routerId'))] if i + 1 < len(group) else base or [number(folder['endId'])]
            if ids(router.get('nextTalk2')) != expected: break
            path.append(key)
            # Explicit failure overrides may intentionally bypass later drafts.
            if custom or i == len(group) - 1:
                kept.update(path); path = []
    return kept


def reconcile_branch_folders(talks, folders):
    if not isinstance(folders, dict): return {}, ['格式无效']
    conditions = condition_keys(talks, folders)
    kept, dropped = {}, []
    for key, folder in folders.items():
        if not isinstance(folder, dict) or (folder.get('kind') == 'condition' and key not in conditions): dropped.append(key)
        else: kept[key] = copy.deepcopy(folder)
    return kept, dropped


def warning(dropped):
    return '已忽略 ' + str(len(dropped)) + ' 个与当前对话连接不一致的分支记录；对话正文和实际连接均已保留。'
