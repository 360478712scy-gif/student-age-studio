"""Small-table saves keep working beside a JSON file above the parsing limit."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b


class LargeUnrelatedSaveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {
            'STUDIO_USER_DATA_ROOT': str(self.root / 'User'),
            'STUDIO_CACHE_ROOT': str(self.root / 'Cache'),
            'STUDIO_BACKUP_ROOT': str(self.root / 'Backups'),
        })
        env.start()
        self.addCleanup(env.stop)
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game',
                                  asset_settings_path=self.root / 'assets.json', migrate_cache=False)
        self.addCleanup(self.store.close)
        self.project = self.store.project(self.store.create('大表旁的保存')['id'])
        self.cfg = self.project.path / 'Cfgs/zh-cn'
        self.talk = self.cfg / 'TalkCfg.json'
        self.talk_bytes = b.json_bytes({'1': {'id': 1, 'content': 'A' * 5000}})
        self.talk.write_bytes(self.talk_bytes)
        self.gift = {'1500000': {'id': 1500000, 'item': 1300000, 'npc': [1], 'talkId': [[1]],
                                'type': [0], 'cond': [], 'futureField': {'keep': True}}}
        (self.cfg / 'GiftEvtCfg.json').write_bytes(b.json_bytes(self.gift))
        (self.cfg / 'ItemCfg.json').write_bytes(b.json_bytes({'1300000': {'id': 1300000, 'name': '旧礼物'}}))
        limit = patch.object(b, 'MAX_JSON', 1024)
        limit.start()
        self.addCleanup(limit.stop)
        self.assertGreater(len(self.talk_bytes), b.MAX_JSON)

    def save(self, table, rows):
        revision = self.store.revision(self.project)
        opened = []
        original_open = Path.open
        def tracked(path, *args, **kwargs):
            opened.append(path)
            return original_open(path, *args, **kwargs)
        with patch.object(b, 'read_json', wraps=b.read_json) as read, patch.object(Path, 'open', tracked):
            result = self.store.table_save({'projectId': self.project.id, 'revision': revision,
                                           'name': table, 'rows': rows, 'scope': 'local'})
        self.assertTrue(result['ok'])
        self.assertFalse(any(Path(call.args[0]) == self.talk for call in read.call_args_list))
        self.assertNotIn(self.talk, opened, 'warm small-table save must reuse the talk digest')
        self.assertEqual(self.talk.read_bytes(), self.talk_bytes)
        backup = Path(result['backup'])
        self.assertEqual(b.read_json(backup / 'transaction.json')['state'], 'committed')
        files = list((backup / 'Cfgs/zh-cn').iterdir())
        self.assertEqual([path.name for path in files], [table + '.json'])
        return result

    def test_gift_field_save_preserves_large_talk_and_unknown_fields(self):
        rows = copy.deepcopy(self.gift)
        rows['1500000']['item'] = 1300001
        del rows['1500000']['futureField']
        self.save('GiftEvtCfg', rows)
        row = b.read_json(self.cfg / 'GiftEvtCfg.json')['1500000']
        self.assertEqual(row['item'], 1300001)
        self.assertEqual(row['futureField'], {'keep': True})

    def test_new_gift_row_only_checks_same_table_in_other_mods(self):
        other = self.store.project(self.store.create('另一模组')['id'])
        other_cfg = other.path / 'Cfgs/zh-cn'
        (other_cfg / 'TalkCfg.json').write_bytes(self.talk_bytes)
        (other_cfg / 'GiftEvtCfg.json').write_bytes(b.json_bytes({'1500001': {'id': 1500001}}))
        rows = copy.deepcopy(self.gift)
        rows['1500002'] = {'id': 1500002, 'item': 1300000, 'npc': [1], 'talkId': [[1]], 'type': [0], 'cond': []}
        with patch.object(self.store.record_ids, 'keys', wraps=self.store.record_ids.keys) as keys:
            self.save('GiftEvtCfg', rows)
        self.assertFalse(any(Path(call.args[0]).name == 'TalkCfg.json' for call in keys.call_args_list))
        self.assertEqual(b.read_json(self.cfg / 'GiftEvtCfg.json')['1500002'], rows['1500002'])

    def test_other_non_story_table_save_preserves_large_talk(self):
        self.save('ItemCfg', {'1300000': {'id': 1300000, 'name': '修改礼物'}})
        self.assertEqual(b.read_json(self.cfg / 'ItemCfg.json')['1300000']['name'], '修改礼物')

    def test_external_large_talk_change_still_invalidates_revision(self):
        revision = self.store.revision(self.project)
        stat = self.talk.stat()
        external = self.talk_bytes.replace(b'A' * 5000, b'B' * 5000)
        self.talk.write_bytes(external)
        os.utime(self.talk, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertNotEqual(self.store.revision(self.project), revision)
        rows = copy.deepcopy(self.gift)
        rows['1500000']['item'] = 1300001
        with self.assertRaises(b.ApiError) as caught:
            self.store.table_save({'projectId': self.project.id, 'revision': revision,
                                   'name': 'GiftEvtCfg', 'rows': rows, 'scope': 'local'})
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'conflict'))
        self.assertEqual(b.read_json(self.cfg / 'GiftEvtCfg.json'), self.gift)
        self.assertEqual(self.talk.read_bytes(), external)


if __name__ == '__main__':
    unittest.main()
