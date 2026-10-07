"""Persist unfinished audio drafts without replacing existing native/UP exports."""
import copy
import math
import re


def issues(data, audios, talks, valid_id):
    notes = []
    def note(message):
        if message not in notes:
            notes.append(message)
    if not isinstance(data, dict):
        return ['声音设置必须是对象。']
    if data.get('version', 1) != 1:
        note('声音设置版本无效。')
    sfx, bgm = data.get('sfx', {}), data.get('bgm', [])
    if not isinstance(sfx, dict): note('句子音效设置必须是对象。'); sfx = {}
    if not isinstance(bgm, list): note('背景音乐范围必须是列表。'); bgm = []
    def sound(cue, kind, continuing=False):
        if not isinstance(cue, dict): note('声音设置必须是对象。'); return
        ident = cue.get('audioId')
        if not (continuing and type(ident) is int and ident == 0):
            if not valid_id(ident) or str(ident) not in audios:
                note('声音设置引用了不存在的音频，请重新选择。')
            elif kind is not None and (2 if audios[str(ident)].get('type') == 2 else 1) != kind:
                note('请选择音乐类型的 BGM。' if kind == 1 else '请选择音效类型的声音。')
        if 'loop' in cue and not isinstance(cue['loop'], bool): note('声音循环方式无效。')
        volume = cue.get('volume', 1)
        if type(volume) not in (int, float) or not math.isfinite(volume) or not 0 <= volume <= 1:
            note('音量需要在 0 到 1 之间。')
    for ident, cues in sfx.items():
        if not valid_id(ident) or str(ident) not in talks: note('句子音效引用了不存在的对话。')
        if not isinstance(cues, list): note('句子音效必须是列表。'); continue
        if len(cues) > 16: note('同一句音效超过 16 项。')
        for cue in cues: sound(cue, 2)
    native = data.get('nativeAudio', {})
    if not isinstance(native, dict): note('原有背景音乐记录格式无效。'); native = {}
    for ident, audio in native.items():
        if not valid_id(ident) or str(ident) not in talks: note('原有背景音乐引用了不存在的对话。')
        sound({'audioId': audio}, None)
    occupied, groups = set(), set()
    for group in bgm:
        sound(group, 1, True)
        if not isinstance(group, dict): continue
        ident = group.get('id')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', ident) or ident in groups:
            note('背景音乐范围标识无效或重复。')
        if isinstance(ident, str): groups.add(ident)
        members = group.get('talkIds')
        if not isinstance(group.get('loop'), bool): note('请选择背景音乐的循环方式。')
        if not isinstance(members, list): note('请选择背景音乐的范围。'); continue
        if not members: note('请选择背景音乐的范围。')
        safe = {str(i) for i in members if valid_id(i)}
        if len(safe) != len(set(map(str, members))) or any(i not in talks for i in safe):
            note('背景音乐范围包含不存在或无效的对话。')
        if occupied.intersection(safe): note('同一句不能属于两个背景音乐范围，请先替换原范围。')
        occupied.update(safe)
    for field in ('nativeSnapshot', 'upAudio'):
        if field in data and not isinstance(data[field], dict): note(field + ' 音频归属记录格式无效。')
    tracked = data.get('upAudio', {})
    if isinstance(tracked, dict):
        for field in ('effects', 'aliases'):
            if not isinstance(tracked.get(field, {}), dict): note('UP 音频归属记录格式无效。')
    return notes


def save(store, project, data, previous, maps, original_talks, api):
    """Return metadata/CFG changes. A failed derivation leaves submitted CFGs intact."""
    import up_audio
    from native_audio import export
    previous = previous if isinstance(previous, dict) else {}
    draft = {**copy.deepcopy(previous), **copy.deepcopy(data)} if isinstance(data, dict) else copy.deepcopy(data)
    if isinstance(draft, dict):
        for field in ('upAudio', 'nativeSnapshot', 'runtimeVersion'):
            if field in previous: draft[field] = copy.deepcopy(previous[field])
            else: draft.pop(field, None)
    talks = maps.setdefault('TalkCfg.json', {})
    audios = {**store.catalog_rows('AudioCfg'), **maps.get('AudioCfg.json', {})}
    known_talks = set(talks) | set(store.catalog_rows('TalkCfg'))
    known_talks.update(str(i) for i in store.catalog().get('baseTalkIds', []) if api.valid_id(i))
    compile_previous = dict(previous)
    ledger_notes = []
    for field in ('nativeSnapshot', 'upAudio'):
        ledger = previous.get(field, {})
        invalid = not isinstance(ledger, dict) or (field == 'upAudio' and any(not isinstance(ledger.get(k, {}), dict) for k in ('effects', 'aliases')))
        if invalid:
            compile_previous[field] = {}
            ledger_notes.append('既有 ' + field + ' 音频归属记录未完成，已保留原有指令并建立新的归属记录。')
    probe = dict(draft) if isinstance(draft, dict) else draft
    if isinstance(probe, dict):
        for field in ('nativeSnapshot', 'upAudio'):
            if compile_previous.get(field) != previous.get(field): probe[field] = {}
    notes = issues(probe, audios, known_talks, api.valid_id)
    relative = 'StudentAgeStudio/audio-cues.json'
    if notes:
        return {relative: api.json_bytes(draft)}, set(), notes + ['声音草稿已保存；未完成设置沿用原有游戏音频和 UP 配置。']
    cues = {'version': 1, 'sfx': {}, 'bgm': [], **copy.deepcopy(draft)}
    for field in ('nativeSnapshot', 'upAudio'):
        if compile_previous.get(field) != previous.get(field): cues[field] = {}
    previous = compile_previous
    # These are the only TalkCfg fields written by the native/UP audio exporters.
    before = {key: {field: copy.deepcopy(row[field]) for field in ('audio', 'effect') if field in row} for key, row in talks.items()}
    old_local_audios = copy.deepcopy(maps.get('AudioCfg.json', {}))
    local_audios = copy.deepcopy(old_local_audios)
    keys = set(cues['sfx']) | set(cues.get('nativeAudio', {})) | set(previous.get('nativeSnapshot', {})) | set(previous.get('upAudio', {}).get('effects', {}))
    keys.update(str(i) for group in cues['bgm'] for i in group['talkIds'])
    for key in keys:
        if key in talks: talks[key] = copy.deepcopy(talks[key])
    try:
        up_audio.remove_effects(talks, previous.get('upAudio', {}))
        plan = export(cues, previous, talks, original_talks, audios, maps.get('EvtCfg.json', {}), maps.get('OptionCfg.json', {}))
        needs_config = previous.get('upAudio', {}).get('aliases') or any(cue.get('volume', 1) != 1 or not up_audio._exact_float_id(cue['audioId']) for cue in [*cues['bgm'], *(c for values in cues['sfx'].values() for c in values)] if cue.get('audioId'))
        config = api.read_json(api.safe_path(project.path, up_audio.CONFIG), {}) if needs_config else {}
        def referenced(ident):
            def contains(value):
                if isinstance(value, dict): return any(contains(v) for v in value.values())
                if isinstance(value, list): return any(contains(v) for v in value)
                return type(value) in (int, float) and value == ident
            for filename, path in store.cfg_table_files(project).items():
                rows = maps.get(filename) if filename in maps else api.read_json(path, {})
                if filename == 'AudioCfg.json': rows = {k: r for k, r in rows.items() if k != str(ident)}
                if contains(rows): return True
            return any(isinstance(row, dict) and row.get('id') == ident for row in config.get('musics', []))
        compiled = up_audio.compile(cues, previous, talks, audios, local_audios, plan, config,
                                    lambda occupied: store.record_ids.allocate('AudioCfg', {key: {} for key in occupied}), referenced)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        # API/I/O/JSON-read exceptions deliberately propagate. Only in-memory
        # incomplete configuration rolls back its generated fields.
        for key, row in talks.items():
            saved = before[key]
            if {f: row[f] for f in ('audio', 'effect') if f in row} != saved:
                row = talks[key] = dict(row)
                for field in ('audio', 'effect'):
                    if field in saved: row[field] = copy.deepcopy(saved[field])
                    else: row.pop(field, None)
        return {relative: api.json_bytes(draft)}, set(), ['声音草稿已保存，沿用原有游戏音频和 UP 配置：' + str(error)]
    changes, touched = {}, set()
    if local_audios != old_local_audios:
        maps['AudioCfg.json'] = local_audios; touched.add('AudioCfg.json')
    if compiled != config: changes[up_audio.CONFIG] = api.json_bytes(compiled)
    if before != {key: {field: row[field] for field in ('audio', 'effect') if field in row} for key, row in talks.items()}:
        touched.add('TalkCfg.json')
    if cues != previous: changes[relative] = api.json_bytes(cues)
    return changes, touched, ledger_notes
