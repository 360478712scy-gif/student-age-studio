"""Chinese display names shared with the browser, without changing resource records."""
import json
import re
from pathlib import Path

_source = Path(__file__).with_name('asset-names.js').read_text(encoding='utf-8')
_labels = json.loads(_source.split('/* ASSET_LABELS_START */', 1)[1].split('/* ASSET_LABELS_END */', 1)[0])

def _text(value):
    return value.strip() if isinstance(value, str) else ''

def _han(value):
    return bool(re.search(r'[\u3400-\u9fff]', value))

def _normalize(value):
    value = re.sub(r'[?#].*$', '', _text(value).replace('\\', '/'))
    value = re.sub(r'^\.?/', '', value)
    value = re.sub(r'^assets/(?:resources/)?', '', value, flags=re.I)
    return re.sub(r'\.(?:png|jpe?g|webp|gif|bmp|wav|ogg|mp3|flac|aac|prefab)$', '', value, flags=re.I).lower()

def _paths(row):
    result = []
    for field in ('url', 'urls', 'assetPath', 'icon', 'icon_xx', 'url2'):
        value = row.get(field)
        for item in value if isinstance(value, list) else [value]:
            path = _normalize(item)
            if path and path not in result:
                result.append(path)
    return result

def _explicit(row):
    if not isinstance(row, dict):
        return ''
    name = _text(row.get('name')) or _text(row.get('title'))
    if not name:
        return ''
    normalized = _normalize(name)
    resources = _paths(row)
    if re.search(r'[\\/]', name) and normalized in resources:
        return ''
    if any(path.startswith('mods/') for path in resources):
        return name
    if not _han(name) and any(normalized in (path, path.rsplit('/', 1)[-1]) for path in resources):
        return ''
    return name

def asset_name_index(records):
    """Index authored names once for a catalogue instead of scanning all rows per card."""
    result = {}
    for position, row in enumerate(records.values() if isinstance(records, dict) else records or []):
        label = _explicit(row)
        if _han(label):
            for resource in _paths(row): result.setdefault(resource, (position, label))
    return result


def asset_name(row, kind, records=None, name_index=None):
    """Return a label for background/cg/audio/portrait; records is a map or list."""
    row = row if isinstance(row, dict) else {}
    given = _explicit(row)
    if given:
        return given
    resources = _paths(row)
    if name_index is not None:
        matches = [name_index[path] for path in resources if path in name_index]
        if matches: return min(matches)[1]
    else:
        values = records.values() if isinstance(records, dict) else records or []
        for other in values:
            label = _explicit(other)
            if _han(label) and any(path in resources for path in _paths(other)):
                return label
    labels = _labels.get(kind, {})
    for resource in resources:
        stem = resource.rsplit('/', 1)[-1]
        if resource in labels or stem in labels:
            return labels.get(resource) or labels[stem]
        if kind == 'audio':
            voice = re.search(r'(?:^|/)npc/(xx_)?([a-z]+)_(greeting|talk|bye)(?:_(\d+))?$', resource)
            if voice and voice[2] in _labels['speakers']:
                return ('小学 · ' if voice[1] else '') + _labels['speakers'][voice[2]] + ' · ' + _labels['voiceActions'][voice[3]] + (' ' + str(int(voice[4])) if voice[4] else '')
            numbered = re.match(r'^(.*?)[_-]?(\d+)$', stem)
            if numbered and numbered[1] in labels:
                return labels[numbered[1]] + ' ' + str(int(numbered[2]))
        if _han(stem):
            return stem
    kind_name = ('背景音乐' if row.get('type') in (1, '1') else '音效') if kind == 'audio' else {'background':'场景', 'cg':'插画', 'portrait':'人物立绘'}.get(kind, '素材')
    identifier = row.get('id')
    return kind_name + (' ' + str(identifier) if identifier is not None and str(identifier) else '（未命名）')
