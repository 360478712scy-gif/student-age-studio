"""Workshop publishing backend: validation, staging, state machine.

Everything runs against an injected fake Steam bridge (no client, no DLL);
only publisher/bridge logic is exercised; no real uploads.
"""
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
import workshop_publish as pub
from workshop_publish import PublishError, Publisher
from steam_bridge import SteamBridge, SteamBridgeError


class FakeBridge:
    """Same surface as SteamBridge; scripted results, records calls."""

    def __init__(self, submit_results=(1,), progress_script=(), create_ids=(7654321,)):
        self.submit_results = list(submit_results)
        self.progress_script = list(progress_script)
        self.create_ids = list(create_ids)
        self.calls = []
        self.created = 0

    def ensure_running(self, game=None):
        self.calls.append(('ensure', game))
        return {'appId': 1991040}

    def create_item(self, timeout=120):
        self.calls.append(('create',))
        self.created += 1
        return self.create_ids[min(self.created - 1, len(self.create_ids) - 1)]

    def start_update(self, file_id):
        self.calls.append(('start_update', file_id))
        return 9000 + file_id % 1000

    def _set(self, name, handle, value):
        self.calls.append((name, handle, value))
        return True

    def set_title(self, handle, value):
        return self._set('title', handle, value)

    def set_description(self, handle, value):
        return self._set('description', handle, value)

    def set_metadata(self, handle, value):
        return self._set('metadata', handle, value)

    def set_visibility(self, handle, value):
        return self._set('visibility', handle, value)

    def set_tags(self, handle, value):
        return self._set('tags', handle, value)

    def set_content(self, handle, value):
        return self._set('content', handle, value)

    def set_preview(self, handle, value):
        return self._set('preview', handle, value)

    def submit_update(self, handle, note, timeout=120, progress=None):
        self.calls.append(('submit', handle, note))
        while progress and self.progress_script:
            progress(self.update_progress(handle))
        return self.submit_results.pop(0) if self.submit_results else 1

    def update_progress(self, handle):
        if self.progress_script:
            status, processed, total = self.progress_script.pop(0)
        else:
            status, processed, total = 5, 100, 100
        self.calls.append(('progress', handle))
        return {'status': status, 'phase': '?', 'processedBytes': processed, 'totalBytes': total}

    def shutdown(self):
        self.calls.append(('shutdown',))

    describe_result = staticmethod(SteamBridge.describe_result)


def make_cover(path, size=(64, 48), fmt='PNG'):
    from PIL import Image
    Image.new('RGB', size, (10, 200, 90)).save(path, format=fmt)


class PublishHarness(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root / 'Cache'),
                                       'STUDIO_USER_DATA_ROOT': str(self.root / 'User'),
                                       'STUDIO_DISPLAY_SETTINGS': str(self.root / 'display.json')})
        env.start()
        self.addCleanup(env.stop)
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game')
        self.ident = self.store.create('发布测试')['id']
        self.project = self.store.project(self.ident)
        manifest = b.read_json(self.project.path / 'manifest.json', {})
        manifest.update({'title': '测试模组', 'description': '简介',
                         'visible': 2, 'tags': ['剧情']})
        b.atomic_write(self.project.path / 'manifest.json', b.json_bytes(manifest))
        make_cover(self.project.path / 'preview.jpg')
        self.api = b
        self.publisher = Publisher()
        self.addCleanup(self.publisher.close)

    def payload(self, **overrides):
        body = {'projectId': self.ident, 'revision': self.store.revision(self.project),
                'changeNote': '测试更新'}
        body.update(overrides)
        return body

    def run_job(self, fake, payload):
        job_id = self.publisher.start(self.store, self.api, payload, bridge=fake)['jobId']
        deadline = time.time() + 60
        while True:
            state = self.publisher.status(job_id)['state']
            if state in ('done', 'error', 'cancelled', 'unconfirmed'):
                return self.publisher.status(job_id)
            self.assertLess(time.time(), deadline, 'job stalled in state ' + state)
            time.sleep(0.05)

    # ---- validation ----

    def test_first_publish_defaults_private_regardless_of_game_manifest_enum(self):
        fields = pub.normalize_payload(self.api, self.project, {'title': 'test', 'visible': 0}, {'changeNote': 'test'})
        self.assertEqual(fields['visibility'], 2)

    def test_title_required_and_bounded(self):
        manifest = b.read_json(self.project.path / 'manifest.json', {})
        manifest['title'] = '   '
        with self.assertRaises(PublishError) as caught:
            pub.normalize_payload(self.api, self.project, manifest, {'changeNote': 'x'})
        self.assertEqual(caught.exception.code, 'publish_title_missing')
        with self.assertRaises(PublishError) as caught:
            pub.normalize_payload(self.api, self.project, manifest, {'title': 'x' * 129, 'changeNote': 'x'})
        self.assertEqual(caught.exception.code, 'publish_title_too_long')

    def test_description_visibility_tags_change_note(self):
        manifest = b.read_json(self.project.path / 'manifest.json', {})
        base = {'title': 't', 'changeNote': 'n'}
        with self.assertRaises(PublishError):
            pub.normalize_payload(self.api, self.project, manifest, {**base, 'description': 'x' * 8001})
        with self.assertRaises(PublishError):
            pub.normalize_payload(self.api, self.project, manifest, {**base, 'visibility': 7})
        with self.assertRaises(PublishError) as caught:
            pub.normalize_payload(self.api, self.project, manifest, {**base, 'tags': ['恐怖']})
        self.assertEqual(caught.exception.code, 'publish_tags_unsupported')
        with self.assertRaises(PublishError):
            pub.normalize_payload(self.api, self.project, manifest, {'title': 't', 'changeNote': '  '})
        fields = pub.normalize_payload(self.api, self.project, manifest,
                                        {'title': '  t  ', 'visibility': 0, 'tags': ['剧情', '其他'],
                                         'changeNote': 'n'})
        self.assertEqual((fields['title'], fields['visibility'], fields['tags']), ('t', 0, ['剧情', '其他']))

    def test_revision_mismatch_rejected_before_thread(self):
        with self.assertRaises(PublishError) as caught:
            self.publisher.start(self.store, self.api, self.payload(revision='stale'))
        self.assertEqual(caught.exception.status, 409)

    def test_workshop_project_rejected(self):
        with self.assertRaises(b.ApiError):
            self.publisher.start(self.store, self.api, {'projectId': 'workshop:dead', 'revision': 'x'})

    def test_preview_traversal_rejected(self):
        with self.assertRaises(PublishError) as caught:
            pub.resolve_preview(self.api, self.project, {}, {'previewPath': '../../outside.png'})
        self.assertEqual(caught.exception.status, 403)

    def test_preview_size_limit(self):
        import random
        from PIL import Image
        big = self.project.path / 'big.png'
        random.seed(1234)
        noise = Image.new('RGB', (1200, 900))
        pixels = noise.load()
        for y in range(900):
            for x in range(1200):
                pixels[x, y] = (random.randrange(256), random.randrange(256), random.randrange(256))
        noise.save(big, format='PNG')
        self.assertGreater(big.stat().st_size, pub.PREVIEW_MAX)
        with self.assertRaises(PublishError) as caught:
            pub.prepare_preview(self.api, big, self.root / 'staged')
        self.assertEqual(caught.exception.code, 'publish_preview_too_large')

    # ---- staging ----

    def test_staging_excludes_private_files(self):
        private = self.project.path / 'StudentAgeStudio'
        (private / 'Backups').mkdir(parents=True)
        (private / 'Backups' / 'full-copy.json').write_bytes(b'{}')
        (private / 'editor-state.json').write_bytes(b'{}')
        (private / 'workshop.json').write_bytes(b'{}')
        (self.project.path / 'notes.tmp').write_bytes(b'x')
        (self.project.path / '.save.lock').write_bytes(b'x')
        (self.project.path / 'Cfgs/zh-cn/TalkCfg.json').write_bytes(b'{}')
        out = self.root / 'staged'
        out.mkdir()
        files, total, skipped = pub.stage_mod(self.api, self.project, out)
        staged = sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file())
        self.assertIn('Cfgs/zh-cn/TalkCfg.json', staged)
        self.assertIn('StudentAgeStudio/editor-state.json', staged)
        self.assertNotIn('StudentAgeStudio/Backups/full-copy.json', staged)
        self.assertNotIn('StudentAgeStudio/workshop.json', staged)
        self.assertFalse(any(name.endswith(('.tmp', '.lock')) for name in staged))
        self.assertTrue(files >= 2 and total > 0 and skipped)

    def test_sidecar_roundtrip(self):
        self.assertEqual(pub.read_sidecar(self.project), {})
        pub.Publisher._write_sidecar(self.api, self.project, 123, {'changeNote': 'n'})
        sidecar = pub.read_sidecar(self.project)
        self.assertEqual(sidecar['publishedFileId'], 123)
        self.assertTrue(sidecar['itemUrl'].endswith('id=123'))

    # ---- state machine ----

    def test_create_and_publish_new_item(self):
        fake = FakeBridge(submit_results=[1], progress_script=[(3, 0, 100), (3, 60, 100), (5, 100, 100)])
        result = self.run_job(fake, self.payload())
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['publishedFileId'], '7654321')
        self.assertTrue(result['itemUrl'].endswith('id=7654321'))
        self.assertEqual(result['percent'], 100)
        kinds = [call[0] for call in fake.calls]
        self.assertIn('create', kinds)
        self.assertIn('submit', kinds)
        sidecar = pub.read_sidecar(self.project)
        self.assertEqual(sidecar['publishedFileId'], 7654321)
        titles = [call[2] for call in fake.calls if call[0] == 'title']
        self.assertEqual(titles, ['测试模组'])

    def test_update_reuses_bound_item(self):
        pub.Publisher._write_sidecar(self.api, self.project, 555, {'changeNote': 'old'})
        fake = FakeBridge(submit_results=[1])
        result = self.run_job(fake, self.payload())
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['publishedFileId'], '555')
        kinds = [call[0] for call in fake.calls]
        self.assertNotIn('create', kinds)
        starts = [call[1] for call in fake.calls if call[0] == 'start_update']
        self.assertEqual(starts, [555])

    def test_deleted_item_never_automatically_recreated(self):
        pub.Publisher._write_sidecar(self.api, self.project, 555, {'changeNote': 'old'})
        fake = FakeBridge(submit_results=[9])
        result = self.run_job(fake, self.payload())
        self.assertEqual(result['error']['code'], 'steam_item_missing')
        self.assertEqual(fake.created, 0)
        self.assertEqual(pub.read_sidecar(self.project)['publishedFileId'], 555)

    def test_submit_failure_reports_steam_message(self):
        fake = FakeBridge(submit_results=[3])
        result = self.run_job(fake, self.payload())
        self.assertEqual(result['state'], 'error')
        self.assertEqual(result['error']['code'], 'steam_submit_failed')
        self.assertIn('网络', result['error']['message'])
        self.assertEqual(pub.read_sidecar(self.project)['publishedFileId'], 7654321)

    def test_timeout_blocks_second_create(self):
        class TimeoutBridge(FakeBridge):
            def create_item(self, timeout=120):
                raise SteamBridgeError('timeout', code='steam_create_timeout')
        result = self.run_job(TimeoutBridge(), self.payload())
        self.assertEqual(result['state'], 'unconfirmed')
        with self.assertRaises(PublishError):
            self.publisher.start(self.store, self.api, self.payload(), bridge=FakeBridge())

    def test_cancel_marks_job_with_note(self):
        gate = threading.Event()
        started = threading.Event()

        class BlockingBridge(FakeBridge):
            def create_item(self, timeout=120):
                started.set()
                self.calls.append(('create',))
                gate.wait(timeout=30)
                return 999

        fake = BlockingBridge(submit_results=[1])
        job_id = self.publisher.start(self.store, self.api, self.payload(), bridge=fake)['jobId']
        self.assertTrue(started.wait(timeout=30))
        cancelled = self.publisher.cancel(job_id)
        self.assertEqual(cancelled['state'], 'cancelling')
        with self.assertRaises(PublishError) as caught:
            self.publisher.start(self.store, self.api, self.payload(), bridge=fake)
        self.assertEqual(caught.exception.code, 'publish_busy')
        report = self.publisher.prereq(self.store, self.api, self.ident)
        self.assertEqual(report['currentJob']['jobId'], job_id)
        self.assertIn('note', cancelled)
        gate.set()
        deadline = time.time() + 30
        while self.publisher.status(job_id)['state'] not in ('done', 'error', 'cancelled', 'unconfirmed'):
            self.assertLess(time.time(), deadline)
            time.sleep(0.05)
        # The blocked Steam call finished first; the worker must not resurrect it.
        self.assertEqual(self.publisher.status(job_id)['state'], 'cancelled')

    def test_unknown_job_and_registry(self):
        self.assertIsNone(self.publisher.status('nope'))
        self.assertIsNone(self.publisher.cancel('nope'))
        fresh = self.publisher.start(self.store, self.api, self.payload(), bridge=FakeBridge())
        # The worker thread may already have advanced past 'queued'; the
        # registry contract is presence + a known state.
        state = self.publisher.status(fresh['jobId'])['state']
        self.assertIn(state, ('queued', 'preflight', 'staging', 'creating', 'updating',
                              'uploading', 'done', 'error', 'cancelled', 'cancelling'))
        self.publisher.cancel(fresh['jobId'])

    def test_prereq_reports_checklist(self):
        with patch.object(self.publisher, '_bridge_instance', side_effect=SteamBridgeError('offline')):
            report = self.publisher.prereq(self.store, self.api, self.ident)
        self.assertFalse(report['ready'])
        self.assertFalse(report['steam']['available'])
        self.assertTrue(report['manifest']['ok'])
        self.assertTrue(report['preview']['ok'])
        self.assertEqual(report['binding']['publishedFileId'], '0')

    def test_asset_change_during_staging_rejected(self):
        asset = self.project.path / 'asset.png'
        asset.write_bytes(b'old')
        original = pub.stage_mod
        def changed(*args):
            result = original(*args)
            asset.write_bytes(b'new')
            return result
        fake = FakeBridge()
        with patch.object(pub, 'stage_mod', changed):
            result = self.run_job(fake, self.payload())
        self.assertEqual(result['error']['code'], 'conflict')
        self.assertEqual(fake.created, 0)

    def test_success_binding_failure_recovers_without_reupload(self):
        original = self.publisher._write_sidecar
        count = 0
        def fail_second(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('disk full')
            return original(*args)
        fake = FakeBridge()
        with patch.object(self.publisher, '_write_sidecar', fail_second):
            result = self.run_job(fake, self.payload())
        self.assertEqual(result['state'], 'done')
        self.assertTrue(result['bindingPending'])
        recovered = self.publisher.recover_binding(self.store, self.api, {'jobId': result['jobId']})
        self.assertFalse(recovered['bindingPending'])
        self.assertEqual(fake.created, 1)
        self.assertEqual(sum(call[0] == 'submit' for call in fake.calls), 1)

    def test_corrupt_binding_blocks_create_and_can_rebind(self):
        target = self.project.path / pub.SIDECAR
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{broken')
        with self.assertRaises(PublishError):
            self.publisher.start(self.store, self.api, self.payload(), bridge=FakeBridge())
        self.publisher.bind_existing(self.store, self.api, self.payload(publishedFileId='18446744073709551614'))
        self.assertEqual(pub.read_sidecar(self.project)['publishedFileId'], 18446744073709551614)
        self.assertEqual(target.with_name('workshop-binding-backup.json').read_text(), '{broken')

    def test_definitive_create_failure_allows_retry(self):
        class FailedBridge(FakeBridge):
            def create_item(self, timeout=120):
                raise SteamBridgeError('denied', code='steam_create_failed')
        self.assertEqual(self.run_job(FailedBridge(), self.payload())['state'], 'error')
        self.assertEqual(self.run_job(FakeBridge(), self.payload())['state'], 'done')

    def test_custom_cover_prereq(self):
        import base64
        raw = (self.project.path / 'preview.jpg').read_bytes()
        cover = self.publisher.cover(self.store, self.api, self.payload(data=base64.b64encode(raw).decode()))
        (self.project.path / 'preview.jpg').unlink()
        self.assertTrue(self.publisher.prereq(self.store, self.api, self.ident, self.payload(**cover))['preview']['ok'])

    def test_packaged_bridge_integrity_and_callback_layout(self):
        import ctypes, hashlib
        import steam_bridge as sb
        raw = sb.packaged_bridge().read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), sb.BRIDGE_SHA256)
        self.assertEqual(ctypes.sizeof(sb.SubmitItemUpdateResult), 16)
        self.assertEqual(sb.SubmitItemUpdateResult.publishedFileId.offset, 8)
        self.assertEqual(sb.FILE_TYPE_COMMUNITY, 0)

    def test_close_never_unloads_under_worker(self):
        gate, started = threading.Event(), threading.Event()
        class Waiting(FakeBridge):
            def create_item(inner, timeout=120):
                started.set()
                gate.wait(10)
                return 87654
        fake = Waiting()
        self.publisher._bridge = fake
        self.publisher.start(self.store, self.api, self.payload())
        self.assertTrue(started.wait(5))
        self.publisher.close()
        self.assertNotIn(('shutdown',), fake.calls)
        gate.set()
        self.publisher._worker.join(5)
        self.assertIn(('shutdown',), fake.calls)
        self.assertFalse(self.publisher.busy())

    def test_staging_holds_save_lock(self):
        original = pub.stage_mod
        acquired = []
        def locked(*args):
            def other_writer():
                locked = self.store.lock.acquire(blocking=False)
                acquired.append(locked)
                if locked:
                    self.store.lock.release()
            thread = threading.Thread(target=other_writer)
            thread.start(); thread.join()
            return original(*args)
        with patch.object(pub, 'stage_mod', locked):
            self.assertEqual(self.run_job(FakeBridge(), self.payload())['state'], 'done')
        self.assertEqual(acquired, [False])

    def test_submit_callback_finishes_without_waiting_for_invalid_progress(self):
        bridge = SteamBridge(bridge_path='unused.dll')
        bridge._initialized = True
        def submit(*args):
            bridge._update_result = (1, False)
            bridge._update_event.set()
        bridge._lib = SimpleNamespace(Workshop_SubmitItemUpdate=submit)
        with patch.object(bridge, 'start_pump'), patch.object(bridge, 'stop_pump'), patch.object(bridge, 'update_progress') as progress:
            self.assertEqual(bridge.submit_update(1, 'note', timeout=.1), 1)
        progress.assert_not_called()

    # ---- bridge binding surface ----

    def test_bridge_declares_all_signatures(self):
        import ctypes
        from types import SimpleNamespace
        from ctypes import c_uint32, c_uint64
        names = ('SteamInit SteamShutdown RunCallbacks IsSteamRunning Workshop_CreateItem '
                 'Workshop_StartItemUpdate Workshop_SetItemTitle Workshop_SetItemDescription '
                 'Workshop_SetItemMetadata Workshop_SetItemVisibility Workshop_SetItemTags '
                 'Workshop_SetItemContent Workshop_SetItemPreview Workshop_SubmitItemUpdate '
                 'Workshop_GetItemUpdateProgress Workshop_SetItemCreatedCallback '
                 'Workshop_SetItemUpdatedCallback').split()
        namespace = SimpleNamespace(**{name: SimpleNamespace() for name in names})
        bridge = SteamBridge(bridge_path='unused.dll', official_dll='unused.dll',
                             cdll_factory=lambda path: namespace)
        bridge._lib = namespace
        bridge._declare()
        self.assertEqual(namespace.Workshop_StartItemUpdate.argtypes, [c_uint32, c_uint64])
        self.assertEqual(namespace.Workshop_SetItemTags.argtypes,
                         [c_uint64, ctypes.POINTER(ctypes.c_char_p), ctypes.c_int32])
        self.assertIn('SteamInit', dir(namespace))

    def test_bridge_holds_callbacks(self):
        import ctypes
        import gc
        from types import SimpleNamespace
        seen = {}
        namespace = SimpleNamespace()

        def fake_setter(callback):
            seen['callback'] = callback

        namespace.Workshop_SetItemCreatedCallback = fake_setter
        namespace.Workshop_SetItemUpdatedCallback = fake_setter
        bridge = SteamBridge(bridge_path='unused.dll', official_dll='unused.dll',
                             cdll_factory=lambda path: namespace)
        bridge._lib = namespace
        bridge._register_callbacks()
        gc.collect()
        self.assertIsNotNone(bridge._on_created)
        self.assertIsNotNone(bridge._on_updated)
        self.assertIs(seen['callback'], bridge._on_updated)

    def test_result_vocabulary(self):
        self.assertEqual(SteamBridge.describe_result(9), '物品不存在（可能已被删除）')
        self.assertTrue(SteamBridge.describe_result(999).startswith('Steam 返回码'))


if __name__ == '__main__':
    unittest.main()
