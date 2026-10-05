"""Compile editor audio cues into UP's existing 1163 and BetterAudio contracts.

Only exact effects and resource rows recorded by the previous save are owned by
the editor. Other 1163 commands and BetterAudio entries belong to the author.
"""
import copy
import json
import struct
from collections import OrderedDict, deque

CONFIG = 'BetterAudio/BetterAudio.json'
_TEXT_AUDIO_CACHE = OrderedDict()


def _text_audio_key(project, path):
    return (str(path.resolve()), str((project.path / 'StudentAgeStudio/audio-cues.json').resolve()))


def _remember_text_audio(key, stamps):
    _TEXT_AUDIO_CACHE[key] = stamps
    _TEXT_AUDIO_CACHE.move_to_end(key)
    while len(_TEXT_AUDIO_CACHE) > 4: _TEXT_AUDIO_CACHE.popitem(last=False)


def verified_text_saved(project, path, source_stamp, result_stamp, api):
    """Move an audio anchor only to text bytes verified by the transaction."""
    key = _text_audio_key(project, path)
    cached = _TEXT_AUDIO_CACHE.get(key)
    if cached is None or cached[0] != source_stamp: return
    try: cue_stamp = api.file_fingerprint(project.path / 'StudentAgeStudio/audio-cues.json')
    except OSError: return
    if cached[1] == cue_stamp:
        _remember_text_audio(key, (result_stamp, cue_stamp))


def needs_text_compile(project, payload, api):
    """Keep text saves fast; audio edits upgrade legacy cue metadata."""
    if set(payload) - {'projectId', 'revision', 'talkGeneration', 'talkPatch'} or not payload.get('talkPatch'):
        return False
    state_path = project.path / 'StudentAgeStudio/audio-cues.json'
    if not state_path.exists(): return False
    path = project.path / 'Cfgs/zh-cn/TalkCfg.json'
    if not path.exists(): return True
    stamps = (api.file_fingerprint(path), api.file_fingerprint(state_path))
    key = _text_audio_key(project, path)
    if _TEXT_AUDIO_CACHE.get(key) == stamps:
        _TEXT_AUDIO_CACHE.move_to_end(key)
        return False
    state = api.read_json(state_path, {})
    if not isinstance(state, dict): return True
    snapshot = state.get('nativeSnapshot', {})
    if state.get('runtimeVersion') != 1 or not snapshot:
        if (api.file_fingerprint(path), api.file_fingerprint(state_path)) != stamps: return True
        _remember_text_audio(key, stamps)
        return False
    from text_record_save import index
    offsets = index(path, api)
    if offsets is None: return True
    with path.open('rb') as stream:
        for key, expected in snapshot.items():
            if key not in offsets: return True
            start, end = offsets[key]; stream.seek(start)
            if json.loads(stream.read(end - start)).get('audio', 0) != expected: return True
    if (api.file_fingerprint(path), api.file_fingerprint(state_path)) != stamps: return True
    _remember_text_audio(_text_audio_key(project, path), stamps)
    return False


def remap(cues, mapping):
    cues = copy.deepcopy(cues)
    def key(value): return str(mapping.get(str(value), value))
    for field in ('sfx', 'nativeAudio', 'nativeSnapshot'):
        if field in cues: cues[field] = {key(k): v for k, v in cues[field].items()}
    for group in cues.get('bgm', []): group['talkIds'] = [int(key(i)) for i in group['talkIds']]
    tracked = cues.get('upAudio', {})
    if isinstance(tracked, dict) and isinstance(tracked.get('effects'), dict):
        tracked['effects'] = {key(k): v for k, v in tracked['effects'].items()}
    return cues


def remove_effects(talks, previous):
    """Remove one tracked occurrence; never remove commands by their opcode."""
    for key, owned in previous.get('effects', {}).items():
        row = talks.get(key)
        if not row or not isinstance(row.get('effect'), list): continue
        effects = row['effect']
        # Later appended commands must be removed first, including duplicates.
        for record in reversed(owned):
            command = record['command']
            index = record['index']
            matches = [i for i, effect in enumerate(effects) if effect == command]
            occurrence = record['occurrence']
            if index < len(effects) and effects[index] == command and index in matches and matches.index(index) == occurrence:
                effects.pop(index)
            elif occurrence < len(matches):
                effects.pop(matches[occurrence])


def _exact_float_id(ident):
    return struct.unpack('f', struct.pack('f', ident))[0] == ident


def compile(cues, previous, talks, audios, local_audios, plan, config, allocate, referenced=None):
    previous = previous.get('upAudio', {})
    if not isinstance(previous, dict): previous = {}
    tracked = {**previous, 'version': 1, 'effects': {}, 'aliases': {}}
    config = copy.deepcopy(config)
    if not isinstance(config, dict) or not isinstance(config.get('audios', []), list) or not isinstance(config.get('musics', []), list):
        raise ValueError('BetterAudio.json 格式无效，原文件未修改。')
    entries = config.get('audios', [])
    old_aliases = previous.get('aliases', {})
    occupied = set(audios) | {str(e.get('id')) for e in entries + config.get('musics', []) if isinstance(e, dict)}

    def add(key, command):
        talks[key] = copy.deepcopy(talks[key])
        effects = talks[key].get('effect')
        if effects is None:
            effects = talks[key]['effect'] = []
        record = {'command': command, 'index': len(effects),
                  'occurrence': sum(e == command for e in effects)}
        effects.append(command)
        tracked['effects'].setdefault(key, []).append(record)

    def audio_id(ident, volume):
        if volume == 1 and _exact_float_id(ident): return ident
        source = audios.get(str(ident))
        # A confirmed unfinished draft may retain a missing reference. It must
        # still save, and must never manufacture an alias to an unknown file.
        if not isinstance(source, dict): return ident
        token = str(ident) + ':' + str(float(volume))
        if token in tracked['aliases']: return tracked['aliases'][token]['id']
        old = old_aliases.get(token, {})
        key = str(old.get('id', ''))
        match = next((entry for entry in entries if entry == old.get('entry')), None)
        if key in local_audios and local_audios[key] == old.get('row') and match is not None:
            alias = int(key)
        else:
            alias = allocate(occupied)
            if not _exact_float_id(alias): raise ValueError('可用 UP 音频编号超出精确范围。')
            key = str(alias); occupied.add(key)
        row = {**copy.deepcopy(source), 'id': alias}
        # Default playback keeps AudioCfg's native volume. Explicit slider
        # values are absolute, matching the editor's preview, including zero.
        value = volume if volume != 1 else source.get('volumn', 0) or 1
        if value <= 0: value = 1 if volume == 1 else 0
        entry = {'id': alias, 'name': source.get('name', ''), 'audioPath': '',
                 'timelinePath': '', 'volume': min(1, value), 'type': source.get('type', 1)}
        if match is not None and alias == old.get('id'):
            entries[entries.index(match)] = entry
        else: entries.append(entry)
        local_audios[key] = row
        tracked['aliases'][token] = {'id': alias, 'sourceId': ident, 'volume': volume,
                                     'row': copy.deepcopy(row), 'entry': copy.deepcopy(entry)}
        config['audios'] = entries
        return alias

    advanced = {key for key, sig in plan['signatures'].items() if sig[1] is False or sig[2] != 1}
    # A later native BGM needs to release an earlier UP music channel. Pause
    # releases UP's suppression without stopping the independent sound effects.
    possible_up = set(advanced)
    queue = deque(possible_up)
    while queue:
        for key in plan['children'].get(queue.popleft(), []):
            if key not in possible_up: possible_up.add(key); queue.append(key)
    for key, row in talks.items():
        sig = plan['signatures'].get(key)
        if key in advanced:
            parents = plan['predecessors'][key]
            starts = key in plan['roots'] or not parents or any(plan['outgoing'].get(p) != sig for p in parents)
            row['audio'] = 0
            if starts:
                add(key, [1163, 10, audio_id(sig[0], sig[2]), 0 if sig[1] else 1, -1, 0])
        elif row.get('audio') and audios.get(str(row['audio']), {}).get('type') == 1 and key in possible_up:
            add(key, [1163, 99, 1])
        effects = cues.get('sfx', {}).get(key, [])
        native = row.get('audio', 0)
        for index, cue in enumerate(effects):
            if index == 0 and native == cue['audioId'] and cue.get('volume', 1) == 1 and not cue.get('loop'):
                continue
            add(key, [1163, 3, audio_id(cue['audioId'], cue.get('volume', 1)), 2 if cue.get('loop') else 1])

    for token, old in old_aliases.items():
        if token in tracked['aliases'] and tracked['aliases'][token]['id'] == old['id']: continue
        key = str(old['id'])
        if local_audios.get(key) != old.get('row') or old.get('entry') not in entries: continue
        if referenced and referenced(old['id']):
            tracked['aliases']['retained:' + key] = old
            continue
        local_audios.pop(key, None)
        entries.remove(old['entry'])
        config['audios'] = entries
    for key in cues.get('nativeSnapshot', {}):
        if key in talks: cues['nativeSnapshot'][key] = talks[key].get('audio', 0)
    if tracked['effects'] or tracked['aliases'] or previous:
        cues['upAudio'] = tracked
    else:
        cues.pop('upAudio', None)
    cues['runtimeVersion'] = 1
    return config
