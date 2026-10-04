"""Large local files load without arbitrary size rejection or whole-row copies."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
from talk_segments import records, SegmentError


class LargeLoadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        env = patch.dict(os.environ, {'STUDIO_USER_DATA_ROOT': str(root / 'User'),
                                     'STUDIO_CACHE_ROOT': str(root / 'Cache'), 'STUDIO_BACKUP_ROOT': str(root / 'Backups')})
        env.start(); self.addCleanup(env.stop)
        self.store = b.StudioStore(root / 'Mods', root / 'Workshop', root / 'Game', asset_settings_path=root / 'assets.json', migrate_cache=False)
        self.addCleanup(self.store.close)
        self.project = self.store.project(self.store.create('大表读取')['id'])
        self.cfg = self.project.path / 'Cfgs/zh-cn'

    def write(self, name, value):
        path = self.cfg / (name + '.json')
        path.write_bytes(b.json_bytes(value))
        return path

    def test_only_mismatched_rows_are_copied_and_source_rows_remain_intact(self):
        good = {'id': 1, 'future': {'keep': [1, 2]}}
        bad = {'id': 999, 'future': {'keep': [3, 4]}}
        rows = {'1': good, '2': bad, '3': {'content': '缺编号'}}
        normalized, count = b.normalize_loaded_map(rows, 'TalkCfg.json')
        self.assertIs(normalized, rows)
        self.assertIs(normalized['1'], good)
        self.assertIsNot(normalized['2'], bad)
        self.assertEqual(count, 2)
        self.assertEqual(normalized['2']['id'], 2)
        self.assertEqual(bad['id'], 999)
        self.assertEqual(normalized['2']['future'], {'keep': [3, 4]})

    def test_load_repairs_ids_in_editing_copy_without_changing_native_bytes(self):
        path = self.write('TalkCfg', {'1': {'id': 9, 'content': '原文', 'future': [1, 2]},
                                      '2': {'content': '没有编号'}, '0': {'id': 0, 'future': True}})
        before = path.read_bytes(), b.file_fingerprint(path)
        loaded = self.store.load(self.project.id)
        self.assertEqual(loaded['talks']['1'], {'id': 1, 'content': '原文', 'future': [1, 2]})
        self.assertEqual(loaded['talks']['2']['id'], 2)
        self.assertEqual(loaded['talks']['0'], {'id': 0, 'future': True})
        self.assertTrue(any('2 处行编号不一致' in warning for warning in loaded['warnings']))
        self.assertEqual(before, (path.read_bytes(), b.file_fingerprint(path)))

    def test_readable_maps_validate_once_without_copying_or_repairing_native_rows(self):
        rows = {'1': {'id': 9, 'future': {'keep': [1, 2]}}, '2': {'id': True}, '0': {'id': 0}}
        path = self.write('TalkCfg', rows); before = path.read_bytes()
        original = b.read_json
        def read(path_arg, *args):
            return rows if path_arg == path else original(path_arg, *args)
        with patch.object(b, 'read_json', side_effect=read):
            maps, failures = self.store.readable_maps(self.project, {'TalkCfg.json'})
        self.assertEqual(failures, {})
        self.assertIs(maps['TalkCfg.json'], rows)
        self.assertIs(maps['TalkCfg.json']['1'], rows['1'])
        self.assertEqual(rows['1']['id'], 9)
        self.assertIs(rows['2']['id'], True)
        self.assertEqual(path.read_bytes(), before)
        for invalid in ([], {'bad': {'id': 1}}, {'1': []}, {'0': {'id': 1}}, {'0': {'id': False}}):
            with self.subTest(invalid=invalid):
                path = self.write('TalkCfg', invalid); before = path.read_bytes()
                maps, failures = self.store.readable_maps(self.project, {'TalkCfg.json'})
                self.assertNotIn('TalkCfg.json', maps)
                self.assertIn('TalkCfg.json', failures)
                self.assertEqual(path.read_bytes(), before)

    def test_genuinely_invalid_tables_keep_fallback_and_other_tables(self):
        self.write('EvtCfg', {'7': {'id': 7, 'talkId': []}})
        for value in ([], {'bad': {'id': 1}}, {'1': []}, {'0': {'id': 1}}, {'0': {'id': False}},
                      {'1': {'id': True}}, {'2147483648': {'id': 2147483648}}):
            with self.subTest(value=value):
                path = self.write('TalkCfg', value); before = path.read_bytes()
                loaded = self.store.load(self.project.id)
                self.assertEqual(loaded['talks'], {})
                self.assertIn('talks', loaded['unreadableTables'])
                self.assertTrue(loaded['warnings'])
                self.assertIn('7', loaded['events'])
                self.assertEqual(path.read_bytes(), before)

    def test_local_read_and_segmented_open_accept_files_above_http_limit(self):
        rows = {'1': {'id': 1, 'content': '中文' * 1000, 'future': {'keep': [1, 2]}}}
        path = self.write('TalkCfg', rows); before = path.read_bytes(), b.file_fingerprint(path)
        with patch.object(b, 'MAX_JSON', 256):
            self.assertGreater(path.stat().st_size, b.MAX_JSON)
            self.assertEqual(b.read_json(path), rows)
            descriptor = self.store.talk_segments.open(self.project.id)
            generation = self.store.talk_segments.get(self.project.id, descriptor['segmentedTalks']['generation'])
            self.assertEqual(json.loads(generation.page(['1'])['rows'][0][1]), rows['1'])
        self.assertEqual(before, (path.read_bytes(), b.file_fingerprint(path)))

    def test_actual_memory_exhaustion_has_explicit_error_and_preserves_source(self):
        path = self.write('TalkCfg', {'1': {'id': 1, 'content': '原文'}}); before = path.read_bytes()
        for target in ('server.json.loads', 'pathlib.Path.read_text'):
            with self.subTest(target=target), patch(target, side_effect=MemoryError('actual exhaustion')):
                with self.assertRaises(b.ApiError) as caught:
                    b.read_json(path)
                self.assertEqual((caught.exception.status, caught.exception.code), (503, 'file_memory'))
        original = Path.read_bytes
        def read(path_arg):
            if path_arg == path: raise MemoryError('actual exhaustion')
            return original(path_arg)
        with patch.object(Path, 'read_bytes', read), self.assertRaises(b.ApiError) as caught:
            self.store.talk_segments.open(self.project.id)
        self.assertEqual((caught.exception.status, caught.exception.code), (503, 'file_memory'))
        self.assertEqual(path.read_bytes(), before)

    def test_segment_records_validate_all_500000_rows_and_reject_invalid_tail(self):
        raw = ('{' + ','.join('"' + str(ident) + '":{"id":' + str(ident) + '}' for ident in range(1, 500001)) + '}').encode()
        count, last = 0, None
        for last in records(raw):
            count += 1
        self.assertEqual(count, 500000)
        self.assertEqual(last, ('500000', b'{"id":500000}'))
        damaged = raw.replace(b'"500000":{"id":500000}', b'"500000":{"id":499999}')
        with self.assertRaises(SegmentError):
            for _ in records(damaged):
                pass


if __name__ == '__main__':
    unittest.main()
