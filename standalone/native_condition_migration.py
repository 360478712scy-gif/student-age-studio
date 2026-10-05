"""Repair only Studio's former 4/7, 9001..9006 comparison instructions.

Native condition lists are conjunctions. A comparison that cannot be expressed
exactly by a conjunction stays intact and is reported, never dropped. Values
use the game's finite binary32 domain, including its 0.001f attribute tolerance.
The project-open repair helper selects known condition fields and preserves all
other source bytes through the existing revision-checked backup transaction.
"""
from functools import lru_cache
from collections import OrderedDict
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import threading

VERSION = 1
_SIGN = 0x80000000
_MASK = 0xffffffff
_MAX = struct.unpack('!f', bytes.fromhex('7f7fffff'))[0]
_EPSILON = struct.unpack('!f', struct.pack('!f', 0.001))[0]


def float32(value):
    """Match C#'s double-to-float cast, including finite double overflow."""
    try:
        return struct.unpack('!f', struct.pack('!f', value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def _bits(value):
    return struct.unpack('!I', struct.pack('!f', value))[0]


def _from_bits(bits):
    return struct.unpack('!f', struct.pack('!I', bits))[0]


def successor(value):
    """Next finite binary32 number; None means the greatest finite value."""
    value = float32(value)
    if not math.isfinite(value):
        raise ValueError('threshold must be a finite float')
    if value == _MAX:
        return None
    if value == 0:
        return _from_bits(1)
    return _from_bits(_bits(value) + (1 if value > 0 else -1))


def _predecessor(value):
    if value == -_MAX:
        return None
    if value == 0:
        return _from_bits(_SIGN | 1)
    return _from_bits(_bits(value) + (-1 if value > 0 else 1))


def _ordered(value):
    bits = _bits(value if value else 0.0)
    return (~bits & _MASK) if bits & _SIGN else bits ^ _SIGN


def _from_ordered(key):
    return _from_bits(key ^ _SIGN if key & _SIGN else ~key & _MASK)


def native_attribute_ge(actual, threshold):
    """ConditionerAttr's IsBiggerOrEqual, with binary32 subtraction."""
    return actual >= threshold or abs(float32(actual - threshold)) <= _EPSILON


@lru_cache(maxsize=1024)
def exact_attribute_lower_threshold(target):
    """Find a native tolerant >= threshold whose cutoff is exactly target.

    Native >= is monotone over finite floats. Its highest threshold accepting
    target is found in at most 32 bit-order steps. If it rejects target's
    immediate predecessor, its entire accepted set is precisely >= target.
    Some cutoffs around zero have no native representation because subtraction
    rounds both neighbors to the same value; those must remain unresolved.
    """
    target = float32(target)
    if not math.isfinite(target):
        return None
    low, high = _ordered(target), _ordered(_MAX)
    while low < high:
        middle = (low + high + 1) // 2
        if native_attribute_ge(target, _from_ordered(middle)):
            low = middle
        else:
            high = middle - 1
    threshold = _from_ordered(low)
    before = _predecessor(target)
    if before is None or not native_attribute_ge(before, threshold):
        return threshold
    return None


def is_owned(command):
    return (isinstance(command, list) and len(command) >= 2
            and not isinstance(command[0], bool) and command[0] in (4, 7)
            and not isinstance(command[1], bool)
            and isinstance(command[1], (int, float)) and 9001 <= command[1] <= 9006
            and command[1] == int(command[1]))


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def convert_command(command):
    """Return (native commands, issue); unowned instructions retain identity.

    The issue is None for a successful conversion or an unowned instruction.
    For an unresolved owned instruction, commands contains the original row.
    """
    if not is_owned(command):
        return [command], None
    if (len(command) != 4 or any(not _finite_number(value) for value in command)
            or command[2] != int(command[2]) or not -2147483648 <= command[2] <= 2147483647):
        return [command], 'invalid_owned_comparison'
    family, subtype, ident, raw_threshold = command
    target = float32(raw_threshold)
    less = -1 if family == 7 else 2

    def lower(value):
        threshold = value if family == 7 else exact_attribute_lower_threshold(value)
        return None if threshold is None else [family, 1, ident, threshold]

    def below(value):
        return [family, less, ident, value]

    def impossible():
        # No finite game value is below the least finite float.
        return [below(-_MAX)], None

    # The former runtime rejects a threshold whose float cast is infinite.
    if not math.isfinite(target):
        return impossible()
    after = successor(target)
    if subtype == 9002:
        return [below(target)], None
    if subtype == 9004:
        return ([lower(-_MAX)] if after is None else [below(after)]), None
    if subtype == 9006:
        if target == _MAX:
            return [below(target)], None
        if target != -_MAX:
            return [command], 'native_conjunction_cannot_express_not_equal'
        bound = lower(after)
        return ([bound], None) if bound is not None else ([command], 'native_attribute_cutoff_unrepresentable')
    if subtype == 9003:
        if after is None:
            return impossible()
        bound = lower(after)
    else:
        bound = lower(target)
    if bound is None:
        return [command], 'native_attribute_cutoff_unrepresentable'
    if subtype == 9005 and after is not None:
        return [bound, below(after)], None
    return [bound], None


def migrate_conditions(value):
    """Convert one flat instruction or native AND list without mutating input.

    Returns (value, converted count, issues). Unchanged input keeps identity.
    Each issue names its original command index and retains the full command.
    """
    if not isinstance(value, list):
        return value, 0, []
    flat = is_owned(value)
    commands = [value] if flat else value
    result, issues, converted = [], [], 0
    for index, command in enumerate(commands):
        replacement, reason = convert_command(command)
        if flat and not reason and is_owned(command) and len(replacement) != 1:
            replacement, reason = [command], 'native_single_condition_cannot_express_conjunction'
        if reason:
            issues.append({'index': index, 'reason': reason, 'command': command})
        if is_owned(command) and not reason:
            converted += 1
        result.extend(replacement)
    if not converted:
        return value, 0, issues
    return (result[0] if flat and len(result) == 1 else result), converted, issues


def migrate_row(row, fields=None, *, include_social=False):
    """Normalize only submitted condition fields, copying changed objects only.

    The two Studio social ownership mirrors are part of EvtCfg's contract.
    Callers must opt in for an actual EvtCfg row; an identically named unknown
    field in another table is never inferred to be editor metadata.
    """
    if not isinstance(row, dict):
        return row, 0, []
    if fields is None:
        from condition_library import FIELDS
        fields = FIELDS
    changes, converted, issues = {}, 0, []
    for field in fields:
        if field not in row: continue
        revised, count, found = migrate_conditions(row[field])
        if count: changes[field] = revised; converted += count
        issues.extend(dict(issue, field=field) for issue in found)
    social = row.get('studioSocial')
    if include_social and isinstance(social, dict):
        social_changes = {}
        for field in ('conditions', 'entryConditions'):
            if field not in social: continue
            revised, count, found = migrate_conditions(social[field])
            if count: social_changes[field] = revised; converted += count
            issues.extend(dict(issue, field='studioSocial.' + field) for issue in found)
        if social_changes:
            changes['studioSocial'] = {**social, **social_changes}
    return ({**row, **changes} if changes else row), converted, issues


# These are the spellings written by Studio's former numeric serializers.
# This negative filter scans bytes in C and keeps ordinary large tables out of
# the JSON decoder. A textual occurrence is harmless: semantic field checks
# below still protect dialogue strings, effects and unknown/plugin data.
_CANDIDATE = re.compile(rb'\[\s*[47](?:\.0+)?(?:[eE][+-]?0+)?\s*,\s*(?:900[1-6](?:\.0+)?(?:[eE][+-]?0+)?|9\.00[1-6][eE]\+?0*3)\s*(?:,|\])')
_NUMBER = rb'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?'
_EXPONENT = rb'-?(?:0|[1-9]\d*)(?:\.\d+)?[eE][+-]?\d+'
_EXPONENT_PRESENT = re.compile(rb'[eE][+-]?\d')
_EXPONENT_PAIR = re.compile(rb'\[\s*(?:(?P<a1>' + _EXPONENT + rb')\s*,\s*(?P<b1>' + _NUMBER
                            + rb')|(?P<a2>' + _NUMBER + rb')\s*,\s*(?P<b2>' + _EXPONENT
                            + rb'))\s*(?:,|\])')
_MARKERS = OrderedDict()
_MARKER_LOCK = threading.RLock()
_SAMPLE_LIMIT = 24


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('重复的 JSON 字段')
        result[name] = value
    return result


def _invalid_constant(value):
    raise ValueError('无效 JSON 数值：' + value)


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('JSON 数值超出有限范围')
    return number


_DECODER = json.JSONDecoder(object_pairs_hook=_unique, parse_constant=_invalid_constant, parse_float=_finite_float)


def _has_candidate(raw):
    if _CANDIDATE.search(raw):
        return True
    # Raw JSON may spell the same reserved numbers as 40e-1 / 90010e-1.
    # Only pairs containing an exponent go through numeric interpretation;
    # ordinary pairs never incur Python per-match work.
    if not _EXPONENT_PRESENT.search(raw):
        return False
    for match in _EXPONENT_PAIR.finditer(raw):
        first = float(match['a1'] or match['a2'])
        second = float(match['b1'] or match['b2'])
        if first in (4, 7) and math.isfinite(second) and 9001 <= second <= 9006 and second == int(second):
            return True
    return False


@lru_cache(maxsize=1)
def bundled_fields():
    from condition_library import FIELDS
    base = frozenset(FIELDS)
    schemas = json.loads(Path(__file__).with_name('catalog-schema.json').read_text(encoding='utf-8')).get('schemas', {})
    return {name: base | {field['name'] for field in schema.get('fields', [])
                         if isinstance(field, dict) and field.get('name')
                         and str(field.get('editorType', '')).lower() == 'condition'}
            for name, schema in schemas.items() if isinstance(schema, dict)}


def _condition_edits(text, start, end, value):
    """Only owned command tokens change; every foreign command keeps its bytes."""
    converted, count, issues = migrate_conditions(value)
    if not count:
        return [], 0, issues
    if is_owned(value):
        return [(start, end, json.dumps(converted, ensure_ascii=False, allow_nan=False))], count, issues
    position, edits = start + 1, []
    for command in value:
        while text[position] in ' \t\r\n': position += 1
        begin = position
        _, position = _DECODER.raw_decode(text, position)
        replacements, reason = convert_command(command)
        if is_owned(command) and not reason:
            edits.append((begin, position, ', '.join(json.dumps(row, ensure_ascii=False, allow_nan=False)
                                                    for row in replacements)))
        while text[position] in ' \t\r\n': position += 1
        if text[position] == ',': position += 1
    return edits, count, issues


def _has_owned(value):
    return isinstance(value, list) and (is_owned(value) or any(is_owned(command) for command in value))


def _field_spans(text, start):
    """Locate fields in an object already validated by the C JSON decoder."""
    position = start + 1
    while text[position] in ' \t\r\n': position += 1
    while text[position] != '}':
        field, position = _DECODER.raw_decode(text, position)
        while text[position] in ' \t\r\n': position += 1
        position += 1  # The validated ':' token.
        while text[position] in ' \t\r\n': position += 1
        begin = position
        _, position = _DECODER.raw_decode(text, position)
        yield field, begin, position
        while text[position] in ' \t\r\n': position += 1
        if text[position] == ',': position += 1
        while text[position] in ' \t\r\n': position += 1


def scan_bytes(raw, fields, *, include_social=False):
    """Plan a numbered table repair, parsing one top-level row at a time.

    No table-wide dictionary or separate record index is built. Only changed
    owned commands are serialized; source whitespace, tokens and siblings keep
    their bytes. Invalid structure fails the complete file without returning
    partial changes. Returns (new bytes or None, stats).
    """
    stats = {'converted': 0, 'unresolvedCount': 0, 'unresolved': []}
    if not _has_candidate(raw):
        return None, stats
    text = raw.decode('utf-8-sig')
    position, edits, keys = 0, [], set()

    def space():
        nonlocal position
        while position < len(text) and text[position] in ' \t\r\n': position += 1

    def take(character):
        nonlocal position
        space()
        if text[position:position + 1] != character:
            raise ValueError('配置表结构不完整，预期 ' + character)
        position += 1

    take('{'); space()
    while text[position:position + 1] != '}':
        key, position = _DECODER.raw_decode(text, position)
        if (not isinstance(key, str) or not key.isascii() or not key.isdecimal()
                or str(int(key)) != key or int(key) > 2147483647 or key in keys):
            raise ValueError('配置表编号重复或无效')
        keys.add(key); take(':'); space(); row_start = position
        row, position = _DECODER.raw_decode(text, position)
        if not isinstance(row, dict):
            raise ValueError('配置行必须是 JSON 对象')
        if key == '0' and (row.get('id') != 0 or isinstance(row.get('id'), bool)):
            raise ValueError('配置表零号记录无效')
        wanted = {field for field in fields if _has_owned(row.get(field))}
        social = row.get('studioSocial')
        social_wanted = ({field for field in ('conditions', 'entryConditions') if _has_owned(social.get(field))}
                         if include_social and isinstance(social, dict) else set())
        if wanted or social_wanted:
            # The C decoder has already validated the row. Only rows containing
            # owned commands need a second, tiny pass to locate value tokens.
            def append_edits(field, begin, end, value):
                replacements, count, found = _condition_edits(text, begin, end, value)
                edits.extend(replacements); stats['converted'] += count
                stats['unresolvedCount'] += len(found)
                for issue in found[:max(0, _SAMPLE_LIMIT - len(stats['unresolved']))]:
                    stats['unresolved'].append(dict(issue, recordId=key, field=field))
            for field, begin, end in _field_spans(text, row_start):
                if field in wanted:
                    append_edits(field, begin, end, row[field])
                elif field == 'studioSocial' and social_wanted:
                    for nested, nested_begin, nested_end in _field_spans(text, begin):
                        if nested in social_wanted:
                            append_edits('studioSocial.' + nested, nested_begin, nested_end, social[nested])
        space()
        if text[position:position + 1] == '}': break
        take(','); space()
        if text[position:position + 1] == '}':
            raise ValueError('配置表存在结尾逗号')
    take('}'); space()
    if position != len(text):
        raise ValueError('配置表结尾有额外内容')
    if not edits:
        return None, stats
    # Convert character positions to UTF-8 byte positions in bounded chunks.
    # Keep source bytes as memory views and allocate only the final byte output;
    # never duplicate/join an entire large Unicode document.
    chunks, cursor, char_cursor = [], 0, 0
    byte_cursor = 3 if raw.startswith(b'\xef\xbb\xbf') else 0
    source = memoryview(raw)
    def byte_position(target):
        nonlocal char_cursor, byte_cursor
        while char_cursor < target:
            stop = min(target, char_cursor + 65536)
            byte_cursor += len(text[char_cursor:stop].encode('utf-8'))
            char_cursor = stop
        return byte_cursor
    for begin, end, replacement in edits:
        byte_begin, byte_end = byte_position(begin), byte_position(end)
        chunks.extend((source[cursor:byte_begin], replacement.encode('utf-8'))); cursor = byte_end
    chunks.append(source[cursor:])
    return b''.join(chunks), stats


def _marker_path(project):
    from storage_paths import cache_root
    key = hashlib.sha256(str(project.path.resolve()).encode('utf-8')).hexdigest()
    return cache_root() / 'NativeConditions' / ('v' + str(VERSION)) / (key + '.json')


def _load_marker(project):
    key = str(project.path.resolve())
    with _MARKER_LOCK:
        marker = _MARKERS.get(key)
        if marker is None:
            try:
                marker = json.loads(_marker_path(project).read_text(encoding='utf-8'))
            except (OSError, ValueError, UnicodeError):
                marker = {}
            if not isinstance(marker, dict) or marker.get('version') != VERSION or marker.get('project') != key:
                marker = {'version': VERSION, 'project': key, 'files': {}}
            if not isinstance(marker.get('files'), dict): marker['files'] = {}
            _MARKERS[key] = marker
        _MARKERS.move_to_end(key)
        while len(_MARKERS) > 64: _MARKERS.popitem(last=False)
        return marker


def _save_marker(project, marker, api):
    path = _marker_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    api.atomic_write(path, api.json_bytes(marker))
    with _MARKER_LOCK:
        _MARKERS[str(project.path.resolve())] = marker


def repair(store, project_id, api, fields_map=None):
    """Repair before opening a project, never while loading/saving an active draft.

    Capture paths/revision under the store lock, scan outside it, and use the
    existing raw transaction only after checking every scanned fingerprint and
    the live revision again. Raw skips unrelated record-ID graph scans; all
    backups, writer locks, revision guards, atomic replacement and rollback stay.
    """
    from condition_library import FIELDS
    with store.lock:
        project = store.project(project_id)
        if project.readonly:
            return {'warnings': [], 'converted': 0, 'unresolved': [], 'unresolvedCount': 0, 'backup': None}
        expected = store.revision(project)
        paths = dict(store.cfg_table_files(project))
    old = _load_marker(project)
    field_map = bundled_fields() if fields_map is None else fields_map
    marker = {'version': VERSION, 'project': str(project.path.resolve()), 'files': {}}
    changes, scanned, converted, unresolved, unresolved_count, warnings = {}, {}, 0, [], 0, []
    for name, path in paths.items():
        fields = sorted(set(FIELDS) | set(field_map.get(name[:-5], field_map.get(name, ()))))
        include_social = name == 'EvtCfg.json'
        stamp = list(api.file_fingerprint(path))
        entry = old['files'].get(name)
        if (not isinstance(entry, dict) or entry.get('fingerprint') != stamp or entry.get('fields') != fields
                or entry.get('includeSocial', False) != include_social):
            raw = path.read_bytes()
            if list(api.file_fingerprint(path)) != stamp:
                raise api.ApiError('自动修复条件时模组发生变化，请重新打开。', 409, 'conflict')
            scanned[name] = stamp
            try:
                revised, stats = scan_bytes(raw, fields, include_social=True) if include_social else scan_bytes(raw, fields)
                entry = dict(stats, fingerprint=stamp, fields=fields, includeSocial=include_social)
            except (ValueError, UnicodeError, IndexError, TypeError, OverflowError) as error:
                revised = None
                entry = {'fingerprint': stamp, 'fields': fields, 'includeSocial': include_social, 'converted': 0,
                         'unresolved': [], 'unresolvedCount': 0, 'error': str(error)[:120]}
            if revised is not None:
                changes['Cfgs/zh-cn/' + name] = revised
                converted += entry['converted']
        marker['files'][name] = entry
        unresolved_count += entry.get('unresolvedCount', 0)
        unresolved.extend(dict(issue, file=name) for issue in entry.get('unresolved', [])[:max(0, _SAMPLE_LIMIT - len(unresolved))])
        if entry.get('error'):
            warnings.append(name + ' 的自动条件修复未执行，原文件已保留：' + entry['error'])
    backup = None
    with store.lock:
        for name, stamp in scanned.items():
            if list(api.file_fingerprint(paths[name])) != stamp:
                raise api.ApiError('自动修复条件时模组发生变化，请重新打开。', 409, 'conflict')
        if changes:
            if store.revision(project) != expected:
                raise api.ApiError('自动修复条件时模组发生变化，请重新打开。', 409, 'conflict')
            backup = store.commit(project, changes, expected, raw=True)
            for relative, data in changes.items():
                name = Path(relative).name; path = paths[name]
                stamp = list(api.file_fingerprint(path))
                if path.read_bytes() != data or list(api.file_fingerprint(path)) != stamp:
                    raise api.ApiError('条件修复后文件又被修改，请重新打开。', 409, 'conflict')
                marker['files'][name]['fingerprint'] = stamp
        try:
            _save_marker(project, marker, api)
        except (OSError, ValueError):
            # The committed file and backup remain valid. An unwritable cache
            # only means the next open repeats the bounded candidate check.
            warnings.append('条件检查缓存暂时无法写入，下次打开模组会重新检查。')
    if converted:
        warnings.append('已自动将 ' + str(converted) + ' 条旧数值扩展条件转换为原版条件，原文件已备份。')
    if unresolved_count:
        positions = '、'.join(issue['file'] + ' #' + issue['recordId'] + ' ' + issue['field'] for issue in unresolved[:5])
        warnings.append('有 ' + str(unresolved_count) + ' 条旧条件无法在原版中等价表达，已保留原文；请手动改为原版支持的条件。'
                        + ('位置：' + positions + ('等。' if unresolved_count > 5 else '。') if positions else ''))
    return {'warnings': warnings, 'converted': converted, 'unresolved': unresolved,
            'unresolvedCount': unresolved_count, 'backup': backup}


def verified_text_saved(project, path, source_stamp, result_stamp, api):
    """Advance a marker only after the text transaction proves all other bytes."""
    marker = _load_marker(project)
    entry = marker['files'].get(Path(path).name)
    if not isinstance(entry, dict) or entry.get('fingerprint') != list(source_stamp):
        return
    updated = {**marker, 'files': dict(marker['files'])}
    updated['files'][Path(path).name] = {**entry, 'fingerprint': list(result_stamp)}
    try:
        _save_marker(project, updated, api)
    except (OSError, ValueError):
        pass
