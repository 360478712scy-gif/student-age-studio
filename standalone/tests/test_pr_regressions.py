"""Save consistency and cache boundaries for the resource optimizations."""
import ctypes
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import platform_support
import server
from media_warmup import MediaWarmup
from storage_paths import saved_cache_path


class ResourceRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        env = patch.dict(os.environ, {
            'STUDIO_USER_DATA_ROOT': str(self.root/'user'),
            'STUDIO_DISPLAY_SETTINGS': str(self.root/'display.json'),
            'STUDIO_CACHE_ROOT': str(self.root/'cache'),
            'STUDIO_BACKUP_ROOT': str(self.root/'backups'),
        })
        env.start(); self.addCleanup(env.stop)
        saved_cache_path.cache_clear(); self.addCleanup(saved_cache_path.cache_clear)

    def assert_stale_save_rejected(self):
        store = server.StudioStore(self.root/'Mods', self.root/'Workshop', self.root/'Game',
                                  asset_settings_path=self.root/'folders.json')
        project = store.project(store.create('Save regression')['id'])
        target = project.path/'Cfgs/zh-cn/TalkCfg.json'
        initial = b'{"1":{"id":1,"content":"AAA"}}'
        external = initial.replace(b'AAA', b'BBB')
        target.write_bytes(initial)
        revision = store.revision(project)
        original = target.stat()
        time.sleep(.005)
        target.write_bytes(external)
        os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
        with self.assertRaises(server.ApiError) as caught:
            store.json_save({'projectId': project.id, 'path': 'Cfgs/zh-cn/TalkCfg.json',
                             'text': initial.replace(b'AAA', b'CCC').decode(),
                             'revision': revision, 'raw': True})
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'conflict'))
        self.assertEqual(target.read_bytes(), external)

    def test_external_change_cannot_hide_inside_windows_fingerprint_ttl(self):
        # Control only the Windows API boundary, leaving real revision and save
        # code intact. Advancing ChangeTime must be observed on every read.
        class BasicInfo(ctypes.Structure):
            _fields_ = [('changed', ctypes.c_longlong)]
        class Metadata:
            def __init__(self): self.path = None
            def CreateFileW(self, name, *args): self.path = Path(name); return 1
            def GetFileInformationByHandleEx(self, handle, kind, ptr, size):
                ptr._obj.changed = int.from_bytes(hashlib.sha256(self.path.read_bytes()).digest()[:7], 'big') + 1
                return 1
            def CloseHandle(self, handle): pass
        with patch.object(platform_support, 'sys', SimpleNamespace(platform='win32')), \
             patch.object(platform_support, '_metadata_api', (Metadata(), BasicInfo)):
            self.assert_stale_save_rejected()

    @unittest.skipUnless(sys.platform == 'win32', 'real NTFS ChangeTime requires Windows')
    def test_native_windows_stale_save_preserves_external_change(self):
        self.assert_stale_save_rejected()

    def test_excluded_directory_is_not_scanned_through_ancestor_alias(self):
        actual = self.root/'actual'
        assets = actual/'assets'; excluded = assets/'generated'
        excluded.mkdir(parents=True)
        (excluded/'preview.png').write_bytes(b'generated')
        (assets/'source.png').write_bytes(b'source')
        alias = self.root/'alias'
        try: alias.symlink_to(actual, target_is_directory=True)
        except OSError as error: self.skipTest('Directory symlinks unavailable: '+str(error))
        job = MediaWarmup(SimpleNamespace())
        found = job.files([alias/'assets'], {excluded.resolve()})
        self.assertEqual(set(found), {str((assets/'source.png').resolve())})
        self.assertEqual(job.files([alias/'assets/generated'], {excluded.resolve()}), {})

    def test_durable_write_fsyncs_and_rebuildable_write_can_skip_it(self):
        with patch.object(server.os, 'fsync', wraps=os.fsync) as sync:
            server.atomic_write(self.root/'user.json', b'{"keep":true}')
            self.assertEqual(sync.call_count, 1)
            server.atomic_write(self.root/'index.json', b'{}', fsync=False)
            self.assertEqual(sync.call_count, 1)
        self.assertEqual((self.root/'user.json').read_bytes(), b'{"keep":true}')

    def test_corrupt_warmup_checkpoint_is_recomputed(self):
        store = SimpleNamespace(game=self.root/'Game', asset_catalog=SimpleNamespace(api=server))
        job = MediaWarmup(SimpleNamespace(store=store))
        job.checkpoint(store, 'probe', ['source'], [])
        path = Path(next(iter(job.checkpoints)))
        path.write_bytes(b'{incomplete')
        fresh = MediaWarmup(SimpleNamespace(store=store))
        self.assertIsNone(fresh.checkpoint(store, 'probe', ['source']))
        fresh.checkpoint(store, 'probe', ['source'], [])
        self.assertEqual(MediaWarmup(SimpleNamespace(store=store)).checkpoint(store, 'probe', ['source']), [])

    def test_image_conversion_preserves_exact_alpha(self):
        image = server.Image.new('RGBA', (16, 12), (42, 73, 151, 93))
        raw = io.BytesIO(); image.save(raw, 'PNG')
        result, extension, width, height = server.normalize_image(raw.getvalue())
        with server.Image.open(io.BytesIO(result)) as output:
            self.assertEqual(output.tobytes(), image.tobytes())
        self.assertEqual((extension, width, height), ('.png', 16, 12))


class SharedDialogueDeletionTests(unittest.TestCase):
    """Deleting one event must not remove lines still owned by a survivor."""

    def setUp(self):
        from event_ownership import deletion
        self.deletion = deletion
        talks = {
            '1': {'id': 1, 'nextTalk': [2]},
            '2': {'id': 2, 'nextTalk': []},
            '3': {'id': 3, 'nextTalk': [2]},
        }
        self.events = {'10': {'id': 10, 'talkId': [1]}, '20': {'id': 20, 'talkId': [3]}}
        self.kwargs = dict(talks=talks, options={}, folders={}, previous={})

    def test_shared_continuation_survives_single_event_deletion(self):
        doomed, _ = self.deletion(self.events, removed={'10'}, **self.kwargs)
        self.assertEqual(doomed, {'1'})

    def test_shared_continuation_goes_with_last_owner(self):
        doomed, _ = self.deletion(self.events, removed={'10', '20'}, **self.kwargs)
        self.assertEqual(doomed, {'1', '2', '3'})

    def test_ownerless_line_is_never_cascaded(self):
        kwargs = dict(self.kwargs, talks={**self.kwargs['talks'], '9': {'id': 9}})
        doomed, _ = self.deletion(self.events, removed={'10', '20'}, **kwargs)
        self.assertNotIn('9', doomed)


class TruncatedSaveTests(unittest.TestCase):
    """A full talks map missing rows without declaring them must abort."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        self.store = server.StudioStore(self.root/'Mods', self.root/'Workshop', self.root/'Game')
        self.ident = self.store.create('截断测试')['id']
        self.project = self.store.project(self.ident)
        self.rows = {'9001': {'id': 9001, 'content': '甲'},
                     '9002': {'id': 9002, 'content': '乙'}}
        server.atomic_write(self.project.path/'Cfgs/zh-cn/TalkCfg.json', server.json_bytes(self.rows))

    def test_missing_row_without_declaration_is_rejected(self):
        target = self.project.path/'Cfgs/zh-cn/TalkCfg.json'
        before = target.read_bytes()
        with self.assertRaises(server.ApiError) as caught:
            self.store.save({'projectId': self.ident, 'revision': self.store.revision(self.project),
                             'talks': {'9001': self.rows['9001']}})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(target.read_bytes(), before)

    def test_declared_deletion_still_saves(self):
        self.store.save({'projectId': self.ident, 'revision': self.store.revision(self.project),
                         'talks': {'9001': self.rows['9001']}, 'deletedIds': [9002]})
        self.assertNotIn('9002', server.read_json(self.project.path/'Cfgs/zh-cn/TalkCfg.json', {}))


class RepairBudgetTests(unittest.TestCase):
    """Repair work on huge damaged documents stays bounded."""

    def test_large_repair_stops_after_scaled_budget(self):
        import json as json_module
        lines = ['{']
        for index in range(3000):
            lines.append('"k%05d": "%s"' % (index, 'x' * 2600))
        lines.append('}')
        text = '\n'.join(lines)
        self.assertGreater(len(text.encode()), 6 * 1024 * 1024)
        calls = {'count': 0}
        real_loads = json_module.loads

        def counting(*args, **kwargs):
            calls['count'] += 1
            return real_loads(*args, **kwargs)

        with patch.object(server.json, 'loads', side_effect=counting):
            result = server.analyze_json_text(text, repair=True)
        self.assertFalse(result['valid'])
        expected = min(64, 4 * server.MAX_JSON // max(1, len(text))) + 1
        self.assertLessEqual(calls['count'], expected)
        self.assertLess(calls['count'], 65)

    def test_small_repair_keeps_full_budget(self):
        text = '{\n"a": 1\n"b": 2\n"c": 3\n}'
        result = server.analyze_json_text(text, repair=True)
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['fixes']), 2)


class HashQueueBoundTests(unittest.TestCase):
    """Pixel-hash queue and validation cache stay bounded on huge libraries."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import asset_catalog
        self.asset_catalog = asset_catalog

    def _catalog(self):
        # The server module itself satisfies the backend surface used here
        # (read_json, ApiError, Image, json_bytes, atomic_write).
        return self.asset_catalog.AssetCatalog(store=None, backend=server,
                                               settings_path=self.root/'asset-folders.json')

    def test_pending_queue_evicts_oldest(self):
        catalog = self._catalog()
        folder = self.root/'lib'
        folder.mkdir()
        items = []
        for index in range(60):
            path = folder/f'img{index:04d}.png'
            path.write_bytes(b'\x89PNG\r\n\x1a\n' + bytes([index % 256]) * 16)
            items.append({'_path': path, 'assetId': str(path), 'name': path.name})
        with patch.object(self.asset_catalog, '_HASH_PENDING_CAP', 50):
            catalog._deduplicate_backgrounds(items)
            with catalog._hash_guard:
                self.assertLessEqual(len(catalog._hash_pending), 50)
        # Let the background worker finish its index writes before the
        # temporary directory is removed (Windows cannot rmdir open files).
        deadline = time.time() + 60
        while catalog.hash_progress()['running'] and time.time() < deadline:
            time.sleep(0.05)

    def test_validation_remember_evicts_oldest(self):
        catalog = self._catalog()
        for index in range(5100):
            catalog._remember_validation(('p%d' % index, (1, 2, 3), 'image'), {'size': 1})
        self.assertEqual(len(catalog.validation), 5000)
        self.assertNotIn(('p0', (1, 2, 3), 'image'), catalog.validation)
        self.assertIn(('p5099', (1, 2, 3), 'image'), catalog.validation)


class IdRegistryTests(unittest.TestCase):
    """Server-allocated IDs are published so scaffolds cannot reclaim them."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        self.store = server.StudioStore(self.root/'Mods', self.root/'Workshop', self.root/'Game')
        self.ident = self.store.create('编号测试')['id']

    def test_allocated_id_is_published_as_reserved(self):
        ident = self.store.record_ids.allocate('TalkCfg', {})
        public = self.store.record_ids.public(self.ident)
        self.assertIn(ident, public['reservedIds'])

    def test_saturated_registry_raises_instead_of_hanging(self):
        import record_ids
        ids = self.store.record_ids
        ids.draft_reserved = set(range(1, 200000))
        try:
            with patch.object(record_ids, 'rule', lambda table, owner=None: {'start': 1, 'end': 3, 'step': 1}):
                start = time.time()
                with self.assertRaises(server.ApiError):
                    ids.allocate('NoSuchCfg', {'1': {}, '2': {}, '3': {}})
                self.assertLess(time.time() - start, 30)
        finally:
            del ids.draft_reserved


class SupervisedStartupTests(unittest.TestCase):
    """Starting inside an existing Job continues without our own Job."""

    @unittest.skipUnless(sys.platform == 'win32', 'Windows Job Objects')
    def test_access_denied_falls_back_to_no_job(self):
        import ctypes
        from types import SimpleNamespace
        holder_path = Path(__file__).resolve().parents[2]/'desktop'/'windows'
        sys.path.insert(0, str(holder_path))
        self.addCleanup(sys.path.remove, str(holder_path))
        import child_processes
        closed = []

        def fake_create(*args): return 1234

        def fake_set(*args): return True

        def fake_assign(*args): return False

        def fake_current(): return 5678

        def fake_close(handle):
            closed.append(handle)
            return True

        def fake_in_job(process, job, output): output._obj.value = True; return True

        kernel = SimpleNamespace(IsProcessInJob=fake_in_job, CreateJobObjectW=fake_create, SetInformationJobObject=fake_set,
                                 AssignProcessToJobObject=fake_assign, GetCurrentProcess=fake_current,
                                 CloseHandle=fake_close)
        with patch.object(ctypes, 'WinDLL', return_value=kernel), \
                patch.object(ctypes, 'get_last_error', return_value=5):
            self.assertIsNone(child_processes.own_children())
        self.assertEqual(closed, [1234])


class InstallCacheFallbackTests(unittest.TestCase):
    """An unwritable install directory falls back to the user profile."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root/'blocker').write_bytes(b'not a directory')
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': '',
                                       'LOCALAPPDATA': str(self.root/'local'),
                                       'STUDIO_DISPLAY_SETTINGS': str(self.root/'display.json')})
        env.start(); self.addCleanup(env.stop)
        import storage_paths
        storage_paths._default_cache_usable = None
        self.addCleanup(setattr, storage_paths, '_default_cache_usable', None)
        saved_cache_path.cache_clear(); self.addCleanup(saved_cache_path.cache_clear)

    @unittest.skipUnless(os.name == 'nt', 'Windows install cache layout')
    def test_unwritable_install_cache_uses_user_profile(self):
        import storage_paths
        with patch.object(storage_paths, 'installation_root', return_value=self.root/'blocker'):
            self.assertEqual(storage_paths.cache_root(), self.root/'local'/'StudentAgeStudio'/'Cache')

    @unittest.skipUnless(os.name == 'nt', 'Windows install cache layout')
    def test_writable_install_cache_keeps_existing_path(self):
        import storage_paths
        with patch.object(storage_paths, 'installation_root', return_value=self.root/'app'):
            self.assertEqual(storage_paths.cache_root(), self.root/'app'/'Cache')


class CommitBackupQuotaTests(unittest.TestCase):
    """Per-save snapshots stay bounded no matter how often the user saves."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        self.store = server.StudioStore(self.root/'Mods', self.root/'Workshop', self.root/'Game')
        self.store.commit_warnings = []
        self.ident = self.store.create('配额测试')['id']
        self.project = self.store.project(self.ident)

    def test_only_newest_twenty_commit_backups_survive(self):
        for index in range(22):
            self.store.commit(self.project, {'note.txt': ('第%d次' % index).encode()}, raw=True)
        stamps = sorted(p.name for p in (self.project.path/'StudentAgeStudio/Backups').iterdir() if p.is_dir())
        self.assertEqual(len(stamps), 20)

    def test_stale_pending_backup_is_swept_on_create(self):
        import time
        from backups import ModBackups
        holder = ModBackups(self.store, server, root=str(self.root/'backups'))
        folder = holder.folder(self.project)
        folder.mkdir(parents=True, exist_ok=True)
        stale = folder/'.pending-old'
        stale.mkdir()
        old = time.time() - 25 * 3600
        os.utime(stale, (old, old))
        fresh = folder/'.pending-new'
        fresh.mkdir()
        holder.create({'projectId': self.ident, 'kind': 'manual', 'requestId': 'sweep-test-1'})
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.is_dir())


class CommitRollbackTests(unittest.TestCase):
    """Rollback restores from the on-disk snapshot even when fsync fails."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        self.store = server.StudioStore(self.root/'Mods', self.root/'Workshop', self.root/'Game')
        self.store.commit_warnings = []
        self.ident = self.store.create('回滚测试')['id']
        self.project = self.store.project(self.ident)
        self.files = {name: self.project.path/'Cfgs/zh-cn'/f'{name}.json' for name in ('A', 'B')}
        for path in self.files.values():
            server.atomic_write(path, b'{"v":1}')

    def test_rollback_survives_disk_full(self):
        import errno
        original = {name: path.read_bytes() for name, path in self.files.items()}
        calls = {'count': 0}
        fail_fsync = {'on': False}
        real_replace, real_fsync = server.replace_file, os.fsync

        def fake_replace(source, destination):
            calls['count'] += 1
            # Fail only the commit-phase rename of B (backup/journal renames
            # must succeed so file A is already replaced when it blows up).
            target = Path(destination)
            if target.match('Cfgs/zh-cn/B.json') and 'Backups' not in target.parts:
                fail_fsync['on'] = True
                raise OSError(errno.ENOSPC, 'No space left on device')
            return real_replace(source, destination)

        def fake_fsync(fd):
            if fail_fsync['on']:
                raise OSError(errno.ENOSPC, 'No space left on device')
            return real_fsync(fd)

        with patch.object(server, 'replace_file', side_effect=fake_replace), \
                patch.object(server.os, 'fsync', side_effect=fake_fsync):
            with self.assertRaises(OSError):
                self.store.commit(self.project, {'Cfgs/zh-cn/A.json': b'{"v":2}',
                                                 'Cfgs/zh-cn/B.json': b'{"v":2}'})
        for name, path in self.files.items():
            self.assertEqual(path.read_bytes(), original[name])


if __name__ == '__main__':
    unittest.main()
