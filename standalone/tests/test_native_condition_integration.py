"""Actual open/save transactions and reusable groups, in disposable Mods only."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
import native_condition_migration as m
from condition_library import UserConditionPresets, collect


class NativeConditionIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {'STUDIO_USER_DATA_ROOT': str(self.root / 'User'),
                                     'STUDIO_CACHE_ROOT': str(self.root / 'Cache')})
        env.start(); self.addCleanup(env.stop)
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game',
                                  asset_settings_path=self.root / 'assets.json')
        self.addCleanup(self.store.close)
        self.ident = self.store.create('Native conditions QA')['id']
        self.project = self.store.project(self.ident)
        self.cfg = self.project.path / 'Cfgs/zh-cn'

    def write(self, table, rows):
        (self.cfg / (table + '.json')).write_bytes(b.json_bytes(rows))

    def test_personal_presets_repair_back_up_and_keep_unresolved(self):
        path = self.root / 'personal/condition-presets.json'
        path.parent.mkdir()
        data = {'future': {'keep': 1}, 'entries': [
            {'key': 'a', 'title': 'Old equals', 'rows': [[7, 9005, 3, 30], [1163, 5, 1]], 'unknown': 9},
            {'key': 'b', 'title': 'Old not equals', 'rows': [[7, 9006, 3, 30]]}]}
        raw = b.json_bytes(data); path.write_bytes(raw)
        presets = UserConditionPresets(path, b)
        result = presets.access()
        self.assertEqual(result['entries'][0]['rows'], [[7, 1, 3, 30], [7, -1, 3, m.successor(30)], [1163, 5, 1]])
        self.assertEqual(result['entries'][1], data['entries'][1])
        self.assertEqual(Path(result['backup']).read_bytes(), raw)
        self.assertEqual(b.read_json(path)['future'], data['future'])
        self.assertIn('手动修改', ' '.join(result['warnings']))
        before = path.read_bytes()
        again = presets.access()
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn('backup', again)
        self.assertIn('手动修改', ' '.join(again['warnings']))

    def test_catalog_and_reuse_never_reintroduce_owned_commands(self):
        owned = {'label': 'old', 'template': [7, 9001, 3, 30], 'match': {'0': 7, '1': 9001}}
        plugin = {'label': 'UP', 'template': [1163, 9001, 3, 30], 'match': {'0': 1163, '1': 9001}}
        catalog = {'commands': {'condition': [owned, plugin], 'effect': [copy.deepcopy(owned)]}}
        with patch.object(self.store, 'catalog', return_value=catalog):
            result = self.store.command_catalog(self.ident)['commands']
        self.assertFalse(any(m.is_owned(t['template']) for t in result['condition']))
        self.assertIn(plugin, result['condition'])
        self.assertIn(owned, result['effect'])
        self.assertEqual(catalog['commands']['condition'][0], owned)
        rows = {'1': {'id': 1, 'cond': [[7, 9001, 3, 30], [1163, 1, 2]],
                      'future': [7, 9001, 3, 30]}}
        before = copy.deepcopy(rows)
        self.assertEqual(collect('GiftEvtCfg', rows)[0]['rows'], [[7, 1, 3, 30], [1163, 1, 2]])
        self.assertEqual(rows, before)

    def test_text_save_advances_condition_cache_without_rescanning(self):
        self.write('TalkCfg', {'1': {'id': 1, 'content': 'before', 'check': [[7, 9006, 3, 30]],
                                   'nextTalk': [], 'effect': []}})
        first = m.repair(self.store, self.ident, b)
        self.assertEqual(first['unresolvedCount'], 1)
        row = b.read_json(self.cfg / 'TalkCfg.json')['1']; row['content'] = 'after'
        with patch.object(m, 'scan_bytes', side_effect=AssertionError('unnecessary rescan')):
            saved = self.store.save({'projectId': self.ident, 'revision': self.store.revision(self.project),
                                     'talkPatch': {'version': 1, 'upsert': {'1': row}, 'deleted': []}})
            second = m.repair(self.store, self.ident, b)
        self.assertTrue(saved['ok'])
        self.assertEqual(second['unresolvedCount'], 1)
        self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json')['1'], row)

    def test_old_submitted_draft_cannot_restore_repairable_opcodes(self):
        self.write('EvtCfg', {'7': {'id': 7, 'talkId': [7001], 'condition': []}})
        self.write('TalkCfg', {'7001': {'id': 7001, 'content': 'before', 'check': [],
                                      'nextTalk': [], 'effect': [[1163, 5, 1]]}})
        row = b.read_json(self.cfg / 'TalkCfg.json')['7001']
        row.update(content='old browser draft', check=[[7, 9005, 3, 30], [7, 9006, 3, 50]])
        before = copy.deepcopy(row)
        with patch.object(m, 'scan_bytes', side_effect=AssertionError('scanned table during delta save')):
            saved = self.store.save({'projectId': self.ident, 'revision': self.store.revision(self.project),
                                     'talkPatch': {'version': 1, 'upsert': {'7001': row}, 'deleted': []}})
        actual = b.read_json(self.cfg / 'TalkCfg.json')['7001']
        self.assertEqual(actual['check'], [[7, 1, 3, 30], [7, -1, 3, m.successor(30)], [7, 9006, 3, 50]])
        self.assertEqual(actual['effect'], [[1163, 5, 1]])
        self.assertEqual(row, before)
        self.assertIn('手动修改', ' '.join(saved['warnings']))
        event = {'id': 7, 'condition': [[7, 9001, 3, 30]],
                 'studioSocial': {'conditions': [[7, 9001, 3, 30]],
                                  'entryConditions': [[7, 9002, 3, 50]],
                                  'future': [[7, 9001, 3, 30]]}}
        payload, notes = b.native_submission_payload({'events': {'7': event}, 'future': event})
        converted = payload['events']['7']
        self.assertEqual(converted['condition'], converted['studioSocial']['conditions'])
        self.assertEqual(converted['studioSocial']['entryConditions'], [[7, -1, 3, 50]])
        self.assertIs(payload['future'], event)
        self.assertIs(converted['studioSocial']['future'], event['studioSocial']['future'])

    def test_http_open_repairs_before_segment_baseline_then_gift_save_skips_migration(self):
        self.write('EvtCfg', {'7': {'id': 7, 'talkId': [1], 'condition': [[7, 9001, 3, 30]]}})
        self.write('TalkCfg', {'1': {'id': 1, 'content': 'Native QA', 'nextTalk': [],
                                   'check': [[7, 9005, 3, 30]], 'effect': [[1163, 5, 1]],
                                   'future': {'keep': [4, 9001, 101, 30]}}})
        self.write('GiftEvtCfg', {'20001': {'id': 20001, 'item': 10, 'npc': [3],
                                          'cond': [[7, 9002, 3, 50]], 'talkId': [[1]],
                                          'type': [], 'redpoint': 1}})
        original_talk = (self.cfg / 'TalkCfg.json').read_bytes()
        host = b.StudioServer(('127.0.0.1', 0), self.store)
        worker = threading.Thread(target=host.serve_forever, daemon=True); worker.start()
        self.addCleanup(host.server_close)
        self.addCleanup(host.shutdown)
        self.addCleanup(host.media_warmup.close)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(route, payload=None):
            req = urllib.request.Request(host.origin + route,
                data=b.json_bytes(payload) if payload is not None else None,
                headers={'X-Studio-Token': host.token, 'Content-Type': 'application/json'})
            with opener.open(req, timeout=30) as response: return json.load(response)
        data = request('/api/project?' + urllib.parse.urlencode({'id': self.ident, 'talkStorage': 'segmented'}))
        token = data['segmentedTalks']['generation']
        gen = self.store.talk_segments.get(self.ident, token)
        row = json.loads(gen.page(['1'])['rows'][0][1])
        self.assertEqual(row['check'], [[7, 1, 3, 30], [7, -1, 3, m.successor(30)]])
        self.assertEqual(row['future'], {'keep': [4, 9001, 101, 30]})
        self.assertEqual(row['effect'], [[1163, 5, 1]])
        self.assertEqual(data['events']['7']['condition'], [[7, 1, 3, 30]])
        backups = list((self.project.path / 'StudentAgeStudio/Backups').glob('*/Cfgs/zh-cn/TalkCfg.json'))
        self.assertTrue(any(p.read_bytes() == original_talk for p in backups))
        revision = self.store.revision(self.project)
        data2 = request('/api/project?' + urllib.parse.urlencode({'id': self.ident, 'talkStorage': 'segmented'}))
        self.assertEqual(data2['revision'], revision)
        self.assertEqual(data2['segmentedTalks']['generation'], token)
        gift = b.read_json(self.cfg / 'GiftEvtCfg.json')
        self.assertEqual(gift['20001']['cond'], [[7, -1, 3, 50]])
        gift['20001']['redpoint'] = 0
        # Gift and other normal saves must never enter the whole-Mod migration path.
        with patch.object(m, 'repair', side_effect=AssertionError('migration in save')):
            saved = request('/api/table-save', {'projectId': self.ident, 'revision': revision,
                                               'name': 'GiftEvtCfg', 'rows': gift, 'scope': 'local'})
        self.assertTrue(saved['ok'])
        self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json')['1'], row)


if __name__ == '__main__': unittest.main()
