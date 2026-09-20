"""Keep native TalkCfg.audio authoritative across editor round trips."""
import copy
from collections import deque


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
    # Compute the music arriving through continuation lines as well as directly
    # adjacent ranges. A 0 or a gap between two ranges of the same track must not
    # turn the next range into a restart. Ambiguous joins keep an entry command.
    planned = {}
    for key, row in talks.items():
        if key in music: value = music[key]
        elif key in native: value = native[key]
        elif cues['sfx'].get(key): value = cues['sfx'][key][0]['audioId']
        elif key in previous.get('nativeSnapshot', {}) and row.get('audio', 0) == previous['nativeSnapshot'][key]: value = 0
        else: value = row.get('audio', 0)
        planned[key] = value
    outgoing, dependents, waiting = {}, {}, {}
    for key, value in planned.items():
        parents = predecessors[key]
        if value:
            outgoing[key] = value if key in music or key in native or audios.get(str(value), {}).get('type') == 1 else None
        elif key in roots or not parents:
            outgoing[key] = None
        else:
            waiting[key] = len(parents)
            for parent in parents: dependents.setdefault(parent, []).append(key)
    queue = deque(outgoing)
    while queue:
        parent = queue.popleft()
        for key in dependents.get(parent, []):
            waiting[key] -= 1
            if waiting[key] == 0:
                arriving = {outgoing[p] for p in predecessors[key]}
                outgoing[key] = next(iter(arriving)) if len(arriving) == 1 else None
                queue.append(key)
    snapshot = {}
    for key in managed | set(previous.get('nativeSnapshot', {})):
        if key not in talks: continue
        value = planned[key]
        if key in music and value:
            parents = predecessors[key]
            if key not in roots and parents and all(outgoing.get(parent) == value for parent in parents): value = 0
        talks[key]['audio'] = value
        snapshot[key] = value
    cues['nativeSnapshot'] = snapshot
