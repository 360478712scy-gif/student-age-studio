"""Differential and fault checks for immutable disk pages in disposable Mods."""
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
from talk_segments import Generation, SegmentError, records


class RecordTests(unittest.TestCase):
    def test_exact_tokens_utf8_and_nested_boundaries(self):
        raw = b'\xef\xbb\xbf' + '{\r\n "1": {"id":1, "content":"中文😀}\\\"\\\\\\n", "future":[{"x":1.234567890123456789e+09,"big":9007199254740993}]}\r\n}'.encode()
        output = dict(records(raw))['1']
        self.assertIn(b'1.234567890123456789e+09', output)
        self.assertIn(b'9007199254740993', output)
        self.assertEqual(json.loads(raw)['1'], json.loads(output))

    def test_reject_ambiguous_or_damaged_source(self):
        cases = ['{"1":{"id":1},"1":{"id":1}}', '{"1":{"id":1,"x":1,"x":2}}',
                 '{"1":{"id":2}}', '{"1":{"id":true}}', '{"01":{"id":1}}',
                 '{"1":{"id":1},}', '{"1":', '{} garbage', '[]', '{"1":{"id":1,"x":NaN}}']
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                list(records(raw.encode()))
        self.assertEqual(list(records(b'{}')), [])


class SegmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root / 'Cache'),
                                     'STUDIO_USER_DATA_ROOT': str(self.root / 'User')})
        env.start()
        self.addCleanup(env.stop)
        self.store = b.StudioStore(self.root/'Mods', self.root/'Workshop', self.root/'Game',
                                   asset_settings_path=self.root/'assets.json')
        self.ident = self.store.create('Segment differential')['id']
        self.project = self.store.project(self.ident)
        self.cfg = self.project.path/'Cfgs/zh-cn'
        self.talks = {str(i): {'id': i, 'content': '中文😀' * 100,
                               'nextTalk': [i+1] if i < 199 else [], 'future': {'keep': [i]}}
                      for i in range(1, 201)}
        self.talks['199']['nextTalk'] = [1]  # cycle
        self.events = {'7': {'id': 7, 'talkId': [1]}, '8': {'id': 8, 'talkId': [80]},
                       '9': {'id': 9, 'talkId': [999]}}
        self.write('TalkCfg', self.talks)
        self.write('EvtCfg', self.events)
        self.write('KZoneProfileCfg', {'3': {'id': 3, 'font': 9}})
        state = self.project.path/'StudentAgeStudio/editor-state.json'
        state.parent.mkdir(exist_ok=True)
        state.write_bytes(b.json_bytes({'talkOwners': {'200': [7]}}))
        self.before = {p.relative_to(self.project.path).as_posix(): p.read_bytes()
                       for p in self.project.path.rglob('*') if p.is_file()}

    def write(self, name, rows):
        (self.cfg/(name+'.json')).write_bytes(b.json_bytes(rows))

    def open(self):
        descriptor = self.store.talk_segments.open(self.ident)
        token = descriptor['segmentedTalks']['generation']
        return descriptor, self.store.talk_segments.get(self.ident, token)

    def assert_source_unchanged(self):
        self.assertEqual(self.before, {p.relative_to(self.project.path).as_posix(): p.read_bytes()
                                      for p in self.project.path.rglob('*') if p.is_file()})

    def test_full_differential_and_warm_seek(self):
        descriptor, gen = self.open()
        self.assertNotIn('talks', descriptor)
        rows = {}
        keys = descriptor['segmentedTalks']['ids']
        for start in range(0, len(keys), 100):
            rows.update({key: json.loads(value) for key, value in gen.page(keys[start:start+100])['rows']})
        self.assertEqual(rows, self.store.load(self.ident)['talks'])
        with patch.object(self.store, 'load', side_effect=AssertionError('warm full load')):
            again = self.store.talk_segments.open(self.ident)
            page = gen.page(['1'])
        self.assertEqual(again['segmentedTalks']['generation'], gen.generation)
        self.assertEqual(page['parsedRows'], 1)
        self.assertLess(page['readBytes'], (self.cfg/'TalkCfg.json').stat().st_size // 100)
        self.assertIn('200', descriptor['segmentedTalks']['eventIds']['7'])
        self.assertIn('1', descriptor['segmentedTalks']['eventIds']['8'])
        self.assertEqual(descriptor['segmentedTalks']['eventIds']['9'], [])
        self.assert_source_unchanged()

    def test_http_cache_failure_falls_back_to_existing_indexed_table(self):
        import threading
        import urllib.request
        import urllib.parse
        host = b.StudioServer(('127.0.0.1', 0), self.store)
        worker = threading.Thread(target=host.serve_forever, daemon=True)
        worker.start()
        try:
            with patch('playback_repair.repair'), patch.object(self.store, 'clean_orphan_dialogues'), patch.object(self.store.talk_segments, 'open', side_effect=OSError('cache unavailable')):
                url = host.origin+'/api/project?'+urllib.parse.urlencode({'id': self.ident, 'talkStorage': 'segmented'})
                request = urllib.request.Request(url, headers={'X-Studio-Token':host.token})
                with urllib.request.urlopen(request) as response:
                    data = json.load(response)
            self.assertNotIn('segmentedTalks', data)
            self.assertEqual({key:json.loads(text) for key,text in data['indexedTalks']['rows']}, self.talks)
            self.assertIn('cache unavailable', data['warnings'][0])
            self.assert_source_unchanged()
        finally:
            host.shutdown()
            host.server_close()
            host.media_warmup.close()
            worker.join(timeout=5)

    def test_null_optional_fields_preserve_real_mod_rows(self):
        self.talks['1'].update(roleIds=None, content=None, roleName=None)
        self.write('TalkCfg', self.talks)
        _, gen = self.open()
        self.assertEqual(json.loads(gen.page(['1'])['rows'][0][1]), self.talks['1'])
        self.assertEqual(gen.summaries['1']['excerpt'], '')

    def test_search_paging_and_missing_distinct_from_empty(self):
        _, gen = self.open()
        first = gen.search('中文')
        self.assertEqual(len(first['ids']), 100)
        second = gen.search('中文', first['nextOffset'])
        self.assertEqual(len(second['ids']), 100)
        self.assertIsNone(second['nextOffset'])
        with self.assertRaises(SegmentError):
            gen.page(['999'])
        self.assertEqual(gen.page([])['rows'], [])

    def test_external_same_size_and_restored_mtime(self):
        _, gen = self.open()
        path = self.cfg/'TalkCfg.json'
        stat = path.stat()
        path.write_bytes(path.read_bytes().replace('中文'.encode(), '变化'.encode()))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with self.assertRaises(b.ApiError) as error:
            gen.page(['1'])
        self.assertEqual(error.exception.status, 409)
        _, rebuilt = self.open()
        self.assertNotEqual(rebuilt.generation, gen.generation)

    def test_relation_change_and_atomic_replace_invalidate(self):
        _, gen = self.open()
        self.events['7']['talkId'] = [200]
        temporary = self.cfg/'event.tmp'
        temporary.write_bytes(b.json_bytes(self.events))
        temporary.replace(self.cfg/'EvtCfg.json')
        with self.assertRaises(b.ApiError):
            gen.page(['1'])

    def test_cache_tamper_or_removal_cannot_be_empty_success(self):
        _, gen = self.open()
        path = gen.path/'records.json'
        path.write_bytes(path.read_bytes().replace('中文'.encode(), '损坏'.encode()))
        with self.assertRaises(SegmentError):
            gen.page(['1'])
        path.unlink()
        with self.assertRaises(OSError):
            gen.page(['1'])
        self.assert_source_unchanged()

    def test_build_failure_never_publishes_generation(self):
        with patch('talk_segments.os.fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.open()
        self.assertEqual(self.store.talk_segments.generations, {})
        self.assertEqual(list((self.root/'Cache/TalkSegments/v1').iterdir()), [])
        self.assert_source_unchanged()

    def test_build_concurrent_edit_rejected(self):
        original = self.store.load
        def changed(ident, original_events=()):
            data = original(ident, original_events)
            self.write('EvtCfg', {})
            return data
        with patch.object(self.store, 'load', side_effect=changed), self.assertRaises(b.ApiError):
            self.open()
        self.assertFalse(self.store.talk_segments.generations)

    def test_bad_duplicate_source_rejected_without_modification(self):
        path = self.cfg/'TalkCfg.json'
        path.write_text('{"1":{"id":1},"1":{"id":1}}')
        raw = path.read_bytes()
        with self.assertRaises(SegmentError):
            self.open()
        self.assertEqual(path.read_bytes(), raw)

    def test_partial_save_matches_full_oracle_and_preserves_other_tables(self):
        descriptor, gen = self.open()
        row = json.loads(gen.page(['5'])['rows'][0][1])
        row['content'] = '只改已加载句'
        result = self.store.save({'projectId': self.ident, 'revision': descriptor['revision'],
                                  'talkGeneration': gen.generation,
                                  'talkPatch': {'version': 1, 'upsert': {'5': row}, 'deleted': []}})
        expected = copy.deepcopy(self.talks)
        expected['5'] = row
        self.assertEqual(b.read_json(self.cfg/'TalkCfg.json'), expected)
        self.assertEqual((self.cfg/'KZoneProfileCfg.json').read_bytes(), self.before['Cfgs/zh-cn/KZoneProfileCfg.json'])
        self.assertEqual((Path(result['backup'])/'Cfgs/zh-cn/TalkCfg.json').read_bytes(), self.before['Cfgs/zh-cn/TalkCfg.json'])
        self.assertTrue(result['talkGenerationAdvanced'])
        self.assertEqual(json.loads(gen.page(['5'])['rows'][0][1]), self.talks['5'])
        self.assertEqual(gen.page(['6'])['revision'], result['revision'])
        _, new_generation = self.open()
        self.assertNotEqual(gen.generation, new_generation.generation)
        self.assertEqual(json.loads(new_generation.page(['5'])['rows'][0][1]), row)

    def test_partial_full_table_save_is_rejected(self):
        descriptor, gen = self.open()
        with self.assertRaises(b.ApiError):
            self.store.save({'projectId': self.ident, 'revision': descriptor['revision'],
                             'talkGeneration': gen.generation, 'talks': {'1': self.talks['1']}})
        self.assert_source_unchanged()

    def test_original_override_keeps_hidden_rows(self):
        import original_mode
        base = {'1': {'id': 1, 'content': '原版'}, '400': {'id': 400, 'content': '原版未覆盖'}}
        with patch.object(self.store, 'catalog', return_value={'tables': {'TalkCfg': base}}), original_mode.scope(self.ident):
            descriptor, gen = self.open()
            expected = self.store.load(self.ident)['talks']
            got = {}
            for key in descriptor['segmentedTalks']['ids']:
                got.update({k: json.loads(v) for k, v in gen.page([key])['rows']})
            self.assertEqual(got, expected)
        self.assert_source_unchanged()


if __name__ == '__main__':
    unittest.main()
