"""Automatic repairs preserve source bytes, backups, revisions and warm saves."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_condition_migration as m
import server as b


class NativeConditionByteTests(unittest.TestCase):
    def test_only_owned_commands_change_with_utf8_bom_and_foreign_tokens(self):
        raw = b'\xef\xbb\xbf' + ('{\n "7": {"id":7, "content":"文字😀 [7,9001,3,30]", '
            '"future":{"condition":[[7,9001,3,40]],"token":1e+003}, '
            '"effect":[[1163,2,9,0.5],[7,9001,3,30]], '
            '"check":[[7,9005,3,30], [1163,  2, 9.000, 1e-1], [4,9002,101,0.1], [7,9006,3,30]]},\n'
            ' "8":{"id":8,"content":"未知", "condition": [[4,1,101,30]]}\n}').encode('utf-8')
        result, stats = m.scan_bytes(raw, {'check', 'condition'})
        self.assertEqual(stats['converted'], 2)
        self.assertEqual(stats['unresolvedCount'], 1)
        self.assertTrue(result.startswith(b'\xef\xbb\xbf'))
        expected = raw.replace(b'[7,9005,3,30]', b'[7, 1, 3, 30.0], [7, -1, 3, 30.000001907348633]')
        expected = expected.replace(b'[4,9002,101,0.1]', b'[4, 2, 101, 0.10000000149011612]')
        self.assertEqual(result, expected)
        parsed = json.loads(result.decode('utf-8-sig'))
        self.assertEqual(parsed['7']['future']['condition'], [[7,9001,3,40]])
        self.assertEqual(parsed['7']['effect'][1], [7,9001,3,30])

    def test_negative_candidate_does_not_decode_large_native_file(self):
        raw = ('{"1":{"id":1,"content":"' + '原版' * 10000 + '","check":[[7,1,3,30]]}}').encode()
        with patch.object(m, '_DECODER', None):
            result, stats = m.scan_bytes(raw, {'check'})
        self.assertIsNone(result); self.assertEqual(stats['converted'], 0)

    def test_candidate_strings_and_unknown_fields_stay_identical(self):
        raw = b'{"1":{"id":1,"content":"[7,9001,3,30]","future":{"condition":[[7,9001,3,30]]},"effect":[[7,9001,3,30]]}}'
        result, stats = m.scan_bytes(raw, {'condition', 'check'})
        self.assertIsNone(result); self.assertEqual(stats['converted'], 0)

    def test_invalid_or_duplicate_json_never_returns_partial_edits(self):
        for raw in (b'{"1":{"id":1,"check":[[7,9001,3,30]],}}',
                    b'{"1":{"id":1,"check":[[7,9001,3,30]]},}',
                    b'{"1":{"id":1,"check":[[7,9001,3,30]],"id":1}}',
                    b'{"1":{"id":1,"check":[[7,9001,3,30]]},"1":{"id":1}}',
                    b'{"1":{"id":1,"check":[[7,9001,3,30]]}} extra',
                    b'{"bad":{"id":true,"check":[[7,9001,3,30]]}}',
                    b'{"0":{"id":false,"check":[[7,9001,3,30]]}}',
                    b'{"1":{"id":1,"check":[[7,9001,3,1e999]]}}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                m.scan_bytes(raw, {'check'})

    def test_foreign_numeric_tokens_do_not_need_reserialization(self):
        raw = b'{"1":{"id":1,"check":[[7,9001,3,30], [1163,9,1e99,123456789012345678901234567890]]}}'
        result, stats = m.scan_bytes(raw, {'check'})
        self.assertEqual(stats['converted'], 1)
        self.assertIn(b'[1163,9,1e99,123456789012345678901234567890]', result)

    def test_scientific_notation_matches_only_owned_numeric_values(self):
        raw = b'{"1":{"id":1,"check":[[40e-1,90010e-1,101,30],[70e-1,90020e-1,3,30]],"future":[[40e-1,90010e-1,101,30]]}}'
        result, stats = m.scan_bytes(raw, {'check'})
        self.assertEqual(stats['converted'], 2)
        self.assertEqual(json.loads(result)['1']['check'][1], [7, -1, 3, 30])
        self.assertIn(b'"future":[[40e-1,90010e-1,101,30]]', result)
        foreign = b'{"1":{"id":1,"check":[[1163e0,90010e-1,3,30]]}}'
        self.assertIsNone(m.scan_bytes(foreign, {'check'})[0])

    def test_event_social_mirrors_change_only_when_table_contract_opts_in(self):
        raw = b'{"7":{"id":7,"condition":[[7,9001,3,30]],"studioSocial":{"conditions":[[7,9001,3,30]],"entryConditions":[[7,9002,3,40]],"effects":[[1163, 2, 9.000]],"future":{"conditions":[[7,9001,3,30]]}}}}'
        ordinary, stats = m.scan_bytes(raw, {'condition'})
        self.assertEqual(stats['converted'], 1)
        self.assertIn(b'"conditions":[[7,9001,3,30]]', ordinary)
        revised, stats = m.scan_bytes(raw, {'condition'}, include_social=True)
        self.assertEqual(stats['converted'], 3)
        self.assertEqual(revised, raw.replace(b'"condition":[[7,9001,3,30]]', b'"condition":[[7, 1, 3, 30.0]]')
                         .replace(b'"conditions":[[7,9001,3,30]]', b'"conditions":[[7, 1, 3, 30.0]]', 1)
                         .replace(b'"entryConditions":[[7,9002,3,40]]', b'"entryConditions":[[7, -1, 3, 40.0]]'))
        self.assertIn(b'"future":{"conditions":[[7,9001,3,30]]}', revised)


class NativeConditionDiskTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        environment = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root / 'Cache'),
                                              'STUDIO_USER_DATA_ROOT': str(self.root / 'User'),
                                              'STUDIO_BACKUP_ROOT': str(self.root / 'Backups')})
        environment.start(); self.addCleanup(environment.stop)
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game',
                                  asset_settings_path=self.root / 'assets.json', migrate_cache=False)
        self.addCleanup(self.store.close)
        self.project = self.store.project(self.store.create('原生条件自动修复')['id'])
        self.cfg = self.project.path / 'Cfgs/zh-cn'
        self.talk = self.cfg / 'TalkCfg.json'
        self.source = b'{"7":{"id":7,"content":"before","check":[[7,9001,3,30],[7,9006,3,30]],"effect":[[1163,2,9,0.5]]}}'
        self.talk.write_bytes(self.source)

    def test_transaction_backups_original_and_warm_cache_skips_byte_reads(self):
        unrelated = self.cfg / 'ItemCfg.json'
        original_item = b'{"3":{"id":3,"future":[[7,9001,3,30]],"name":"item"}}'
        unrelated.write_bytes(original_item)
        previous = self.store.revision(self.project)
        with patch.object(self.store, 'commit', wraps=self.store.commit) as commit:
            result = m.repair(self.store, self.project.id, b)
        self.assertEqual(result['converted'], 1)
        self.assertEqual(result['unresolvedCount'], 1)
        self.assertNotEqual(previous, self.store.revision(self.project))
        self.assertTrue(commit.call_args.kwargs['raw'])
        self.assertEqual(set(commit.call_args.args[1]), {'Cfgs/zh-cn/TalkCfg.json'})
        self.assertEqual((Path(result['backup']) / 'Cfgs/zh-cn/TalkCfg.json').read_bytes(), self.source)
        self.assertEqual(unrelated.read_bytes(), original_item)
        self.assertEqual(b.read_json(self.talk)['7']['effect'], [[1163,2,9,0.5]])
        with (patch.object(Path, 'read_bytes', side_effect=AssertionError('warm files must not be read')),
              patch.object(self.store, 'commit', side_effect=AssertionError('no repeated commit'))):
            again = m.repair(self.store, self.project.id, b)
        self.assertEqual(again['converted'], 0)
        self.assertEqual(again['unresolvedCount'], 1)
        self.assertIsNone(again['backup'])

    def test_external_write_during_scan_keeps_external_data_and_no_commit(self):
        original_scan = m.scan_bytes
        external = self.source.replace(b'before', b'external')
        def scan(raw, fields):
            result = original_scan(raw, fields)
            b.atomic_write(self.talk, external)
            return result
        with (patch.object(m, 'scan_bytes', side_effect=scan),
              patch.object(self.store, 'commit', side_effect=AssertionError('conflict must not commit')),
              self.assertRaises(b.ApiError) as failure):
            m.repair(self.store, self.project.id, b)
        self.assertEqual(failure.exception.code, 'conflict')
        self.assertEqual(self.talk.read_bytes(), external)

    def test_bad_table_is_preserved_and_its_warning_is_cached(self):
        broken = self.source[:-1] + b','
        self.talk.write_bytes(broken)
        first = m.repair(self.store, self.project.id, b)
        self.assertIsNone(first['backup']); self.assertEqual(self.talk.read_bytes(), broken)
        self.assertTrue(first['warnings'])
        with patch.object(m, 'scan_bytes', side_effect=AssertionError('unchanged corrupt file must be cached')):
            again = m.repair(self.store, self.project.id, b)
        self.assertEqual(first['warnings'], again['warnings'])

    def test_verified_text_save_advances_marker_without_rescan(self):
        m.repair(self.store, self.project.id, b)
        before = b.file_fingerprint(self.talk)
        revised = self.talk.read_bytes().replace(b'before', b'new text')
        b.atomic_write(self.talk, revised)
        after = b.file_fingerprint(self.talk)
        m.verified_text_saved(self.project, self.talk, before, after, b)
        with patch.object(m, 'scan_bytes', side_effect=AssertionError('verified content only write must remain warm')):
            result = m.repair(self.store, self.project.id, b)
        self.assertEqual(result['converted'], 0); self.assertEqual(result['unresolvedCount'], 1)


if __name__ == '__main__':
    unittest.main()
