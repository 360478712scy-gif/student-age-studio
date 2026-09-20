"""Local project loading policy and cleanup of disposable editor caches only."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import re
import shutil
import threading

from storage_paths import auxiliary_cache, cache_root, game_cache


def project_id(path, readonly=True):
    return ('workshop:' if readonly else 'local:') + hashlib.sha256(str(path).encode()).hexdigest()[:24]


def under(path, roots):
    # Lexical comparison: ignored source directories must not be stat'ed/resolved.
    value = os.path.normcase(os.path.abspath(path))
    return any(value == root or value.startswith(root + os.sep) for root in roots)


class ProjectSettingsBusy(Exception):
    pass


class RequestGate:
    """Ordinary requests remain concurrent; a policy change drains them first."""
    def __init__(self):
        self.condition = threading.Condition()
        self.readers = 0
        self.writer = False

    @contextmanager
    def access(self, exclusive=False):
        with self.condition:
            if exclusive:
                self.condition.wait_for(lambda: not self.writer)
                self.writer = True
                if not self.condition.wait_for(lambda: self.readers == 0, timeout=20):
                    self.writer = False
                    self.condition.notify_all()
                    raise ProjectSettingsBusy('还有文件正在读取，请稍后重试。')
            else:
                self.condition.wait_for(lambda: not self.writer)
                self.readers += 1
        try:
            yield
        finally:
            with self.condition:
                if exclusive: self.writer = False
                else: self.readers -= 1
                self.condition.notify_all()


class ProjectPreferences:
    def __init__(self, store, api):
        self.store, self.api = store, api
        self.path = store.asset_catalog.settings_path.with_name('project-preferences.json')
        self.saved = api.read_json(self.path, {})
        if not isinstance(self.saved, dict): raise api.ApiError('模组读取设置损坏，原文件已保留。', 422)
        self.ignored = {}
        for row in self.saved.get('ignoredProjects', []):
            if not isinstance(row, dict) or not isinstance(row.get('path'), str): continue
            path = Path(row['path'])
            if path.is_absolute() and row.get('id') == project_id(path):
                self.ignored[row['id']] = row
        self._refresh_roots()

    def _refresh_roots(self):
        self.roots = {os.path.normcase(os.path.abspath(r['path'])) for r in self.ignored.values()}

    def blocked(self, path):
        return under(path, self.roots)

    def public(self):
        rows = [p.public() for p in self.store.projects()]
        # Only retain lightweight labels so ignored mods can be re-enabled.
        rows += [dict(row, readOnly=True, source='workshop', ignored=True) for row in self.ignored.values()
                 if Path(row['path']).parent == self.store.workshop]
        return {'projects': rows, 'ignoredProjectIds': list(self.ignored),
                'defaultProjectId': self.saved.get('defaultProjectId', '')}

    def prepare(self, payload):
        if not isinstance(payload, dict): raise self.api.ApiError('模组设置无效。')
        ids = payload.get('ignoredProjectIds', list(self.ignored))
        if not isinstance(ids, list) or len(ids) > 10000 or any(not isinstance(i, str) for i in ids):
            raise self.api.ApiError('请选择要忽略的订阅模组。')
        available = {p.id: p for p in self.store.projects()}
        ignored = {}
        for ident in dict.fromkeys(ids):
            if ident in self.ignored: ignored[ident] = self.ignored[ident]; continue
            p = available.get(ident)
            if not p or not p.readonly: raise self.api.ApiError('只能忽略已发现的订阅模组。')
            ignored[ident] = {'id': p.id, 'path': str(p.path), 'name': p.name, 'packageId': p.package}
        default = payload.get('defaultProjectId', self.saved.get('defaultProjectId', ''))
        if not isinstance(default, str): raise self.api.ApiError('默认模组无效。')
        if default in ignored: default = ''
        if default and default != self.saved.get('defaultProjectId') and default not in available and default not in self.ignored:
            raise self.api.ApiError('默认模组不存在，请刷新列表。')
        return dict(self.saved, ignoredProjects=list(ignored.values()), defaultProjectId=default), ignored

    def apply(self, saved, ignored):
        cleanup = bool(set(ignored) - set(self.ignored)) or self.saved.get('cleanupPending', False)
        saved = dict(saved, cleanupPending=cleanup)
        self.api.atomic_write(self.path, self.api.json_bytes(saved))
        self.saved, self.ignored = saved, ignored
        self._refresh_roots()
        if cleanup: self.purge()
        else: self.store.projects()
        self.saved.pop('cleanupPending', None)
        self.api.atomic_write(self.path, self.api.json_bytes(self.saved))

    def _cache(self, path):
        try: value = self.api.read_json(path, {})
        except (OSError, self.api.ApiError, ValueError): return {}
        return value if isinstance(value, dict) else {}

    def purge(self):
        """Caller drains HTTP, warmer and hashing before deleting derived data."""
        store, api = self.store, self.api
        with store.lock:
            store._project_paths = {k:p for k,p in store._project_paths.items() if k not in self.ignored}
            store._project_metadata = {k:v for k,v in store._project_metadata.items() if not self.blocked(k)}
            for cache in (store._revision_cache, store._revision_file_digests, store._portrait_person_cache,
                          store._workshop_tables, store.record_ids.cache, store.conditions.mod_cache,
                          store.conditions.table_cache):
                # These bounded caches are disposable. Clearing avoids retaining nested rows from ignored mods.
                cache.clear()
            store.asset_catalog.cache.clear()
            with store.asset_catalog._validation_guard:
                store.asset_catalog.validation = type(store.asset_catalog.validation)(
                    (k,v) for k,v in store.asset_catalog.validation.items() if not self.blocked(k[0]))
            for key, generation in list(store.talk_segments.generations.items()):
                if self.blocked(generation.identity['path']):
                    generation.close(); del store.talk_segments.generations[key]
            segments = cache_root() / 'TalkSegments/v1'
            if segments.is_dir():
                for folder in segments.iterdir():
                    if folder.is_symlink() or not re.fullmatch('[0-9a-f]{32}', folder.name): continue
                    try: identity = self._cache(folder/'index.json').get('identity', {})
                    except (OSError, api.ApiError): continue
                    if self.blocked(identity.get('path', '')): shutil.rmtree(folder)
            asset = store.asset_catalog
            with asset._hash_guard:
                for name in ('image_hashes', '_hash_pending'):
                    cache = getattr(asset, name)
                    for key in list(cache):
                        if self.blocked(key[0]): del cache[key]
                index = asset.hash_index if asset.hash_index is not None else self._cache(asset.hash_index_path)
                asset.hash_index = {k:v for k,v in index.items() if not self.blocked(k)}
                api.atomic_write(asset.hash_index_path, api.json_bytes(asset.hash_index), fsync=False)
            watch = getattr(asset, '_directory_watch_cache', {})
            for key in list(watch):
                if self.blocked(key): del watch[key]
            manifest = auxiliary_cache(asset.settings_path.parent, 'AssetCache/media-warmup-v1.json')
            entries = self._cache(manifest)
            preview_root = auxiliary_cache(asset.settings_path.parent, 'PreviewCache').resolve()
            keep_previews = {str(Path(output)) for path,row in entries.items()
                             if not self.blocked(path) and isinstance(row,dict) for output in row.get('outputs', [])}
            for path, row in list(entries.items()):
                if not self.blocked(path): continue
                for output in (row.get('outputs', []) if isinstance(row, dict) else []):
                    target = Path(output)
                    if target.parent.resolve() == preview_root and re.fullmatch('[0-9a-f]{64}\\.webp', target.name): target.unlink(missing_ok=True)
                del entries[path]
            api.atomic_write(manifest, api.json_bytes(entries), fsync=False)
            attempts = game_cache(store.game)/'warmup-attempts-v1.json'
            data = self._cache(attempts)
            api.atomic_write(attempts, api.json_bytes({k:v for k,v in data.items() if not (k.startswith('file:') and self.blocked(k[5:]))}), fsync=False)
            # Preserve indexed previews from other mods. Legacy on-demand files
            # without source attribution are disposable and will be rebuilt.
            for folder, pattern in ((preview_root, '*.webp'),
                    (game_cache(store.game)/'headshot-cache', '*.png'),
                    (auxiliary_cache(asset.settings_path.parent,'AssetCache/talk-heads'), '*.png')):
                if folder.is_dir() and not folder.is_symlink():
                    for p in folder.glob(pattern):
                        if str(p) not in keep_previews and re.fullmatch('[0-9a-f]{64}\\.(webp|png)', p.name): p.unlink(missing_ok=True)
            store.projects()  # Persist a path index without the ignored metadata.


def update(server, payload):
    policy = server.store.project_preferences
    saved, ignored = policy.prepare(payload)
    if ignored == policy.ignored and not policy.saved.get('cleanupPending'):
        server.store.asset_catalog.api.atomic_write(policy.path, server.store.asset_catalog.api.json_bytes(saved))
        policy.saved = saved
        return policy.public()
    warmer = server.media_warmup
    was_started = warmer.thread is not None
    warmer.close()
    if warmer.thread and warmer.thread.is_alive(): warmer.thread.join(timeout=10)
    if warmer.thread and warmer.thread.is_alive():
        raise server.store.asset_catalog.api.ApiError('后台素材任务正在结束，请稍后再次应用。', 409, 'busy')
    asset = server.store.asset_catalog
    with asset._hash_guard: asset._hash_pending.clear()
    thread = getattr(asset, '_hash_thread', None)
    if thread and thread.is_alive(): thread.join(timeout=10)
    if thread and thread.is_alive():
        raise server.store.asset_catalog.api.ApiError('图片索引正在结束，请稍后再次应用。', 409, 'busy')
    try:
        policy.apply(saved, ignored)
    finally:
        from media_warmup import MediaWarmup
        server.media_warmup = MediaWarmup(server)
        if was_started: server.media_warmup.start()
    return policy.public()
