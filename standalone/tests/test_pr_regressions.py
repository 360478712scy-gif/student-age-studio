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


if __name__ == '__main__':
    unittest.main()
