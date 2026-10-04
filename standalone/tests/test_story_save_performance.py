"""Snapshot sharing and graph memoization retain the existing ownership oracle."""
import copy
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import event_ownership
import server as b


class StorySavePerformanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        env = patch.dict(os.environ, {'STUDIO_USER_DATA_ROOT': str(root / 'User'), 'STUDIO_CACHE_ROOT': str(root / 'Cache'),
                                     'STUDIO_BACKUP_ROOT': str(root / 'Backups')})
        env.start(); self.addCleanup(env.stop)
        self.store = b.StudioStore(root / 'Mods', root / 'Workshop', root / 'Game', asset_settings_path=root / 'assets.json', migrate_cache=False)
        self.addCleanup(self.store.close)
        self.project = self.store.project(self.store.create('图缓存验证')['id'])
        self.cfg = self.project.path / 'Cfgs/zh-cn'
        self.events = {'1': {'id': 1, 'talkId': [1001]}}
        self.talks = {'1001': {'id': 1001, 'content': '原文', 'nextTalk': [1002], 'future': {'keep': [1, 2]}},
                      '1002': {'id': 1002, 'content': '后续', 'nextTalk': []},
                      '3001': {'id': 3001, 'content': '独立对话', 'nextTalk': []}}
        self.write('EvtCfg', self.events); self.write('TalkCfg', self.talks)

    def write(self, table, rows):
        (self.cfg / (table + '.json')).write_bytes(b.json_bytes(rows))

    def save(self, extra):
        return self.store.save({'projectId': self.project.id, 'revision': self.store.revision(self.project), **extra})

    def test_effect_reuses_one_verified_owner_result_and_returns_mutable_copies(self):
        events = {**self.events, '2': {'id': 2, 'talkId': []}}
        with patch.object(event_ownership, 'ownership', wraps=event_ownership.ownership) as owner:
            first = self.save({'events': events})
            self.assertEqual(owner.call_count, 1)
            row = copy.deepcopy(self.talks['1001']); row['effect'] = [[1, 3, 7]]
            second = self.save({'talkPatch': {'version': 1, 'upsert': {'1001': row}, 'deleted': []}})
            self.assertEqual(owner.call_count, 1)
        self.assertEqual(first['talkOwners'], second['talkOwners'])
        second['talkOwners']['1001'].append(99)
        third = self.save({'eventGrades': {'1': 1}})
        self.assertEqual(third['talkOwners']['1001'], [1])
        self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json')['1001']['future'], {'keep': [1, 2]})

    def test_new_empty_event_still_changes_band_and_drops_display_only_retention(self):
        state = self.project.path / 'StudentAgeStudio/editor-state.json'
        state.parent.mkdir(exist_ok=True)
        state.write_bytes(b.json_bytes({'talkOwners': {'3001': [1]}}))
        events = {**self.events, '3': {'id': 3, 'talkId': []}}
        result = self.save({'events': events})
        expected = event_ownership.ownership(events, self.talks, {}, {}, {'3001': [1]}, band=set(events))
        self.assertEqual(result['talkOwners'], expected)
        self.assertNotIn('3001', result['talkOwners'])

    def test_shared_graph_change_matches_existing_retention_oracle(self):
        events = {**self.events, '2': {'id': 2, 'talkId': [1002]}}
        first = self.save({'events': events})
        row = copy.deepcopy(self.talks['1001']); row['nextTalk'] = []
        result = self.save({'talkPatch': {'version': 1, 'upsert': {'1001': row}, 'deleted': []}})
        expected = event_ownership.ownership(events, {**self.talks, '1001': row}, {}, {}, first['talkOwners'], band=set(events))
        self.assertEqual(result['talkOwners'], expected)
        self.assertEqual(result['talkOwners']['1002'], [2])

    def test_malformed_disk_owners_are_validated_before_cache_use(self):
        state = self.project.path / 'StudentAgeStudio/editor-state.json'
        state.parent.mkdir(exist_ok=True)
        for owners in ({'1001': None}, {'1001': True}, {'1001': 'bad'}, {'1001': [False]}, None, []):
            with self.subTest(owners=owners):
                state.write_bytes(b.json_bytes({'talkOwners': owners, 'future': {'keep': [1, 2]}}))
                result = self.save({'eventGrades': {'1': 1}})
                self.assertEqual(result['talkOwners']['1001'], [1])
                self.assertEqual(b.read_json(state)['future'], {'keep': [1, 2]})

    def test_lighting_mutation_detaches_shared_row_before_normalization(self):
        talks = copy.deepcopy(self.talks)
        talks['1001'].update(roleIds=[0], studioLighting={'0': False})
        self.write('TalkCfg', talks)
        original = self.store._same_story_edges
        def check(before, after, *args):
            self.assertEqual(before['TalkCfg.json']['1001']['studioLighting'], {'0': False})
            self.assertEqual(after['TalkCfg.json']['1001']['studioLighting'], {})
            return original(before, after, *args)
        with patch.object(self.store, '_same_story_edges', side_effect=check):
            self.save({'events': self.events})
        self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json')['1001']['studioLighting'], {})

    def test_event_gift_unbind_persists_metadata_without_owner_or_order_change(self):
        self.write('PersonCfg', {'3': {'id': 3, 'name': '人物'}})
        native = {'8': {'id': 8, 'item': 10, 'npc': [3], 'talkId': [[1001]], 'type': [0],
                        'cond': [[111, -1, 1, -1, 0]], 'future': {'keep': [1, 2]}}}
        event = {'id': 1, 'type': 110, 'title': '送礼事件', 'talkId': [1001], 'maxcount': 1,
                 'rate': 1, 'studioGiftCounterSlot': -1, 'condition': [],
                 'studioGiftBindings': [{'id': 8, 'index': 0, 'npc': 3}]}
        self.save({'events': {'1': event}, 'giftEvents': native, 'order': [1001, 1002, 3001]})
        state_path = self.project.path / 'StudentAgeStudio/editor-state.json'
        previous = b.read_json(state_path)
        folder = previous['externalDialogueFolders']['gift-event-1']
        self.assertEqual(folder['giftEventId'], 1)
        self.assertTrue(any(use.get('eventGiftBinding') for use in folder['uses']))
        gift_bytes = (self.cfg / 'GiftEvtCfg.json').read_bytes()
        event['studioGiftBindings'] = []
        result = self.save({'events': {'1': event}})
        actual = b.read_json(state_path)
        self.assertEqual(actual['talkOwners'], previous['talkOwners'])
        self.assertEqual(actual['order'], previous['order'])
        folder = actual['externalDialogueFolders']['gift-event-1']
        self.assertNotIn('giftEventId', folder)
        self.assertFalse(any(use.get('eventGiftBinding') for use in folder['uses']))
        self.assertEqual((self.cfg / 'GiftEvtCfg.json').read_bytes(), gift_bytes)
        self.assertEqual(b.read_json(Path(result['backup']) / 'StudentAgeStudio/editor-state.json'), previous)
        self.assertEqual(b.read_json(self.cfg / 'EvtCfg.json')['1']['studioGiftBindings'], [])

    def test_repaired_event_id_keeps_cascade_snapshot_and_writes_native_references(self):
        talks = copy.deepcopy(self.talks)
        talks['1001']['option'] = [5]
        self.write('TalkCfg', talks)
        self.write('OptionCfg', {'5': {'id': 5, 'talkId': [1002]}})
        self.write('ActionEvtCfg', {'7': {'id': 7, 'evts': [1], 'future': {'keep': True}}})
        self.write('ActionCfg', {'8': {'id': 8, 'evtId': 1, 'future': ['keep']}})
        result = self.save({'events': {'1': {'id': 2, 'talkId': []}}})
        self.assertEqual(b.read_json(self.cfg / 'EvtCfg.json'), {'2': {'id': 2, 'talkId': []}})
        self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json'), {'3001': talks['3001']})
        self.assertEqual(b.read_json(self.cfg / 'OptionCfg.json'), {})
        self.assertEqual(b.read_json(self.cfg / 'ActionEvtCfg.json')['7'],
                         {'id': 7, 'evts': [], 'future': {'keep': True}})
        self.assertEqual(b.read_json(self.cfg / 'ActionCfg.json')['8'],
                         {'id': 8, 'evtId': 0, 'future': ['keep']})
        self.assertTrue(any('EvtCfg.json' in warning and '2' in warning for warning in result['warnings']))

    def test_complex_snapshot_guards_cover_all_in_place_normalizers(self):
        maps = {'TalkCfg.json': self.talks, 'EvtCfg.json': self.events, 'OptionCfg.json': {}}
        base = {'events': self.events}
        self.assertTrue(self.store._simple_story_snapshot(self.project, base, maps, {}))
        for extra in ({'deletedIds': [1002]}, {'idMappings': {'TalkCfg': {'1001': 1003}}},
                      {'replacements': {'1001': [1002]}}, {'audioCues': {}},
                      {'externalDialogueFolders': {}}, {'giftEvents': {}}, {'events': {}},
                      {'premises': {'1': {'eventId': 1, 'slot': 7}}}):
            with self.subTest(extra=extra):
                self.assertFalse(self.store._simple_story_snapshot(self.project, {**base, **extra}, maps, {}))
        for state in ({'premises': {'1': {'eventId': 1, 'slot': 7}}}, {'deletedPremisePairs': [[1, 7]]}):
            self.assertFalse(self.store._simple_story_snapshot(self.project, base, maps, state))
        audio = self.project.path / 'StudentAgeStudio/audio-cues.json'
        audio.parent.mkdir(exist_ok=True); audio.write_bytes(b.json_bytes({'bgm': [{'audioId': 1, 'talkIds': [1001]}]}))
        self.assertFalse(self.store._simple_story_snapshot(self.project, base, maps, {}))

    def test_external_change_invalidates_cache_and_cannot_hide_restored_mtime(self):
        self.save({'events': self.events})
        previous_revision = self.store.revision(self.project)
        path = self.cfg / 'TalkCfg.json'; stat = path.stat()
        external = b.read_json(path); external['1001']['nextTalk'] = []
        path.write_bytes(b.json_bytes(external)); os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with self.assertRaises(b.ApiError) as caught:
            self.store.save({'projectId': self.project.id, 'revision': previous_revision, 'eventGrades': {'1': 1}})
        self.assertEqual(caught.exception.code, 'conflict')
        with patch.object(event_ownership, 'ownership', wraps=event_ownership.ownership) as owner:
            self.save({'eventGrades': {'1': 1}})
            self.assertGreater(owner.call_count, 0)

    def test_cache_signature_covers_previous_band_anchor_options_and_folders(self):
        revision = self.store.revision(self.project)
        def query(**changes):
            args = dict(events=self.events, talks=self.talks, options={}, folders={}, previous={}, band={'1'}, anchor=None)
            args.update(changes)
            expected = event_ownership.ownership(**args)
            self.assertEqual(self.store._story_ownership(self.project, revision, **args), expected)
        query(); query(previous={'3001': [1]}); query(band=set())
        query(anchor=[3001], previous={'3001': [1]})
        query(options={'100': {'id': 100, 'talkId': [3001]}})
        query(folders={'1001:100': {'parentTalkId': 1001, 'talkIds': [3001]}})
        self.assertEqual(len(self.store._story_ownership_cache['previous']), 2)

    def test_canonical_previous_alias_matches_oracle_for_cycles_and_shared_paths(self):
        rng = random.Random(701)
        revision = self.store.revision(self.project)
        for _ in range(24):
            talks = {str(i): {'id': i, 'nextTalk': rng.sample(range(1, 25), rng.randrange(3))} for i in range(1, 25)}
            events = {str(i): {'id': i, 'talkId': [rng.randrange(1, 25)]} for i in range(1, 5)}
            previous = {str(i): rng.sample(range(1, 5), rng.randrange(3)) for i in range(1, 25)}
            result = self.store._story_ownership(self.project, revision, events, talks, {}, {}, previous, band=set(events))
            self.assertEqual(event_ownership.ownership(events, talks, {}, {}, result, band=set(events)), result)
            self.assertEqual(self.store._story_ownership(self.project, revision, events, talks, {}, {}, result, band=set(events)), result)


if __name__ == '__main__':
    unittest.main()
