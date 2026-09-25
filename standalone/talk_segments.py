"""Immutable dialogue pages. Never writes a Mod or owns drafts.

The old loader remains the semantic oracle during cold construction. Warm reads
seek complete UTF-8 records in a disposable generation, not in the source file.
Only the authenticated server selects source paths; clients pass opaque tokens.
"""
import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import uuid
from decimal import Decimal

from platform_support import file_fingerprint

VERSION = 1
PAGE_SIZE = 100
MAX_PAGE_BYTES = 2 * 1024 * 1024



def packed_summaries(summaries):
    """Wire form of the talk summaries (tens of MB on large mods, parsed by WebView2 on every open).
    Field lists repeat, so each distinct list is sent once in fieldSets and referenced by index.
    Records omit values equal to recordDefaults (the most common value of each field); the client
    restores them, so a record is still every field except content. truthyFields has no consumer."""
    sets, index, packed, counts = [], {}, {}, {}
    for summary in summaries.values():
        for field, value in summary['record'].items():
            encoded = json.dumps(value, sort_keys=True, ensure_ascii=False)
            bucket = counts.setdefault(field, {})
            bucket[encoded] = bucket.get(encoded, 0) + 1
    defaults = {field: json.loads(max(bucket.items(), key=lambda item: item[1])[0]) for field, bucket in counts.items()}
    encoded_defaults = {field: json.dumps(value, sort_keys=True, ensure_ascii=False) for field, value in defaults.items()}
    for key, summary in summaries.items():
        fields = tuple(summary['fields'])
        if fields not in index:
            index[fields] = len(sets)
            sets.append(list(fields))
        record = {field: copy.deepcopy(value) for field, value in summary['record'].items()
                  if field == 'id' or json.dumps(value, sort_keys=True, ensure_ascii=False) != encoded_defaults[field]}
        packed[key] = {'record': record, 'excerpt': summary['excerpt'],
                       'hasText': summary['hasText'], 'fieldSet': index[fields]}
    return {'fieldSets': sets, 'recordDefaults': defaults, 'summaries': packed}

class SegmentError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SegmentError('JSON 存在重复键：' + key)
        result[key] = value
    return result


def invalid_constant(value):
    raise SegmentError('JSON 数值无效：' + value)


STRICT = json.JSONDecoder(object_pairs_hook=unique_object, parse_float=Decimal,
                          parse_constant=invalid_constant)


def compact_record(text):
    """Remove only structural whitespace; preserve every token's exact spelling."""
    output = []
    quoted = escaped = False
    for char in text:
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            output.append(char)
        elif char not in ' \r\n\t':
            output.append(char)
    return ''.join(output).encode('utf-8')


def records(raw):
    """Strict top-level record iterator; JSON grammar determines every boundary."""
    text = raw.decode('utf-8-sig')
    pos, seen = 0, set()

    def space():
        nonlocal pos
        while pos < len(text) and text[pos] in ' \t\r\n':
            pos += 1

    def take(char):
        nonlocal pos
        space()
        if pos >= len(text) or text[pos] != char:
            raise SegmentError('对话表结构不完整，预期 ' + char)
        pos += 1

    take('{')
    space()
    if pos < len(text) and text[pos] == '}':
        pos += 1
    else:
        while True:
            space()
            key, pos = STRICT.raw_decode(text, pos)
            if (not isinstance(key, str) or not key.isascii() or not key.isdecimal()
                    or str(int(key)) != key or int(key) > 2147483647 or key in seen):
                raise SegmentError('对话表编号重复或无效')
            seen.add(key)
            if len(seen) > 250000:
                raise SegmentError('对话表记录过多')
            take(':')
            space()
            start = pos
            row, pos = STRICT.raw_decode(text, pos)
            if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] != int(key):
                raise SegmentError('对话表键与行内编号不一致')
            yield key, compact_record(text[start:pos])
            space()
            if pos < len(text) and text[pos] == '}':
                pos += 1
                break
            take(',')
    space()
    if pos != len(text):
        raise SegmentError('对话表结尾存在额外内容')


class Generation:
    """Trusted in-process index plus checked immutable disk records.

    Generations are not restored from an untrusted/partially written manifest.
    A server restart builds a new generation. No cleanup can discard user edits.
    """
    def __init__(self, root, identity, raw, loaded, check):
        self.identity = identity
        self.generation = uuid.uuid4().hex
        self.check = check
        self.entries = {}
        self.summaries = {}
        self.metrics = {'readBytes': 0, 'parsedRows': 0}
        self.search_cache = {}
        self.metadata = copy.deepcopy({k: v for k, v in loaded.items() if k != 'talks'})
        self.event_ids = {key: [] for key in loaded.get('events', {})}
        for key, owners in loaded.get('talkOwners', {}).items():
            for event in owners:
                self.event_ids.setdefault(str(event), []).append(key)
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.building-', dir=root))
        self.path = root / self.generation
        try:
            # Even hidden or deleted local rows must pass strict validation.
            local = dict(records(raw))
            (temporary / 'source.json').write_bytes(raw)
            database = sqlite3.connect(temporary / 'search.sqlite')
            try:
                database.execute('CREATE TABLE search (id TEXT PRIMARY KEY, content TEXT, role_name TEXT)')
                with (temporary / 'records.json').open('wb') as stream:
                    stream.write(b'{\n')
                    for index, (key, row) in enumerate(loaded['talks'].items()):
                        body = local.get(key)
                        if body is None:
                            body = json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
                        # The old loader is the compatibility oracle. Never hide a normalization.
                        if json.loads(body) != row:
                            raise SegmentError('新旧读取结果不一致：' + key)
                        if index:
                            stream.write(b',\n')
                        stream.write(json.dumps(key).encode() + b': ')
                        offset = stream.tell()
                        stream.write(body)
                        self.entries[key] = (offset, len(body), digest(body))
                        self.summaries[key] = {
                            'fields': list(row), 'truthyFields': [field for field, value in row.items() if value or isinstance(value, (list, dict))],
                            'record': {field: copy.deepcopy(value) for field, value in row.items() if field != 'content'},
                            'excerpt': str(row.get('content') or '')[:80],
                            'hasText': bool(str(row.get('content') or '').strip())}
                        speakers = [loaded.get('persons', {}).get(str(ident), {}).get('name')
                                    or ('主角' if ident == 0 else '人物 ' + str(ident))
                                    for ident in (row.get('roleIds') or []) if isinstance(ident, int) and ident >= 0]
                        role_name = row.get('roleName') or '、'.join(speakers) or '旁白'
                        database.execute('INSERT INTO search VALUES (?, ?, ?)',
                                         (key, str(row.get('content') or ''), str(role_name)))
                    stream.write(b'\n}\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                database.commit()
            finally:
                database.close()
            manifest = {'version': VERSION, 'generation': self.generation, 'identity': identity,
                        'sourceDigest': digest(raw), 'entries': self.entries}
            (temporary / 'index.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
            self.check()
            temporary.rename(self.path)
            self.file_identity = file_fingerprint(self.path / 'records.json')
            self.search_identity = file_fingerprint(self.path / 'search.sqlite')
            self.manifest_identity = file_fingerprint(self.path / 'index.json')
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            shutil.rmtree(self.path, ignore_errors=True)
            raise

    def validate(self):
        # This immutable snapshot is the open document/undo base. External disk
        # edits must not prevent reading its untouched pages to finish a draft.
        # Current project identity is checked by get(); live revisions are still
        # checked by save/commit. Building a new snapshot retains self.check().
        if (file_fingerprint(self.path / 'records.json') != self.file_identity
                or file_fingerprint(self.path / 'search.sqlite') != self.search_identity
                or file_fingerprint(self.path / 'index.json') != self.manifest_identity):
            raise SegmentError('分段缓存已变化，请重新载入；已有草稿请保留')

    def descriptor(self):
        self.validate()
        return {**copy.deepcopy(self.metadata), 'segmentedTalks': {
            'version': VERSION, 'generation': self.generation,
            'ids': list(self.entries), 'pageSize': PAGE_SIZE,
            'eventIds': copy.deepcopy(self.event_ids), **copy.deepcopy(self.packed())}}

    def packed(self):
        # Summaries are fixed for this snapshot; pack them once rather than on every project open.
        if getattr(self, '_packed', None) is None:
            self._packed = packed_summaries(self.summaries)
        return self._packed

    def page(self, requested):
        if not isinstance(requested, list) or len(requested) > PAGE_SIZE:
            raise SegmentError('每次最多读取 100 条对话')
        if any(not isinstance(key, str) or key not in self.entries for key in requested):
            # Missing is a distinct error, not an empty successful row.
            raise SegmentError('请求了目录中不存在的对话')
        requested = list(dict.fromkeys(requested))
        self.validate()
        result, used = [], 0
        with (self.path / 'records.json').open('rb') as stream:
            for key in requested:
                offset, length, expected = self.entries[key]
                if result and used + length > MAX_PAGE_BYTES:
                    break
                stream.seek(offset)
                body = stream.read(length)
                if len(body) != length or digest(body) != expected:
                    raise SegmentError('对话缓存区段损坏')
                row = json.loads(body)
                if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] != int(key):
                    raise SegmentError('对话缓存编号不一致')
                result.append([key, body.decode('utf-8')])
                used += length
        self.validate()
        self.metrics['readBytes'] += used
        self.metrics['parsedRows'] += len(result)
        return {'generation': self.generation, 'revision': self.source_state['revision'] if hasattr(self, 'source_state') else self.identity['revision'],
                'rows': result, 'remaining': requested[len(result):],
                'readBytes': used, 'parsedRows': len(result)}

    def search(self, query, offset=0, limit=PAGE_SIZE, content_only=False, body_only=False):
        if not isinstance(query, str) or len(query) > 2000 or type(offset) is not int or offset < 0:
            raise SegmentError('搜索参数无效')
        if type(limit) is not int or not 1 <= limit <= PAGE_SIZE:
            raise SegmentError('搜索页大小无效')
        self.validate()
        uri = (self.path / 'search.sqlite').as_uri() + '?mode=ro'
        cache_key = (query, bool(content_only), bool(body_only))
        if cache_key not in self.search_cache:
            from segment_search import matches
            with closing(sqlite3.connect(uri, uri=True)) as database:
                database.create_function('studio_matches', 3, lambda ident, content, role: matches(query, None if body_only else ident, content, None if content_only or body_only else role))
                rows = database.execute('SELECT id FROM search WHERE studio_matches(id, content, role_name) ORDER BY CAST(id AS INTEGER)').fetchall()
            self.search_cache[cache_key] = [row[0] for row in rows]
            while len(self.search_cache) > 8:
                self.search_cache.pop(next(iter(self.search_cache)))
        found = self.search_cache[cache_key]
        self.validate()
        return {'generation': self.generation, 'ids': found[offset:offset + limit],
                'nextOffset': offset + limit if len(found) > offset + limit else None}

    def close(self):
        shutil.rmtree(self.path, ignore_errors=True)


class SegmentService:
    """Bounded immutable sessions; existing full-table transactions stay intact."""
    def __init__(self, store, backend):
        self.store, self.backend = store, backend
        self.generations = {}
        self.request_context = threading.local()

    def story_fingerprints(self, project):
        # A feature save may change ItemCfg without changing the open story.
        # Track every table the story loader uses, plus all editor metadata.
        from storage_paths import game_cache
        tables = {*self.backend.TABLES.values(), 'AudioCfg.json'}
        paths = [path for path in self.store.revision_paths(project)
                 if not path.relative_to(project.path).as_posix().startswith('Cfgs/') or path.name in tables]
        paths.append(game_cache(self.store.game) / 'game-catalog.json')
        return tuple((str(path), file_fingerprint(path) if path.exists() else None) for path in paths)

    def refresh_revision(self, project_id, token, expected):
        with self.store.lock:
            project = self.store.project(project_id)
            revision = self.store.revision(project)
            result = {'projectId': project.id, 'revision': revision, 'unchangedStory': False}
            generation = self.generations.get(token) if isinstance(token, str) else None
            if (not generation or project.original_mode
                    or generation.identity['path'] != str(project.path.resolve())
                    or generation.identity['originalMode'] != project.original_mode
                    or getattr(generation, 'document_revision', None) != expected):
                return result
            if getattr(generation, 'story_fingerprints', None) != self.story_fingerprints(project):
                return result
            # Do not accept corrupt cache files when advancing an unrelated revision.
            try:
                intact = (file_fingerprint(generation.path / 'records.json') == generation.file_identity
                          and file_fingerprint(generation.path / 'search.sqlite') == generation.search_identity
                          and file_fingerprint(generation.path / 'index.json') == generation.manifest_identity)
            except OSError:
                intact = False
            if not intact: return result
            if self.store.revision(project) != revision:
                raise self.backend.ApiError('检查时模组发生变化，请重试。', 409, 'conflict')
            generation.source_state['revision'] = revision
            generation.document_revision = revision
            result['unchangedStory'] = True
            return result

    def open(self, project_id, original_events=()):
        b = self.backend
        original_events = sorted({str(int(i)) for i in original_events if str(i).isdigit()})
        with self.store.lock:
            project = self.store.project(project_id)
            revision = self.store.revision(project)
            identity = {'path': str(project.path.resolve()), 'revision': revision,
                        'originalMode': project.original_mode, 'language': 'zh-cn', 'version': VERSION,
                        'originalEvents': original_events if project.original_mode else []}
            for token, generation in list(self.generations.items()):
                if generation.identity == identity:
                    try:
                        return generation.descriptor()
                    except (SegmentError, OSError):
                        # Only an explicit reopen rebuilds. A page failure never
                        # silently changes a draft's baseline or generation.
                        self.generations.pop(token).close()
            source = b.safe_path(project.path, 'Cfgs/zh-cn/TalkCfg.json')
            before = file_fingerprint(source) if source.exists() else None
            if source.exists() and source.stat().st_size > b.MAX_JSON:
                raise SegmentError('对话文件过大')
            raw = source.read_bytes() if source.exists() else b'{}'
            # Cold only: the existing loader resolves catalog overrides, retained
            # ownership and audio. No shortened table is ever passed to it.
            loaded = self.store.load(project_id, original_events)
            if loaded.get('unreadableTables', {}).get('talks'):
                raise SegmentError(loaded['unreadableTables']['talks'])

            source_state = {'fingerprint': before, 'revision': revision}
            def check():
                current = self.store.project(project_id)
                if (str(current.path.resolve()) != identity['path']
                        or current.original_mode != identity['originalMode']
                        or (file_fingerprint(source) if source.exists() else None) != source_state['fingerprint']
                        or self.store.revision(current) != source_state['revision']):
                    raise b.ApiError('模组已变化，分段底稿已过期；已有草稿请保留。', 409, 'conflict')

            check()
            from storage_paths import cache_root
            cache = (cache_root() / 'TalkSegments' / 'v1').resolve()
            if cache.is_relative_to(project.path.resolve()):
                raise SegmentError('分段缓存目录不能放在模组内部')
            generation = Generation(cache, identity, raw, loaded, check)
            generation.source_state = source_state
            generation.document_revision = revision
            generation.story_fingerprints = self.story_fingerprints(project)
            check()
            self.generations[generation.generation] = generation
            while len(self.generations) > 4:
                oldest = next(iter(self.generations))
                self.generations.pop(oldest).close()
            return generation.descriptor()

    def get(self, project_id, token):
        generation = self.generations.get(token) if isinstance(token, str) else None
        project = self.store.project(project_id)
        if (not generation or generation.identity['path'] != str(project.path.resolve())
                or generation.identity['originalMode'] != project.original_mode):
            raise self.backend.ApiError('分段底稿已过期，请保留草稿并重新打开。', 409, 'conflict')
        generation.validate()
        return generation

    def saved(self, project, token, revision, *, story_saved=False):
        """Keep a session's immutable undo base readable after its own commit.

        A new open builds a fresh generation. Only this server's successful save
        can advance the guard; an external change always rejects the old token.
        """
        generation = self.generations.get(token) if isinstance(token, str) else None
        if not generation or self.store.revision(project) != revision:
            return False
        source = self.backend.safe_path(project.path, 'Cfgs/zh-cn/TalkCfg.json')
        if story_saved:
            generation.story_fingerprints = self.story_fingerprints(project)
            generation.document_revision = revision
        generation.write_epoch = getattr(generation, 'write_epoch', 0) + 1
        generation.source_state.update(revision=revision,
                                       fingerprint=file_fingerprint(source) if source.exists() else None)
        return True
