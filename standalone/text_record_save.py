"""A verified text-only transaction: parse changed rows, preserve all other bytes.

Cold indexing validates the original object once. Cache validity uses real file
fingerprints, including Windows ChangeTime; it is never time based. Atomic file
replacement and backups still copy bytes, but never decode unchanged records.
"""
import json
from collections import OrderedDict

_CACHE = OrderedDict()


def index(path, api):
    stamp = api.file_fingerprint(path)
    key = str(path.resolve())
    cached = _CACHE.get(key)
    if cached and cached[0] == stamp:
        _CACHE.move_to_end(key)
        return cached[1]
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig')
    decoder = json.JSONDecoder()
    p = 0; byte_cursor = len(raw) - len(text.encode('utf-8')); char_cursor = 0; rows = {}
    def space():
        nonlocal p
        while p < len(text) and text[p].isspace(): p += 1
    space()
    if text[p:p+1] != '{': return None
    p += 1; space()
    while text[p:p+1] != '}':
        name, p = decoder.raw_decode(text, p); space()
        if not isinstance(name, str) or name in rows or text[p:p+1] != ':': return None
        p += 1; space(); start = p
        row, p = decoder.raw_decode(text, p)
        if not isinstance(row, dict) or type(row.get('id')) is not int or str(row['id']) != name: return None
        byte_cursor += len(text[char_cursor:start].encode('utf-8'))
        end = byte_cursor + len(text[start:p].encode('utf-8'))
        rows[name] = (byte_cursor, end)
        byte_cursor = end; char_cursor = p; space()
        if text[p:p+1] == '}': break
        if text[p:p+1] != ',': return None
        p += 1; space()
    p += 1; space()
    if p != len(text) or api.file_fingerprint(path) != stamp: return None
    _CACHE[key] = (stamp, rows)
    while len(_CACHE)>4: _CACHE.popitem(last=False)
    return rows


def save(store, project, payload, api):
    if project.original_mode or set(payload) - {'projectId','revision','talkGeneration','talkPatch'}:
        return None
    patch = payload.get('talkPatch')
    if not isinstance(patch, dict) or set(patch) != {'version','upsert','deleted'} or type(patch.get('version')) is not int or patch['version'] != 1 or patch.get('deleted') != []:
        return None
    changes = patch.get('upsert')
    if not isinstance(changes, dict) or not changes: return None
    api.validate_map(changes, 'TalkCfg.json', allow_zero=True)
    path = api.safe_path(project.path, 'Cfgs/zh-cn/TalkCfg.json')
    if not path.is_file() or path.stat().st_size > api.MAX_JSON: return None
    try: offsets = index(path, api)
    except (ValueError, UnicodeError, IndexError): return None
    if not offsets or any(k not in offsets for k in changes): return None
    replacements = {}
    with path.open('rb') as stream:
        for key, row in changes.items():
            start, end = offsets[key]; stream.seek(start)
            old = json.loads(stream.read(end-start))
            if not isinstance(row.get('content'), str) or row.get('roleName') == '': return None
            if {k:v for k,v in row.items() if k!='content'} != {k:v for k,v in old.items() if k!='content'}: return None
            if row == old: continue
            # Preserve unknown fields/numeric tokens inside this row too.
            # Only the content token is replaced, never reserialize its siblings.
            original = None
            stream.seek(start); original = stream.read(end-start).decode('utf-8')
            decoder=json.JSONDecoder(); pos=1; content_range=None
            while pos<len(original):
                while original[pos].isspace():pos+=1
                if original[pos]=='}':break
                field,pos=decoder.raw_decode(original,pos)
                while original[pos].isspace():pos+=1
                pos+=1
                while original[pos].isspace():pos+=1
                begin=pos;_,pos=decoder.raw_decode(original,pos)
                if field=='content':content_range=(begin,pos)
                while original[pos].isspace():pos+=1
                if original[pos]==',':pos+=1
            if content_range is None: return None
            a,b=content_range
            replacements[key]=(original[:a]+json.dumps(row['content'],ensure_ascii=False,allow_nan=False)+original[b:]).encode('utf-8')
    if not replacements: return None
    # Existing IDs and every field except content were verified above. The private
    # flag skips only ID scanning; every transaction guard remains enabled.
    raw = path.read_bytes(); chunks=[]; cursor=0; new_offsets={}; shift=0
    for key,(start,end) in offsets.items():
        body=replacements.get(key)
        new_offsets[key]=(start+shift,end+shift+(len(body)-(end-start) if body is not None else 0))
        if body is not None:
            chunks.extend((raw[cursor:start],body));cursor=end;shift+=len(body)-(end-start)
    chunks.append(raw[cursor:]);result=b''.join(chunks)
    backup=store.commit(project, {'Cfgs/zh-cn/TalkCfg.json':result}, payload['revision'],_verified_text_only=True)
    stamp=api.file_fingerprint(path)
    if path.read_bytes()==result and api.file_fingerprint(path)==stamp:
        _CACHE[str(path.resolve())]=(stamp,new_offsets)
    else:
        _CACHE.pop(str(path.resolve()),None)
    revision=store.revision(project)
    advanced=store.talk_segments.saved(project,payload.get('talkGeneration'),revision,story_saved=True) if 'talkGeneration' in payload else None
    return dict(ok=True,revision=revision,backup=backup,repairedIds=[],warnings=[],
                **({'talkGenerationAdvanced':advanced} if advanced is not None else {}))
