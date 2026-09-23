"""Love confession/dating and gift events as data-driven table features.

Native semantics and complete round trips for the love/gift editors.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
import gameplay_features

LOVE_TABLES = ['LoveVindicateCfg', 'LoveVindicateRateCfg', 'LoveActionCfg', 'LoveBadmintonCfg',
               'LoveBreakfastCfg', 'LoveDrawCfg', 'LoveRibbonCfg', 'WishCfg']
FEATURE_IDS = ['love-confession', 'love-actions', 'love-badminton', 'love-breakfast',
               'love-draw', 'love-wish', 'gift-events']


def load_json(name):
    return json.loads((Path(__file__).resolve().parents[1] / name).read_text(encoding='utf-8'))


class LoveGiftConfigTests(unittest.TestCase):
    def test_features_reference_paged_schemas(self):
        features = {entry['id']: entry for entry in load_json('workshop-features.json')}
        schemas = load_json('catalog-schema.json')['schemas']
        for ident in FEATURE_IDS:
            self.assertIn(ident, features, ident)
            entry = features[ident]
            self.assertEqual(entry['entry']['kind'], 'table')
            for table in entry['tables']:
                self.assertIn(table, schemas, table)
                self.assertTrue(schemas[table].get('nativePage'), table)
        covered = [table for ident in FEATURE_IDS for table in features[ident]['tables']]
        for table in LOVE_TABLES + ['GiftEvtCfg']:
            self.assertIn(table, covered, table)
            self.assertTrue(schemas[table].get('allowIncomplete'), table)

    def test_gameplay_names_cover_new_tables(self):
        for table in LOVE_TABLES + ['GiftEvtCfg']:
            self.assertIn(table, gameplay_features.NAMES, table)


class LoveGiftTableTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root / 'Cache')})
        env.start()
        self.addCleanup(env.stop)
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game')
        self.ident = self.store.create('恋爱送礼')['id']
        self.project = self.store.project(self.ident)

    def save_rows(self, name, rows):
        return self.store.table_save({'projectId': self.ident, 'revision': self.store.revision(self.project),
                                      'name': name, 'rows': rows, 'scope': 'local'})

    def test_features_listed_in_workshop_info(self):
        info = self.store.workshop_info(self.ident)
        listed = {feature['id'] for feature in info['features']}
        for ident in FEATURE_IDS:
            self.assertIn(ident, listed, ident)

    def test_breakfast_gift_wish_roundtrip(self):
        breakfast = {'10001': {'id': 10001, 'npc': 3, 'item': 10, 'msgIcon': None,
                               'msgTxt': '早安', 'cond': [], 'weight': 1.0, 'futureField': {'text': '保留扩展'}}}
        gift = {'20001': {'id': 20001, 'item': 10, 'npc': [3], 'cond': [],
                          'talkId': [[9001]], 'type': [], 'redpoint': 1}}
        wish = {'30001': {'id': 30001, 'name': '心想事成', 'effect': [[1.0, 11.0, 1.0, 1.0]], 'tag': 1}}
        for name, rows in (('LoveBreakfastCfg', breakfast), ('GiftEvtCfg', gift), ('WishCfg', wish)):
            result = self.save_rows(name, rows)
            self.assertTrue(result['ok'], name)
            table = self.store.table(self.ident, name)
            for key, row in rows.items():
                self.assertEqual(table['rows'][key], row, (name, key))
            self.assertIn(key, table['localIds'] if isinstance(table.get('localIds'), list) else table['rows'])

    def test_probability_parameter_warning_can_be_confirmed(self):
        import save_review
        payload = {'projectId': self.ident, 'revision': self.store.revision(self.project),
                   'name': 'LoveVindicateRateCfg', 'scope': 'local',
                   'rows': {'101': {'id': 101, 'favorParms': [], 'attrParms': [.3, .01, 1, 1, 1]}}}
        with self.assertRaises(b.ApiError) as raised:
            save_review.perform(self.store.table_save, payload, b.ApiError)
        self.assertEqual(raised.exception.code, 'save_warnings')
        self.assertFalse((self.project.path / 'Cfgs/zh-cn/LoveVindicateRateCfg.json').exists())
        payload['_confirmedSaveWarnings'] = raised.exception.warnings
        result = save_review.perform(self.store.table_save, payload, b.ApiError)
        self.assertTrue(result['ok'])

    def test_native_schema_contracts(self):
        schemas = load_json('catalog-schema.json')['schemas']
        for name in ['LoveVindicateRateCfg', 'LoveBadmintonCfg']:
            self.assertEqual(schemas[name]['identityTable'], 'PersonCfg')
        for name in ['LoveDrawCfg', 'LoveActionCfg', 'LoveVindicateCfg']:
            self.assertTrue(schemas[name]['editExistingOnly'])
        self.assertFalse(schemas['LoveGreetingCfg']['nativePage'])
        self.assertTrue({'img', 'video', 'name', 'cond', 'talkId'} <= {f['name'] for f in schemas['LoveDrawCfg']['fields']})

    def test_invalid_paths_and_stale_revision_do_not_write(self):
        for name in ['../LoveBreakfastCfg', 'LoveBreakfastCfg/../../outside']:
            with self.assertRaises(b.ApiError):
                self.save_rows(name, {})
        payload = {'projectId': self.ident, 'revision': 'stale', 'name': 'LoveBreakfastCfg',
                   'rows': {}, 'scope': 'local'}
        with self.assertRaises(b.ApiError) as raised:
            self.store.table_save(payload)
        self.assertEqual(raised.exception.code, 'conflict')
        self.assertFalse((self.project.path / 'Cfgs/zh-cn/LoveBreakfastCfg.json').exists())

    def test_all_new_tables_preserve_complete_records(self):
        samples = {
            'LoveVindicateRateCfg': {'id': 101, 'favorParms': [.18, .01, 1, 1, 1], 'attrParms': [.3, .01, 1, 1, 1]},
            'LoveBadmintonCfg': {'id': 101, **{k: ['荀彧：接球！'] for k in ['faqiu', 'score', 'loseScore', 'hit', 'opHit', 'heavyHit']}},
            'LoveDrawCfg': {'id': 10101, 'name': '画作', 'img': 'draw', 'video': 'draw-video', 'cond': [], 'talkId': [10101001]},
            'LoveRibbonCfg': {'id': 1000000, 'names': ['小雅'], 'content': '平安喜乐', 'weight': 2.0, 'cond': []},
        }
        for name, row in samples.items():
            row['unknownField'] = {'nested': [1, 'preserve']}
            self.save_rows(name, {str(row['id']): row})
            self.assertEqual(self.store.table(self.ident, name)['localRows'][str(row['id'])], row)

    def test_allocate_uses_default_block(self):
        ident = self.store.record_ids.allocate('LoveBreakfastCfg', {})
        self.assertGreaterEqual(ident, 1000000)

    def test_vindicate_and_action_roundtrip(self):
        vindicate = {'40001': {'id': 40001, 'target': 0.8, 'txt': '我喜欢你', 'color': '#fb0202'}}
        actions = {'50001': {'id': 50001, 'name': '看电影', 'funcId': 602}}
        for name, rows in (('LoveVindicateCfg', vindicate), ('LoveActionCfg', actions)):
            self.assertTrue(self.save_rows(name, rows)['ok'], name)
            table = self.store.table(self.ident, name)
            self.assertEqual(table['rows'][next(iter(rows))]['id'], rows[next(iter(rows))]['id'])


if __name__ == '__main__':
    unittest.main()
