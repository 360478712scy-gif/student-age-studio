"""Where the game shows an ending part (EndingData.GetNextPart, SelectJob and the ending view's jumps).

After a part the game shows part id+1 when that row's stage is 0 or the current stage and its conditions pass
(otherwise it tries id+2, id+3 ... while the ids stay consecutive). When no consecutive part follows, a part of
type 1 continues with another unshown type-1 part of the same stage; any other part moves on to the next stage,
where the first matching part in table order is shown, original parts before mod parts. Stages run
2 → 3 → 4 → 45 → 5 → 6 → 7 → 8. Stage 1 starts from the job result, and the game also jumps straight to the
parts named by an ending option (EndingOptionCfg.part) or a blind-date profile (EndingDatingCfg.jump).
"""

STAGES = {2: '大学阶段与职业选择', 3: '婚姻阶段', 4: '职业故事中段', 45: '三十岁催婚', 5: '35 岁之后',
          6: '职业故事后段', 7: '阶段 7', 8: '人生尾声'}
STAGE_ORDER = '2、3、4、45、5、6、7、8'


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _row(rows, ident):
    row = rows.get(str(ident))
    return row if isinstance(row, dict) else None


def jump_targets(options=None, dating=None, jobs=None):
    """Parts the game opens directly: ending options, blind-date profiles and job results."""
    found = set()
    for row in (options or {}).values():
        if isinstance(row, dict):
            found.add(_int(row.get('part')))
    for row in (dating or {}).values():
        if isinstance(row, dict):
            found.add(_int(row.get('jump')))
    for row in (jobs or {}).values():
        for result in (row.get('result') or []) if isinstance(row, dict) else []:
            if isinstance(result, list) and len(result) > 1:
                found.add(_int(result[1]))
    return found - {0}


def _heads(rows, targets):
    """Maps a part id to the first part of the consecutive run the game plays it in."""
    memo = {}

    def head(ident):
        path, current = [], ident
        while current not in memo:
            if current in targets or _row(rows, current - 1) is None:
                memo[current] = current
                break
            path.append(current)
            current -= 1
        start = memo[current]
        for part in reversed(path):
            step, stage = _int(_row(rows, part).get('step')), _int(_row(rows, start).get('step'))
            if step and stage and step != stage:
                start = part
            memo[part] = start
        return memo[ident]
    return head


def problems(local_ids, rows, targets=(), originals=(), places=None):
    """Notes on this mod's ending parts. `rows` holds every part the game loads (original and this mod),
    `targets` the parts opened directly (jump_targets) and `originals` the ids of the game's own parts. Each note
    is {'id', 'problem'} plus 'fix', the field values that solve it, when there is a sure fix. `places`, when
    given, receives a description of when each part without a blocking problem plays."""
    targets = set(targets)
    originals = {_int(v) for v in originals}
    local = {_int(v) for v in local_ids}
    head = _heads(rows, targets)
    # Stages whose original first parts are type 1 keep going to the other type-1 parts; the rest stop at the
    # first matching part, which is an original one whenever it matches.
    other_heads = [row for key, row in rows.items() if isinstance(row, dict) and (_int(key) not in local or _int(key) in originals) and _int(row.get('step'))
                   and head(_int(key)) == _int(key)]
    chained = {_int(row.get('step')) for row in other_heads if _int(row.get('type')) == 1}
    crowded = {_int(row.get('step')) for row in other_heads} - chained

    def blocked(start):
        """Why the first part of a run never appears, or None."""
        stage = _int(_row(rows, start).get('step'))
        if start in targets:
            return None
        if stage == 0:
            return f'阶段为 0（接在上一段后面），但没有编号为 {start - 1} 的上一段，游戏里不会出现。请选择这段结局所在的阶段；如果它是某段结局的后续，把编号改成上一段编号 +1。'
        if stage == 1:
            return '阶段 1 是毕业后职业故事的开头，只由职业结果决定，这段不会被选中。请选择其他阶段。'
        if stage not in STAGES:
            return f'阶段 {stage} 不在游戏的结局流程中（{STAGE_ORDER}），这段不会出现。'
        if stage in chained and _int(_row(rows, start).get('type')) != 1:
            return 'type'
        return None

    found = []
    for key in sorted(local):
        row = _row(rows, key)
        if row is None:
            continue
        start = head(key)
        stage, kind, reason = _int(_row(rows, start).get('step')), _int(row.get('type')), blocked(start)
        if places is not None and not reason:
            places[key] = (f'接在段落 {key - 1} 后面（编号 +1）：播放完上一段、满足前提时接着播放。' if start != key else
                           '由结局选项、相亲名单或职业结果直接跳到这一段，之后按编号 +1 继续。' if key in targets else
                           f'阶段 {stage}（{STAGES[stage]}）的第一段：进入这个阶段、满足前提时播放' + ('，并和同阶段其他人物结局依次出现。' if kind == 1 and stage in chained else '。'))
        if start != key:
            if reason == 'type':
                found.append({'id': key, 'problem': f'接在段落 {start} 后面，那一段的类型不是 1，通常不会出现，所以这段也不会出现。'})
                continue
            if reason:
                found.append({'id': key, 'problem': f'接在段落 {start} 后面，那一段不会出现，所以这段也不会出现。'})
                continue
            following = _row(rows, key + 1)
            if kind != 1 and stage in chained and (following is None or head(key + 1) != start):
                found.append({'id': key, 'fix': {'type': 1}, 'problem': f'这是结局故事的最后一段，类型为 {kind}：播放完后直接进入下一阶段，同阶段其他人物的结局不会再出现。'})
        elif reason == 'type':
            found.append({'id': key, 'fix': {'type': 1}, 'problem': f'类型为 {kind}：这个阶段先播放游戏原有的人物结局，之后只继续寻找类型为 1 的段落，所以这段通常不会出现。游戏自带编辑器新建的段落类型为 1。'})
        elif reason:
            found.append({'id': key, 'problem': reason})
        elif key not in targets and key not in originals and stage in crowded:
            found.append({'id': key, 'problem': f'阶段 {stage}（{STAGES[stage]}）只播放第一个满足前提的段落，游戏原有段落排在前面：只有它们都不满足前提时，这段才会出现。'})
    return found


def check(store, payload, api):
    """Notes for a mod's ending parts. `rows`, when given, are the editor's unsaved rows of this mod."""
    with store.lock:
        project = store.project(payload.get('projectId'))

        def table(name):
            local = api.read_json(api.safe_path(project.path, 'Cfgs/zh-cn/' + name + '.json'), {})
            return store.catalog_rows(name), local if isinstance(local, dict) else {}
        original, saved = table('EndingPartCfg')
        local = payload.get('rows') if isinstance(payload.get('rows'), dict) else saved
        linked = {name: {**base, **mine} for name, (base, mine) in ((name, table(name)) for name in ('EndingOptionCfg', 'EndingDatingCfg', 'JobCfg'))}
    targets, places = jump_targets(linked['EndingOptionCfg'], linked['EndingDatingCfg'], linked['JobCfg']), {}
    notes = problems(local.keys(), {**original, **local}, targets, original.keys(), places)
    return {'notes': notes, 'places': {str(key): text for key, text in places.items()}}
