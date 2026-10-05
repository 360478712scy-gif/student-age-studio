"""Real WAV inputs exercise audio-library AAC previews and native WAV registration."""
import base64
import io
import json
import math
import struct
import subprocess
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asset_catalog
import audio_transcode
import editor_music
import server as api
import test_plugin_mode


class AudioLibraryAacTests(unittest.TestCase):
    def setUp(self):
        test_plugin_mode.PluginModeTests.setUp(self)
        self.addCleanup(self.store.close)
        self.root = Path(self.tmp.name)
        self.audio = self.root / 'Music'
        self.audio.mkdir()
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(32000)
            output.writeframes(b''.join(struct.pack('<h', round(6000 * math.sin(i * math.tau * 440 / 32000))) for i in range(4000)))
        self.raw = buffer.getvalue()
        self.source = self.audio / '测试音乐.wav'
        self.source.write_bytes(self.raw)
        self.assets = self.store.asset_catalog
        folders = self.assets.folders()
        self.assets.set_folder({'kind': 'audio', 'path': str(self.audio), 'settingsRevision': folders['revision']})

    def payload(self, **extra):
        return {'projectId': self.id, 'revision': self.store.revision(self.project),
                'source': 'custom', 'kind': 'audio', 'settingsRevision': self.assets.folders()['revision'], **extra}

    def snapshot(self):
        return {str(path.relative_to(self.project.path)): path.read_bytes()
                for path in self.project.path.rglob('*') if path.is_file()}

    def pair(self, ident):
        row = api.read_json(self.cfg / 'AudioCfg.json')[str(ident)]
        native = self.store.project_asset(self.project, row['url'])
        self.assertEqual(native.suffix, '.wav')
        with wave.open(str(native), 'rb') as stream:
            self.assertEqual((stream.getsampwidth(), stream.getnchannels(), stream.getframerate()), (2, 2, 48000))
            self.assertGreater(len(stream.readframes(stream.getnframes())), 0)
        previews = api.read_json(self.project.path / 'StudentAgeStudio/audio-imports.json')['previews']
        preview = self.project.path / previews[str(ident)]['path']
        self.assertEqual(preview.suffix, '.m4a')
        self.assertEqual(previews[str(ident)]['native'], native.relative_to(self.project.path).as_posix())
        self.assertEqual(preview.read_bytes()[4:8], b'ftyp')
        return native, preview

    def test_folder_import_commits_real_codec_pair_in_one_transaction_without_locking_conversion(self):
        original = api.prepare_audio_import
        def convert(payload):
            self.assertFalse(self.store.lock._is_owned(), 'Codec conversion holds the editor writer lock')
            return original(payload)
        with patch.object(api, 'prepare_audio_import', side_effect=convert), patch.object(self.store, 'commit', wraps=self.store.commit) as commit:
            result = self.assets.import_folder(self.payload())
        self.assertEqual(commit.call_count, 1)
        written = commit.call_args.args[1]
        self.assertIn('StudentAgeStudio/audio-imports.json', set(written))
        self.assertIn('Cfgs/zh-cn/AudioCfg.json', set(written))
        self.assertEqual(len([key for key in written if key.startswith('Audios/')]), 2)
        self.assertEqual(result['count'], 1)
        _, preview = self.pair(result['results'][0]['id'])
        subprocess.run([audio_transcode._ffmpeg(), '-v', 'error', '-i', str(preview), '-f', 'null', '-'],
                       check=True, capture_output=True, timeout=10)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.protected.read_bytes(), self.before)

    def test_single_library_sound_uses_real_aac_and_original_thread_writer_scope(self):
        query = self.payload()
        item = next(item for item in self.assets.list(query)['items'] if item['origin'] == 'folder')
        with patch.object(self.store, 'audio_import', wraps=self.store.audio_import) as imported:
            result = self.assets.import_asset({**query, 'assetId': item['assetId'], 'assetRevision': item['mediaRevision'], 'type': 2})
        self.assertEqual(imported.call_args.args[0]['transcode'], 'aac')
        self.assertIn('prepared', imported.call_args.kwargs)
        self.pair(result['id'])
        self.assertEqual(api.read_json(self.cfg / 'AudioCfg.json')[str(result['id'])]['type'], 2)

    def test_missing_aac_is_repaired_with_stable_id_and_unknown_metadata_survives(self):
        result = self.assets.import_folder(self.payload())
        ident = result['results'][0]['id']
        _, preview = self.pair(ident)
        path = self.project.path / 'StudentAgeStudio/audio-imports.json'
        metadata = api.read_json(path)
        metadata['future'] = {'keep': 1}
        metadata['previews'][str(ident)]['future'] = ['keep']
        api.atomic_write(path, api.json_bytes(metadata)); preview.unlink()
        repaired = self.assets.import_folder(self.payload())
        self.assertEqual(repaired['results'][0]['id'], ident)
        self.pair(ident)
        after = api.read_json(path)
        self.assertEqual(after['future'], metadata['future'])
        self.assertEqual(after['previews'][str(ident)]['future'], ['keep'])
        repeated = self.assets.import_folder(self.payload())
        self.assertEqual(repeated['skipped'], 1)
        self.assertFalse(repeated['imported'])

    def test_bad_audio_or_metadata_never_commits_a_registration(self):
        self.source.write_bytes(b'RIFF\x00\x00\x00\x00WAVEfmt ')
        before = self.snapshot()
        result = self.assets.import_folder(self.payload())
        self.assertEqual(result['count'], 0)
        self.assertTrue(result['warnings'])
        self.assertEqual(self.snapshot(), before)
        self.source.write_bytes(self.raw)
        with patch.object(api, 'prepare_audio_import', side_effect=api.ApiError('decode failed', 422)), self.assertRaises(api.ApiError):
            self.assets.import_folder(self.payload())
        self.assertEqual(self.snapshot(), before)
        path = self.project.path / 'StudentAgeStudio/audio-imports.json'
        for value in ([], {'version': 1, 'previews': []}, {'version': 1, 'previews': {'1': None}}):
            api.atomic_write(path, api.json_bytes(value)); before = self.snapshot()
            with self.subTest(value=value), self.assertRaises(api.ApiError): self.assets.import_folder(self.payload())
            self.assertEqual(self.snapshot(), before)

    def test_audio_library_accepts_actual_aac_with_an_mp3_filename(self):
        _, _, aac = api.prepare_audio_import({'fileName': 'source.wav', 'transcode': 'aac',
                                             'data': base64.b64encode(self.raw).decode()})
        self.source.unlink()
        renamed = self.audio / '实际AAC.mp3'
        renamed.write_bytes(aac)
        item = next(item for item in self.assets.list(self.payload())['items'] if item['origin'] == 'folder')
        self.assertTrue(item['canImport'])
        result = self.assets.import_folder(self.payload())
        self.pair(result['results'][0]['id'])
        self.assertEqual(renamed.read_bytes(), aac)

    def test_changed_source_during_conversion_is_rejected_before_writing(self):
        original = api.prepare_audio_import
        def convert(payload):
            value = original(payload)
            self.source.write_bytes(self.raw + b'changed')
            return value
        before = self.snapshot()
        with patch.object(api, 'prepare_audio_import', side_effect=convert), self.assertRaises(api.ApiError) as caught:
            self.assets.import_folder(self.payload())
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.snapshot(), before)

    def test_personal_music_stores_aac_and_keeps_pause_volume_without_game_writes(self):
        editor_music.access(self.store, api, {'playing': False, 'volume': .21})
        before = self.snapshot()
        payload = {'trackId': 'local', 'fileName': self.source.name, 'transcode': 'aac',
                   'data': base64.b64encode(self.raw).decode()}
        first = editor_music.access(self.store, api, payload)
        row = next(row for row in first['tracks'] if row['id'].startswith('local-'))
        file = editor_music.media(api, row['id'])
        self.assertEqual(file.suffix, '.m4a')
        self.assertEqual(file.read_bytes()[4:8], b'ftyp')
        second = editor_music.access(self.store, api, payload)
        self.assertEqual(len([row for row in second['tracks'] if row['id'].startswith('local-')]), 1)
        self.assertEqual(second['preferences']['playing'], False)
        self.assertEqual(second['preferences']['volume'], .21)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def existing_native(self, prepared, ident=17):
        native = 'Audios/user.wav'
        api.atomic_write(self.project.path / native, prepared[0])
        row = {'id': ident, 'name': '已有音频', 'type': 1,
               'url': 'Mods\\' + self.project.package + '\\' + native.replace('/', '\\'), 'future': 'keep'}
        api.atomic_write(self.cfg / 'AudioCfg.json', api.json_bytes({str(ident): row}))
        return native, row

    def real_pair(self):
        return api.prepare_audio_import({'fileName': self.source.name, 'transcode': 'aac',
                                         'data': base64.b64encode(self.raw).decode()})

    def unrelated_aac(self):
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(32000)
            output.writeframes(b''.join(struct.pack('<h', round(6000 * math.sin(i * math.tau * 880 / 32000))) for i in range(4000)))
        return api.prepare_audio_import({'fileName': '另一首.wav', 'transcode': 'aac',
                                        'data': base64.b64encode(buffer.getvalue()).decode()})[2]

    def test_preview_ownership_unbound_same_name_never_overwrites_user_file_and_reuses_id(self):
        prepared = self.real_pair()
        native, row = self.existing_native(prepared)
        unrelated = self.project.path / 'Audios/user.m4a'
        sentinel = self.unrelated_aac(); unrelated.write_bytes(sentinel)
        table_before = (self.cfg / 'AudioCfg.json').read_bytes()
        result = self.store.audio_import({**self.payload(), 'fileName': self.source.name, 'type': 1}, prepared=prepared)
        self.assertTrue(result['reused']); self.assertEqual(result['id'], row['id'])
        self.assertNotEqual(result['assetPath'], 'Audios/user.m4a')
        self.assertEqual(unrelated.read_bytes(), sentinel)
        self.assertEqual((self.project.path / result['assetPath']).read_bytes(), prepared[2])
        self.assertEqual((self.cfg / 'AudioCfg.json').read_bytes(), table_before)
        self.assertEqual(api.read_json(self.project.path / 'StudentAgeStudio/audio-imports.json')['previews']['17']['native'], native)

    def test_preview_ownership_only_matching_id_native_may_repair_owned_path(self):
        prepared = self.real_pair()
        native, _ = self.existing_native(prepared)
        path = self.project.path / 'StudentAgeStudio/audio-imports.json'
        own = 'Audios/owned-preview.m4a'
        (self.project.path / own).write_bytes(b'damaged own preview')
        metadata = {'version': 1, 'future': {'keep': 1}, 'previews': {
            '17': {'path': own, 'native': native, 'future': ['keep']}}}
        api.atomic_write(path, api.json_bytes(metadata))
        result = self.store.audio_import({**self.payload(), 'fileName': self.source.name, 'type': 1}, prepared=prepared)
        self.assertEqual(result['assetPath'], own)
        self.assertEqual((self.project.path / own).read_bytes(), prepared[2])
        after = api.read_json(path)
        self.assertEqual(after['future'], metadata['future'])
        self.assertEqual(after['previews']['17']['future'], ['keep'])

    def test_preview_ownership_other_id_or_unconfirmed_native_gets_unique_path(self):
        prepared = self.real_pair()
        native, _ = self.existing_native(prepared)
        path = self.project.path / 'StudentAgeStudio/audio-imports.json'
        preview = 'Audios/user.m4a'
        sentinel = self.unrelated_aac()
        for bindings in ({'17': {'path': preview, 'native': 'Audios/other.wav', 'future': 'keep'}},
                         {'17': {'path': preview, 'native': native, 'future': 'keep'},
                          '18': {'path': preview, 'native': 'Audios/other.wav', 'future': 'other keep'}}):
            with self.subTest(bindings=bindings):
                (self.project.path / preview).write_bytes(sentinel)
                api.atomic_write(path, api.json_bytes({'version': 1, 'future': 'keep', 'previews': bindings}))
                result = self.store.audio_import({**self.payload(), 'fileName': self.source.name, 'type': 1}, prepared=prepared)
                self.assertEqual(result['id'], 17)
                self.assertNotEqual(result['assetPath'], preview)
                self.assertEqual((self.project.path / preview).read_bytes(), sentinel)
                after = api.read_json(path)
                self.assertEqual(after['future'], 'keep')
                self.assertEqual(after['previews']['17']['future'], 'keep')
                if '18' in bindings: self.assertEqual(after['previews']['18'], bindings['18'])

    def test_preview_ownership_pending_batch_paths_and_metadata_do_not_collide(self):
        prepared = self.real_pair()
        native, _ = self.existing_native(prepared)
        sentinel = self.unrelated_aac()
        changes = {'Audios/user.m4a': sentinel}
        first = self.store.audio_preview_changes(self.project, 17, native, prepared[2], changes)
        second = self.store.audio_preview_changes(self.project, 18, native, prepared[2], changes)
        self.assertNotIn('Audios/user.m4a', (first, second))
        self.assertNotEqual(first, second)
        self.assertEqual(changes['Audios/user.m4a'], sentinel)
        metadata = json.loads(changes['StudentAgeStudio/audio-imports.json'])
        self.assertEqual(set(metadata['previews']), {'17', '18'})
        self.store.commit(self.project, changes, self.store.revision(self.project))
        self.assertEqual((self.project.path / 'Audios/user.m4a').read_bytes(), sentinel)
        self.assertEqual((self.project.path / first).read_bytes(), prepared[2])
        self.assertEqual((self.project.path / second).read_bytes(), prepared[2])

    def test_folder_historical_aac_repair_preserves_unbound_files_and_all_staged_metadata(self):
        (self.audio / '另一条音乐.wav').write_bytes(self.raw)
        initial = self.assets.import_folder(self.payload())
        ids = {entry['id'] for entry in initial['results']}
        self.assertEqual(len(ids), 2)
        path = self.project.path / 'StudentAgeStudio/audio-imports.json'
        initial_metadata = api.read_json(path)
        # A historical WAV-only import has stable library IDs but no confirmed
        # AAC ownership. The same filenames belong to other user material.
        sentinels = {ident: self.project.path / initial_metadata['previews'][str(ident)]['path'] for ident in ids}
        unrelated = self.unrelated_aac()
        for sentinel in sentinels.values(): sentinel.write_bytes(unrelated)
        metadata = {'version': 1, 'future': {'keep': 1},
                    'previews': {str(ident): {'future': ['keep', ident]} for ident in ids}}
        api.atomic_write(path, api.json_bytes(metadata))
        table_before = (self.cfg / 'AudioCfg.json').read_bytes()
        repaired = self.assets.import_folder(self.payload())
        self.assertEqual({entry['id'] for entry in repaired['results']}, ids)
        after = api.read_json(path)
        self.assertEqual(after['future'], metadata['future'])
        self.assertEqual(set(after['previews']), {str(ident) for ident in ids})
        for ident in ids:
            self.assertEqual(sentinels[ident].read_bytes(), unrelated)
            _, preview = self.pair(ident)
            self.assertNotEqual(preview, sentinels[ident])
            self.assertEqual(after['previews'][str(ident)]['future'], ['keep', ident])
        self.assertEqual((self.cfg / 'AudioCfg.json').read_bytes(), table_before)
        repeated = self.assets.import_folder(self.payload())
        self.assertEqual(repeated['skipped'], 2)
        self.assertFalse(repeated['imported'])


if __name__ == '__main__': unittest.main()
