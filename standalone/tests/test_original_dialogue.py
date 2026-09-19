"""Original dialogue lines reach the editor only through the events that use them."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
import original_dialogue
import original_mode
from storage_paths import game_cache


def talk(i, content, nxt=(), option=()):
    return {'id': i, 'content': content, 'nextTalk': list(nxt), 'nextTalk2': [], 'option': list(option),
            'check': [], 'effect': [], 'roleIds': [3], 'roles': []}


ORIGINAL_TALKS = {'1001001': talk(1001001, '原版一', [1001002]), '1001002': talk(1001002, '原版二', option=[100101]),
                  '1001003': talk(1001003, '原版三'), '1002001': talk(1002001, '原版乙'), '1003001': talk(1003001, '原版丙'),
                  '1004001': talk(1004001, '无人引用')}
ORIGINAL_OPTIONS = {'100101': {'id': 100101, 'content': '选A', 'talkId': [1001003], 'talkId2': [], 'effect': [], 'precondition': []}}
ORIGINAL_EVENTS = {'1001': {'id': 1001, 'title': '原版事件甲', 'type': 1, 'talkId': [1001001], 'rate': 1, 'maxcount': 1, 'effect': [], 'condition': []},
                   '1002': {'id': 1002, 'title': '原版事件乙', 'type': 1, 'talkId': [1002001], 'rate': 1, 'maxcount': 1, 'effect': [], 'condition': []},
                   '1003': {'id': 1003, 'title': '原版事件丙', 'type': 1, 'talkId': [1003001], 'rate': 1, 'maxcount': 1, 'effect': [], 'condition': []}}


class OriginalDialogueTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root / 'Cache'), 'STUDIO_USER_DATA_ROOT': str(self.root / 'User')})
        env.start(); self.addCleanup(env.stop)
        (self.root / 'Game').mkdir()
        cache = game_cache(self.root / 'Game'); cache.mkdir(parents=True, exist_ok=True)
        # The catalog carries only ids for dialogue, exactly like extract_catalog writes it.
        (cache / 'game-catalog.json').write_text(json.dumps({'schemas': {'EvtCfg': {}}, 'tables': {'EvtCfg': ORIGINAL_EVENTS, 'PersonCfg': {'3': {'id': 3, 'name': '甲'}}},
                                                             'baseTalkIds': sorted(int(k) for k in ORIGINAL_TALKS)}, ensure_ascii=False), encoding='utf-8')
        original_dialogue.write(self.root / 'Game', ORIGINAL_TALKS, ORIGINAL_OPTIONS)
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game', asset_settings_path=self.root / 'assets.json')
        # Close the read-only SQLite handle before TemporaryDirectory cleanup:
        # Windows cannot unlink an open database file.
        self.addCleanup(self.store.close)
        self.ident = self.store.create('原版覆盖')['id']
        self.project = self.store.project(self.ident)
        self.cfg = self.project.path / 'Cfgs/zh-cn'
        self.write('EvtCfg', {'1001': {**ORIGINAL_EVENTS['1001'], 'title': '改过的甲'},
                              '1500000': {'id': 1500000, 'title': '自建', 'type': 1, 'talkId': [1500000001], 'rate': 1, 'maxcount': 1, 'effect': [], 'condition': []}})
        self.write('TalkCfg', {'1003001': talk(1003001, '模组改写的丙'), '1500000001': talk(1500000001, '自建一')})

    def write(self, name, rows):
        (self.cfg / (name + '.json')).write_bytes(b.json_bytes(rows))

    def test_store_reads_by_id_and_walks_links_without_local_rows(self):
        store = self.store.original_dialogue
        self.assertTrue(store.available())
        self.assertEqual(set(store.rows('TalkCfg', [1001001, '999'])), {'1001001'})
        talks, options = store.reachable([1001001], [], set(), set())
        self.assertEqual(set(talks), {'1001001', '1001002', '1001003'}); self.assertEqual(set(options), {'100101'})
        # A local override stops the walk: its own links are the caller's business.
        talks, options = store.reachable([1001001], [], {'1001002'}, set())
        self.assertEqual(set(talks), {'1001001'}); self.assertEqual(options, {})

    def test_catalog_is_prepared_only_with_the_dialogue_store(self):
        self.assertTrue(self.store.catalog_prepared())
        os.unlink(original_dialogue.path(self.root / 'Game'))
        self.assertFalse(self.store.catalog_prepared())

    def test_mod_overriding_an_original_event_loads_its_original_lines(self):
        data = self.store.load(self.ident)
        self.assertEqual(set(data['talks']), {'1003001', '1500000001', '1001001', '1001002', '1001003'})
        self.assertEqual(set(data['options']), {'100101'})
        self.assertEqual(data['talks']['1003001']['content'], '模组改写的丙')  # the local override wins
        self.assertEqual(set(data['localIds']['talks']), {'1003001', '1500000001'})
        self.assertEqual(set(data['catalogIds']['talks']), {'1001001', '1001002', '1001003', '1003001'})
        self.assertEqual(data['catalogIds']['events'], ['1001'])
        self.assertEqual(data['talkOwners']['1001003'], [1001])
        # The segmented path serves the same rows.
        descriptor = self.store.talk_segments.open(self.ident)
        self.assertEqual(set(descriptor['segmentedTalks']['ids']), set(data['talks']))

    def test_saving_unchanged_original_lines_writes_nothing_into_the_mod(self):
        data = self.store.load(self.ident)
        before = json.loads((self.cfg / 'TalkCfg.json').read_text(encoding='utf-8'))
        self.store.save({'projectId': self.ident, 'revision': data['revision'], 'talks': data['talks'], 'options': data['options']})
        after = json.loads((self.cfg / 'TalkCfg.json').read_text(encoding='utf-8'))
        self.assertEqual(set(after), set(before))
        self.assertFalse((self.cfg / 'OptionCfg.json').exists() and json.loads((self.cfg / 'OptionCfg.json').read_text(encoding='utf-8')))
        # An edited original line becomes an override; its untouched neighbours stay original.
        data = self.store.load(self.ident)
        talks = dict(data['talks']); talks['1001002'] = {**talks['1001002'], 'content': '改过的二'}
        self.store.save({'projectId': self.ident, 'revision': data['revision'], 'talks': talks})
        after = json.loads((self.cfg / 'TalkCfg.json').read_text(encoding='utf-8'))
        self.assertEqual(after['1001002']['content'], '改过的二'); self.assertNotIn('1001001', after)

    def test_corrupt_edits_open_as_empty_with_warning(self):
        with original_mode.scope(self.ident):
            target = self.project.path / 'StudentAgeStudio/original-edits.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'{"TalkCfg": "broken"}')
            data = self.store.load(self.ident)
            self.assertTrue(any('原版资源编辑记录损坏' in warning for warning in data['warnings']))
            # Writes stay fail-closed: the strict reader still refuses.
            with self.assertRaises(b.ApiError):
                original_mode.owned(self.store, self.project)

    def test_idle_connection_reopens_transparently(self):
        holder = self.store.original_dialogue
        self.assertTrue(holder.available())
        first = holder._connection
        with patch.object(original_dialogue.time, 'monotonic', return_value=holder._last_use + 1000):
            self.assertTrue(holder.available())
        self.assertIsNot(holder._connection, first)
        self.assertEqual(set(holder.rows('TalkCfg', [1001001])), {'1001001'})

    def test_original_mode_loads_only_opened_events_and_prefers_mod_overrides(self):
        with original_mode.scope(self.ident):
            data = self.store.load(self.ident)
            self.assertEqual(set(data['events']), {'1001', '1002', '1003'})
            self.assertEqual(data['talks'], {})  # nothing opened yet: the whole game is never loaded
            data = self.store.load(self.ident, ['1002', '1003'])
            self.assertEqual(set(data['talks']), {'1002001', '1003001'})
            self.assertEqual(data['talks']['1003001']['content'], '模组改写的丙')
            self.assertIn('1002001', data['localIds']['talks'])
            descriptor = self.store.talk_segments.open(self.ident, ['1002'])
            self.assertEqual(descriptor['segmentedTalks']['ids'], ['1002001'])


if __name__ == '__main__':
    unittest.main()
