"""Real FFmpeg and production HTTP media imports, in disposable Mod directories."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
import video_transcode


class MediaImportAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = video_transcode._ffmpeg()
        cls.fixtures = tempfile.TemporaryDirectory(prefix='studio-media-http-fixture-')
        cls.addClassCleanup(cls.fixtures.cleanup)
        root = Path(cls.fixtures.name)
        for name, inputs, codecs in (
            ('source.webm', ['-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=12', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000'], ['-c:v', 'libvpx-vp9', '-c:a', 'libopus']),
            ('silent.webm', ['-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=12'], ['-c:v', 'libvpx-vp9', '-an']),
            ('source.wav', ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=22050'], ['-c:a', 'pcm_s16le']),
        ):
            process = subprocess.run([cls.ffmpeg, '-v', 'error', '-nostdin', *inputs, '-t', '0.4', *codecs, '-y', str(root / name)], capture_output=True, timeout=15)
            if process.returncode:
                raise AssertionError(process.stderr.decode(errors='replace'))
        cls.video = (root / 'source.webm').read_bytes()
        cls.silent = (root / 'silent.webm').read_bytes()
        cls.wav = (root / 'source.wav').read_bytes()
        cls.evidence = Path(os.environ['MEDIA_HTTP_EVIDENCE']).resolve() if os.environ.get('MEDIA_HTTP_EVIDENCE') else None
        if cls.evidence:
            cls.evidence.mkdir(parents=True, exist_ok=True)
            (cls.evidence / 'source.webm').write_bytes(cls.video)
            (cls.evidence / 'source.wav').write_bytes(cls.wav)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='studio-media-http-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = {key: str(self.root / name) for key, name in (
            ('STUDIO_USER_DATA_ROOT', 'User'), ('STUDIO_CACHE_ROOT', 'Cache'),
            ('STUDIO_BACKUP_ROOT', 'Backups'), ('STUDIO_ERROR_LOG_ROOT', 'Logs'),
            ('STUDIO_DISPLAY_SETTINGS', 'display.json'))}
        env['STUDIO_UPDATE_MANAGED'] = '1'
        context = patch.dict(os.environ, env)
        context.start()
        self.addCleanup(context.stop)
        self._start()
        self.addCleanup(self._stop)
        self.id = self.store.create('HTTP视频音频验收')['id']
        self.project = self.store.project(self.id)
        cfg = self.project.path / 'Cfgs/zh-cn'
        b.atomic_write(cfg / 'TalkCfg.json', b.json_bytes({'1': {'id': 1, 'content': '原始台词', 'effect': None, 'future': {'keep': True}}}))
        b.atomic_write(cfg / 'EvtCfg.json', b.json_bytes({'1': {'id': 1, 'title': '原始事件', 'future': 9}}))
        self.story = {path.name: path.read_bytes() for path in cfg.glob('*.json')}
        self.opener = build_opener(ProxyHandler({}))

    def _start(self):
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game', asset_settings_path=self.root / 'assets.json', migrate_cache=False)
        self.app = b.StudioServer(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.app.serve_forever, daemon=True)
        self.thread.start()

    def _stop(self):
        self.app.shutdown()
        self.app.server_close()
        self.thread.join(2)
        self.store.close()

    def request(self, path, data=None, binary=None, headers=None, token=True, timeout=20):
        values = {'X-Studio-Token': self.app.token} if token else {}
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            values['Content-Type'] = 'application/json'
        if binary is not None:
            body = binary
            values['Content-Type'] = 'application/octet-stream'
        values.update(headers or {})
        req = Request(self.app.origin + path, data=body, headers=values)
        try:
            response = self.opener.open(req, timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            out = json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw
            return response.status, out, dict(response.headers)

    def get(self, route, **query):
        status, result, _ = self.request(route + '?' + urlencode(query))
        self.assertEqual(status, 200, result)
        return result

    def revision(self):
        return self.get('/api/project-revision', id=self.id)['revision']

    def upload(self, raw=None, file_name='源视频.webm', revision=None):
        return self.request('/api/video-import?' + urlencode({'projectId': self.id, 'revision': revision or self.revision(), 'fileName': file_name}), binary=self.video if raw is None else raw)

    def imported(self, **kwargs):
        status, result, _ = self.upload(**kwargs)
        self.assertEqual(status, 201, result)
        return result

    def listing(self, source='mod', source_project=None):
        return self.get('/api/videos', projectId=self.id, source=source, sourceProjectId=source_project or self.id)

    def payload(self, item, source='mod'):
        return {'projectId': self.id, 'revision': self.revision(), 'source': source, 'assetId': item['assetId'], 'assetRevision': item['assetRevision'], **{key: item[key] for key in ('sourceProjectId', 'sourceRevision') if key in item}}

    def snapshot(self):
        return {str(path.relative_to(self.project.path)): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.project.path.rglob('*') if path.is_file()}

    def assert_story(self):
        for name, raw in self.story.items():
            self.assertEqual((self.project.path / 'Cfgs/zh-cn' / name).read_bytes(), raw)

    def assert_backup(self, result):
        self.assertTrue(result['backup'])
        transaction = b.read_json(Path(result['backup']) / 'transaction.json', {})
        self.assertEqual(transaction['state'], 'committed')

    def inspect(self, path):
        result = subprocess.run([self.ffmpeg, '-hide_banner', '-nostdin', '-i', str(path), '-map', '0', '-f', 'null', '-'], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result.stderr.decode(errors='replace').split('Output #', 1)[0]

    def test_binary_video_registers_real_h264_aac_without_story_save(self):
        result = self.imported()
        self.assertEqual((result['videoCodec'], result['audioCodec'], result['pixelFormat']), ('h264', 'aac', 'yuv420p'))
        self.assertTrue(result['hasAudio'] and result['fastStart'])
        path = self.project.path / result['assetPath']
        log = self.inspect(path)
        self.assertIn('Video: h264', log)
        self.assertIn('Audio: aac', log)
        self.assertEqual(b.read_json(self.project.path / 'ScreenVideo/CustomVideo.json', {})['videos'][0], result['row'])
        self.assertEqual(result['row']['video'], path.name)
        self.assert_story()
        self.assert_backup(result)
        if self.evidence:
            (self.evidence / 'h264-aac.mp4').write_bytes(path.read_bytes())

    def test_silent_video_stays_silent(self):
        result = self.imported(raw=self.silent)
        self.assertFalse(result['hasAudio'])
        self.assertIsNone(result['audioCodec'])
        self.assertNotIn('Audio:', self.inspect(self.project.path / result['assetPath']))
        self.assert_story()

    def test_settings_repeat_reopen_preserve_all_unknown_data(self):
        result = self.imported()
        config = self.project.path / 'ScreenVideo/CustomVideo.json'
        database = b.read_json(config, {})
        database['future'] = {'keep': 1}
        database['videos'][0]['futureRow'] = ['keep', 2]
        b.atomic_write(config, b.json_bytes(database))
        payload = {'projectId': self.id, 'revision': self.revision(), 'id': result['id'], 'name': '动态背景', 'volume': .25, 'loop': True, 'skippable': False, 'roleOnTop': True, 'scale': 'fill'}
        status, saved, _ = self.request('/api/video-settings', data=payload)
        self.assertEqual(status, 200, saved)
        self.assertEqual({key: saved['row'][key] for key in ('name', 'volume', 'loop', 'skippable', 'roleOnTop', 'scale')}, {key: payload[key] for key in ('name', 'volume', 'loop', 'skippable', 'roleOnTop', 'scale')})
        self.assertEqual(saved['row']['futureRow'], ['keep', 2])
        self.assert_backup(saved)
        payload['revision'] = saved['revision']
        self.assertEqual(self.request('/api/video-settings', data=payload)[0], 200)
        self._stop()
        self._start()
        loaded = self.listing()['items'][0]['row']
        self.assertEqual(loaded['futureRow'], ['keep', 2])
        self.assertEqual(b.read_json(config, {})['future'], {'keep': 1})
        self.assert_story()

    def test_current_mod_selection_references_without_transcoding(self):
        result = self.imported()
        item = self.listing()['items'][0]
        before = self.snapshot()
        with patch.object(video_transcode, 'transcode', side_effect=AssertionError('current Mod must not transcode')):
            status, reference, _ = self.request('/api/video-library-import', data=self.payload(item))
        self.assertEqual(status, 200, reference)
        self.assertTrue(reference['reference'])
        self.assertFalse(reference['imported'])
        self.assertEqual(reference['id'], result['id'])
        self.assertEqual(self.snapshot(), before)

    def test_other_mod_and_custom_copy_to_new_native_ids(self):
        other = self.store.project(self.store.create('另一个视频模组')['id'])
        folder = other.path / 'ScreenVideo'
        folder.mkdir()
        source = folder / 'source.webm'
        source.write_bytes(self.video)
        b.atomic_write(folder / 'CustomVideo.json', b.json_bytes({'future': 1, 'videos': [{'id': 17, 'name': '来源视频', 'video': source.name, 'futureRow': True}]}))
        for kind in ('mod', 'custom'):
            if kind == 'custom':
                state = self.get('/api/video-folder')
                self.assertEqual(self.request('/api/video-folder', data={'path': str(folder), 'revision': state['revision']})[0], 200)
            item = self.listing(kind, other.id)['items'][0]
            status, result, _ = self.request('/api/video-library-import', data=self.payload(item, kind))
            self.assertEqual(status, 201, result)
            self.assertNotEqual(result['id'], 17)
            self.assertEqual(result['videoCodec'], 'h264')
            self.assertTrue((self.project.path / result['assetPath']).is_file())
            if kind == 'mod':
                self.assertTrue(result['row']['futureRow'])
            self.assertEqual(source.read_bytes(), self.video)
            self.assert_backup(result)
        self.assertEqual(len({item['videoId'] for item in self.listing()['items']}), 2)
        self.assert_story()

    def test_preview_range_and_authentication_use_real_registered_movie(self):
        result = self.imported()
        url = self.listing()['items'][0]['previewUrl']
        status, raw, headers = self.request(url, headers={'Range': 'bytes=0-31'})
        self.assertEqual(status, 206)
        self.assertEqual(raw, (self.project.path / result['assetPath']).read_bytes()[:32])
        self.assertTrue(headers['Content-Range'].startswith('bytes 0-31/'))
        self.assertEqual(self.request(url, token=False)[0], 403)
        status, _, _ = self.request('/api/assets?' + urlencode({'projectId': self.id, 'path': result['url']}), headers={'Range': 'bytes=0-31'})
        self.assertEqual(status, 206)

    def test_converter_does_not_block_other_http_editor_reads(self):
        entered, release = threading.Event(), threading.Event()
        original = video_transcode.transcode
        def held(*args):
            entered.set()
            if not release.wait(5):
                raise AssertionError('test gate not released')
            return original(*args)
        revision = self.revision()
        with patch.object(video_transcode, 'transcode', held), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.upload, revision=revision)
            try:
                self.assertTrue(entered.wait(3))
                started = time.monotonic()
                self.assertEqual(self.request('/api/display-settings', timeout=2)[0], 200)
                self.assertEqual(self.get('/api/table', projectId=self.id, name='TalkCfg')['rows']['1']['effect'], None)
                self.assertLess(time.monotonic() - started, 1.5)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=20)[0], 201)

    def test_external_source_or_destination_changes_reject_after_conversion(self):
        folder = self.root / 'CustomVideo'
        folder.mkdir()
        source = folder / 'source.webm'
        source.write_bytes(self.video)
        state = self.get('/api/video-folder')
        self.assertEqual(self.request('/api/video-folder', data={'path': str(folder), 'revision': state['revision']})[0], 200)
        for changed in ('source', 'destination'):
            item = self.listing('custom')['items'][0]
            payload = self.payload(item, 'custom')
            entered, release = threading.Event(), threading.Event()
            original = video_transcode.transcode
            def held(*args):
                metadata = original(*args)
                entered.set()
                if not release.wait(5):
                    raise AssertionError('test gate not released')
                return metadata
            with patch.object(video_transcode, 'transcode', held), ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.request, '/api/video-library-import', data=payload)
                try:
                    self.assertTrue(entered.wait(8))
                    path = source if changed == 'source' else self.project.path / 'Cfgs/zh-cn/TalkCfg.json'
                    path.write_bytes(path.read_bytes() + b'\n')
                    expected = self.snapshot()
                finally:
                    release.set()
                status, error, _ = future.result(timeout=20)
                self.assertEqual((status, error['code']), (409, 'conflict'))
                self.assertEqual(self.snapshot(), expected)
        self.assertFalse((self.project.path / 'ScreenVideo').exists())

    def test_bad_video_and_aac_input_never_write_mod_files(self):
        before = self.snapshot()
        status, error, _ = self.upload(raw=b'not a video')
        self.assertEqual((status, error['code']), (422, 'video_conversion'))
        status, error, _ = self.request('/api/audio-import', data={'projectId': self.id, 'revision': self.revision(), 'fileName': 'broken.wav', 'data': base64.b64encode(b'not audio').decode(), 'type': 1, 'transcode': 'aac'})
        self.assertEqual((status, error['code']), (422, 'audio_conversion'))
        self.assertEqual(self.snapshot(), before)

    def audio_folder(self, name):
        folder = self.root / name
        folder.mkdir()
        (folder / 'first.wav').write_bytes(self.wav)
        state = self.get('/api/asset-folders')
        status, settings, _ = self.request('/api/asset-folders', data={
            'kind': 'audio', 'path': str(folder), 'settingsRevision': state['revision']})
        self.assertEqual(status, 200, settings)
        payload = {'projectId': self.id, 'revision': self.revision(), 'source': 'custom',
                   'kind': 'audio', 'library': True, 'settingsRevision': settings['revision']}
        return folder, payload

    def test_audio_library_conversion_keeps_both_import_routes_responsive(self):
        # The HTTP/store path is real; a held codec isolates lock behaviour.
        for index, route in enumerate(('/api/asset-catalog-import', '/api/asset-library-import')):
            with self.subTest(route=route):
                _, payload = self.audio_folder('ResponsiveAudio' + str(index))
                if route.endswith('catalog-import'):
                    listing = self.get('/api/asset-catalog', **payload)
                    item = listing['items'][0]
                    payload.update(assetId=item['assetId'], assetRevision=item['mediaRevision'])
                entered, release = threading.Event(), threading.Event()
                def held(_):
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError('audio test gate not released')
                    return self.wav, '.wav', None
                with patch.object(b, 'prepare_audio_import', held), ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self.request, route, data=payload)
                    try:
                        self.assertTrue(entered.wait(3))
                        self.assertEqual(self.request('/api/display-settings', timeout=2)[0], 200)
                        self.assertEqual(self.get('/api/table', projectId=self.id, name='TalkCfg')['rows']['1']['effect'], None)
                    finally:
                        release.set()
                    status, imported, _ = future.result(timeout=10)
                    self.assertEqual(status, 201, imported)
                self.assert_story()

    def test_parallel_audio_library_imports_preserve_reservations_and_revision(self):
        folder, payload = self.audio_folder('ConcurrentAudio')
        (folder / 'second.wav').write_bytes(self.wav)
        listing = self.get('/api/asset-catalog', **payload)
        first, second = listing['items']
        entered, release, second_waiting = threading.Event(), threading.Event(), threading.Event()
        class ObservedLock:
            def __init__(self):
                self.lock, self.owner = threading.RLock(), None
            def __enter__(self):
                caller = threading.get_ident()
                if self.owner is not None and caller != self.owner:
                    second_waiting.set()
                self.lock.acquire()
                self.owner = caller
            def __exit__(self, *args):
                self.lock.release()
        def held(_):
            entered.set()
            if not release.wait(5):
                raise AssertionError('concurrent audio test gate not released')
            return self.wav, '.wav', None
        first_payload = {**payload, 'assetId': first['assetId'], 'assetRevision': first['mediaRevision'], 'reservedIds': [1234567890]}
        second_payload = {**payload, 'assetIds': [second['assetId']], 'reservedIds': [1234567891]}
        route = '/api/asset-catalog-import'
        with patch.object(self.store.asset_catalog, '_import_lock', ObservedLock()), \
                patch.object(b, 'prepare_audio_import', held), ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(self.request, route, data=first_payload)
            try:
                self.assertTrue(entered.wait(3))
                second_future = pool.submit(self.request, route, data=second_payload)
                self.assertTrue(second_waiting.wait(3))
                self.assertFalse(second_future.done())
                self.assertTrue(self.store.lock.acquire(blocking=False), 'waiting import held store.lock')
                try:
                    self.assertEqual(self.store.record_ids.draft_reserved, {1234567890})
                finally:
                    self.store.lock.release()
                self.assertEqual(self.request('/api/display-settings', timeout=2)[0], 200)
            finally:
                release.set()
            first_status, imported, _ = first_future.result(timeout=10)
            self.assertEqual(first_status, 201, imported)
            second_status, error, _ = second_future.result(timeout=10)
            self.assertEqual((second_status, error['code']), (409, 'conflict'))
            self.assertEqual(self.store.record_ids.draft_reserved, set())
            second_payload['revision'] = self.revision()
            status, retried, _ = self.request(route, data=second_payload)
            self.assertEqual(status, 201, retried)
        rows = b.read_json(self.project.path / 'Cfgs/zh-cn/AudioCfg.json', {})
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row['id'] for row in rows.values()}), 2)
        self.assertTrue({1234567890, 1234567891}.isdisjoint(row['id'] for row in rows.values()))
        self.assertEqual(self.store.record_ids.draft_reserved, set())
        self.assert_story()

    def test_audio_aac_preview_and_pcm_game_asset_repeat_reopen(self):
        payload = {'projectId': self.id, 'revision': self.revision(), 'fileName': '真实音轨.wav', 'data': base64.b64encode(self.wav).decode(), 'name': '真实音轨', 'type': 1, 'transcode': 'aac'}
        status, result, _ = self.request('/api/audio-import', data=payload)
        self.assertEqual(status, 201, result)
        self.assertTrue(result['assetPath'].endswith('.m4a'))
        self.assertTrue(result['row']['url'].endswith('.wav'))
        preview = self.project.path / result['assetPath']
        self.assertIn('Audio: aac', self.inspect(preview))
        native = self.store.project_asset(self.project, result['row']['url'])
        with wave.open(str(native)) as stream:
            self.assertEqual((stream.getnchannels(), stream.getsampwidth(), stream.getframerate()), (2, 2, 48000))
            self.assertGreater(stream.getnframes(), 0)
        cfg = self.project.path / 'Cfgs/zh-cn/AudioCfg.json'
        rows = b.read_json(cfg, {})
        rows[str(result['id'])]['future'] = {'keep': True}
        b.atomic_write(cfg, b.json_bytes(rows))
        metadata_path = self.project.path / 'StudentAgeStudio/audio-imports.json'
        metadata = b.read_json(metadata_path, {})
        metadata['future'] = 3
        metadata['previews'][str(result['id'])]['future'] = 4
        b.atomic_write(metadata_path, b.json_bytes(metadata))
        payload['revision'] = self.revision()
        status, repeated, _ = self.request('/api/audio-import', data=payload)
        self.assertEqual(status, 201, repeated)
        self.assertTrue(repeated['reused'])
        self.assertEqual(repeated['id'], result['id'])
        self.assertEqual(repeated['row']['future'], {'keep': True})
        self.assert_backup(result)
        self.assert_story()
        self._stop()
        self._start()
        audios = self.get('/api/audio', projectId=self.id)['audios']
        audio = next(row for row in audios if row['id'] == result['id'])
        self.assertEqual(audio['assetPath'], result['assetPath'])
        self.assertEqual(b.read_json(metadata_path, {})['previews'][str(result['id'])]['future'], 4)
        self.assertEqual(b.read_json(metadata_path, {})['future'], 3)
        self.assertEqual(len(b.read_json(cfg, {})), 1)
        if self.evidence:
            (self.evidence / 'aac-preview.m4a').write_bytes(preview.read_bytes())


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MediaImportAPITests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if os.environ.get('MEDIA_HTTP_EVIDENCE'):
        evidence = Path(os.environ['MEDIA_HTTP_EVIDENCE'])
        evidence.mkdir(parents=True, exist_ok=True)
        report = {'status': 'passed' if result.wasSuccessful() else 'failed', 'tests': result.testsRun, 'failures': [name.id() for name, _ in result.failures], 'errors': [name.id() for name, _ in result.errors], 'actualFFmpeg': True, 'scope': 'production HTTP + actual codecs, isolated Mods; no native UI or game claim'}
        (evidence / 'media-http.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    sys.exit(not result.wasSuccessful())
