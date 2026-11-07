"""Explicit repair of stale native asset package prefixes, without reformatting JSON.

Only known asset fields and files physically present inside this mod qualify.
Cross-mod references in dependency-bearing mods are deliberately left for review.
"""
import json
import re
from pathlib import PurePosixPath

FIELDS = {
    'BgCfg.json': {'url'}, 'CGCfg.json': {'urls'},
    'ModFaceCfg.json': {'icon', 'icon_xx'}, 'PersonCfg.json': {'url', 'url2'},
    'KZoneContentCfg.json': {'imgs'}, 'KZoneAvatarCfg.json': {'icon'},
    'ItemCfg.json': {'icon'}, 'AudioCfg.json': {'url'},
}
STRING = re.compile(r'"(?:[^"\\]|\\.)*"', re.S)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('重复 JSON 键，无法安全修复素材路径')
        result[key] = value
    return result


def rewrite(raw, filename, package, exists, *, old_package=None, dependencies=False):
    """Return (patched bytes or None, number of changed asset values).

    exists accepts a safe relative Textures/Audios path. An explicit old_package
    is used only when the editor itself changes that known local package ID.
    """
    fields = FIELDS.get(filename)
    if not fields or not isinstance(package, str) or not package or any(c in package for c in '/\\'):
        return None, 0
    if dependencies and old_package is None: return None, 0
    text = raw.decode('utf-8-sig')
    rows = json.loads(text, object_pairs_hook=_object)
    if not isinstance(rows, dict): return None, 0
    replacements = {}
    for row in rows.values():
        if not isinstance(row, dict): continue
        for field in fields:
            value = row.get(field)
            values = value if isinstance(value, list) else [value]
            for value in values:
                if not isinstance(value, str): continue
                normalized = value.replace('\\', '/')
                parts = normalized.split('/', 2)
                if len(parts) != 3 or parts[0].casefold() != 'mods': continue
                if parts[1].casefold() == package.casefold(): continue
                if old_package is not None and parts[1].casefold() != old_package.casefold(): continue
                relative = parts[2]
                path = PurePosixPath(relative)
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0].casefold() not in {'textures', 'audios'}: continue
                if not exists(relative): continue
                separator = '\\' if '\\' in value else '/'
                replacements[value] = separator.join((parts[0], package, parts[2].replace('/', separator)))
    if not replacements: return None, 0
    # Walk validated JSON tokens to target only top-level row asset fields, never
    # dialogue text, unknown metadata, object keys, or same-looking nested data.
    decoder = json.JSONDecoder()
    from native_condition_migration import _field_spans
    edits = []
    start = len(text) - len(text.lstrip())
    for _, row_start, row_end in _field_spans(text, start):
        if text[row_start] != '{': continue
        for field, begin, end in _field_spans(text, row_start):
            if field not in fields: continue
            value = decoder.raw_decode(text, begin)[0]
            if not isinstance(value, (str, list)) or (isinstance(value, list) and not all(isinstance(item, str) for item in value)): continue
            for match in STRING.finditer(text, begin, end):
                original = json.loads(match.group())
                if original in replacements:
                    edits.append((match.start(), match.end(), json.dumps(replacements[original], ensure_ascii=False)))
    if not edits: return None, 0
    chunks, cursor = [], 0
    for begin, end, replacement in edits:
        chunks.extend((text[cursor:begin], replacement))
        cursor = end
    chunks.append(text[cursor:])
    return (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + ''.join(chunks).encode('utf-8'), len(edits)


def existing_asset(store, project, relative):
    try:
        path = store.mod_image_path(project, relative)
        # Check containment again even for exact-match paths and symbolic links.
        return path.resolve().is_relative_to(project.path.resolve()) and path.is_file() and path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}
    except (OSError, ValueError):
        return False
