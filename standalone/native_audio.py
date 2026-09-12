"""Keep native TalkCfg.audio authoritative across editor round trips."""
import copy


def reconcile(cues, talks):
    cues = copy.deepcopy(cues)
    snapshot = cues.get('nativeSnapshot', {})
    expected = {str(i):g['audioId'] for g in cues.get('bgm', []) for i in g.get('talkIds', [])}
    expected.update({k:v for k,v in cues.get('nativeAudio', {}).items() if k not in expected})
    for key, row in talks.items():
        actual = row.get('audio', 0)
        changed = actual != snapshot[key] if key in snapshot else actual not in (0, expected.get(key, actual))
        if not changed: continue
        # A built-in edit (including clearing music) supersedes stale Studio cues.
        cues.get('sfx', {}).pop(key, None)
        cues.get('nativeAudio', {}).pop(key, None)
        for group in cues.get('bgm', []):
            group['talkIds'] = [i for i in group.get('talkIds', []) if str(i) != key]
    cues['bgm'] = [g for g in cues.get('bgm', []) if g.get('talkIds')]
    return cues


def export(cues, previous, talks, original, audios, events=None, options=None):
    music = {str(i):g['audioId'] for g in cues['bgm'] for i in g['talkIds']}
    native = cues.setdefault('nativeAudio', {})
    managed = set(music) | set(cues['sfx']) | set(native)
    for key in managed:
        old_audio = original.get(key, {}).get('audio', 0)
        kind = audios.get(str(old_audio), {}).get('type')
        if key in cues['sfx'] and key not in music and kind == 1:
            native.setdefault(key, old_audio)
        if key in music:
            native.pop(key, None)
            if kind == 2 and key not in cues['sfx']:
                cues['sfx'][key] = [{'audioId':old_audio,'volume':1}]
    # Native BlackBg stops music whenever this line has audio != 0.
    # Emit a range BGM only at entry/change boundaries, including branch joins.
    predecessors = {key:set() for key in talks}
    for key,row in talks.items():
        targets = list(row.get('nextTalk') or []) + list(row.get('nextTalk2') or [])
        for oid in row.get('option') or []:
            option = (options or {}).get(str(oid), {})
            targets += list(option.get('talkId') or []) + list(option.get('talkId2') or [])
        for target in targets:
            if str(target) in predecessors:predecessors[str(target)].add(key)
    roots = {str(i) for row in (events or {}).values() for i in row.get('talkId') or []}
    if events is None:roots.update(str(g['talkIds'][0]) for g in cues['bgm'] if g['talkIds'])
    snapshot = {}
    for key in managed | set(previous.get('nativeSnapshot', {})):
        if key not in talks: continue
        if key in music:
            parents = predecessors.get(key, set())
            value = 0 if key not in roots and parents and all(music.get(parent) == music[key] for parent in parents) else music[key]
        elif key in native: value = native[key]
        elif cues['sfx'].get(key): value = cues['sfx'][key][0]['audioId']
        elif talks[key].get('audio', 0) == previous.get('nativeSnapshot', {}).get(key): value = 0
        else: value = talks[key].get('audio', 0)
        talks[key]['audio'] = value
        snapshot[key] = value
    cues['nativeSnapshot'] = snapshot
