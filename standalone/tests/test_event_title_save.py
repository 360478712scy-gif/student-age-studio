"""Pure existing event titles use the existing transaction without story scans."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b


class EventTitleSaveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT': str(self.root / 'Cache'),
                                     'STUDIO_USER_DATA_ROOT': str(self.root / 'User'),
                                     'STUDIO_BACKUP_ROOT': str(self.root / 'Backups')})
        env.start(); self.addCleanup(env.stop)
        self.store = b.StudioStore(self.root / 'Mods', self.root / 'Workshop', self.root / 'Game',
                                   asset_settings_path=self.root / 'assets.json', migrate_cache=False)
        self.addCleanup(self.store.close)
        self.project = self.store.project(self.store.create('事件标题事务')['id'])
        self.cfg = self.project.path / 'Cfgs/zh-cn'
        self.events = {'7': {'id': 7, 'title': '原标题', 'type': 1, 'talkId': [7001],
                             'future': {'keep': [True, 1.25, {'nested': '未知'}]}},
                       '8': {'id': 8, 'title': '共享对话', 'talkId': [7001]}}
        self.talks = {'7001': {'id': 7001, 'content': '原文', 'nextTalk': [7002], 'future': {'keep': [1]}},
                      '7002': {'id': 7002, 'content': '后续', 'nextTalk': []}}
        (self.cfg / 'EvtCfg.json').write_bytes(b.json_bytes(self.events))
        (self.cfg / 'TalkCfg.json').write_bytes(b.json_bytes(self.talks))
        (self.cfg / 'ItemCfg.json').write_bytes(b.json_bytes({'3': {'id': 3, 'name': '无关物品'}}))
        self.descriptor = self.store.talk_segments.open(self.project.id)
        self.gen = self.store.talk_segments.get(self.project.id, self.descriptor['segmentedTalks']['generation'])
        self.before = {path.relative_to(self.project.path).as_posix(): path.read_bytes()
                       for path in self.project.path.rglob('*') if path.is_file()}

    def payload(self):
        events = copy.deepcopy(self.events)
        events['7']['title'] = '新标题😀'
        return {'projectId': self.project.id, 'revision': self.store.revision(self.project),
                'talkGeneration': self.gen.generation, 'events': events}

    def test_title_only_preserves_unknowns_pages_and_exact_target_backup(self):
        payload = self.payload()
        entries, summaries, packed = self.gen.entries, self.gen.summaries, self.gen.packed()
        original_page = self.gen.page(['7001', '7002'])['rows']
        context = self.store.talk_segments.request_context
        context.token = self.gen.generation
        self.addCleanup(delattr, context, 'token')
        with (patch.object(self.store, 'story_save_maps', side_effect=AssertionError('unrelated story read')),
              patch.object(self.store, '_story_ownership', side_effect=AssertionError('unrelated ownership')),
              patch.object(b, 'read_json', wraps=b.read_json) as read):
            result = self.store.save(payload)
        self.assertFalse(any(Path(call.args[0]).name == 'TalkCfg.json' for call in read.call_args_list))
        self.assertTrue(result['ok']); self.assertTrue(result['talkGenerationAdvanced'])
        self.assertEqual(context.advanced[0], self.gen.generation)
        self.assertEqual(b.read_json(self.cfg / 'EvtCfg.json'), payload['events'])
        backup = Path(result['backup'])
        self.assertEqual((backup / 'Cfgs/zh-cn/EvtCfg.json').read_bytes(), self.before['Cfgs/zh-cn/EvtCfg.json'])
        self.assertEqual(b.read_json(backup / 'transaction.json')['files'], {'Cfgs/zh-cn/EvtCfg.json': True})
        for key, raw in self.before.items():
            if key != 'Cfgs/zh-cn/EvtCfg.json': self.assertEqual((self.project.path / key).read_bytes(), raw, key)
        self.assertIs(self.gen.entries, entries); self.assertIs(self.gen.summaries, summaries); self.assertIs(self.gen.packed(), packed)
        self.assertEqual(self.gen.page(['7001', '7002'])['rows'], original_page)
        self.assertEqual(self.gen.page(['7001'])['revision'], result['revision'])

    def test_non_title_normalization_and_omitted_unknowns_fall_back(self):
        for change in ('normalized', 'unknown_omitted'):
            with self.subTest(change=change):
                payload = self.payload()
                if change == 'normalized': payload['events']['7']['studioEventBindings'] = []
                else: payload['events']['7'].pop('future')
                with patch.object(self.store, 'story_save_maps', wraps=self.store.story_save_maps) as maps:
                    result = self.store.save(payload)
                self.assertTrue(result['ok']); self.assertTrue(maps.called)
                self.assertEqual(b.read_json(self.cfg / 'EvtCfg.json')['7']['future'], self.events['7']['future'])
                self.events = b.read_json(self.cfg / 'EvtCfg.json')

    def test_every_guard_boundary_keeps_generic_save(self):
        changes = [lambda p: p.update(order=[]), lambda p: p.update(_confirmedSaveWarnings=[]),
                   lambda p: p['events'].update({'9': {'id': 9, 'title': '新增', 'talkId': []}}),
                   lambda p: p['events'].pop('8'), lambda p: p['events']['7'].update(id=9),
                   lambda p: p['events']['7'].update(type=1.0),
                   lambda p: p['events']['7']['future'].update(keep=[1, 1.25, {'nested': '未知'}]),
                   lambda p: p['events']['7'].pop('title'),
                   lambda p: p['events']['7'].update(title=None),
                   lambda p: p['events']['7'].update(title='原标题')]
        for change in changes:
            payload = self.payload(); change(payload)
            with self.subTest(payload=payload), patch.object(self.store, 'story_save_maps', side_effect=RuntimeError('generic')):
                with self.assertRaisesRegex(RuntimeError, 'generic'): self.store.save(payload)

    def test_omitted_existing_title_keeps_generic_merge_and_old_title(self):
        payload = self.payload()
        payload['events']['7'].pop('title')
        with patch.object(self.store, 'story_save_maps', wraps=self.store.story_save_maps) as maps:
            result = self.store.save(payload)
        self.assertTrue(result['ok']); self.assertTrue(maps.called)
        self.assertEqual(b.read_json(self.cfg / 'EvtCfg.json'), self.events)

    def social_metadata(self):
        # Exact metadata shape of native event 1300003 in the captured request.
        return {'text': '', 'favor': 0, 'title': 'final Remote Massive 填写后点击创建',
                'maxcount': 1, 'repeat': False, 'intimacy': 0, 'actionId': 0, 'level': 1,
                'disabledConditions': [], 'entryConditions': [], 'conditions': [], 'effects': [],
                'futureNested': {'keep': [True, 1.25, {'nested': '未知社交字段'}]}}

    def test_captured_social_title_shape_commits_only_two_labels_without_talk_read(self):
        self.events['7']['studioSocial'] = self.social_metadata()
        (self.cfg / 'EvtCfg.json').write_bytes(b.json_bytes(self.events))
        prior = (self.cfg / 'EvtCfg.json').read_bytes()
        payload = self.payload()
        payload['events']['7']['studioSocial']['title'] = 'final Remote Massive 最终保存复核'
        with (patch.object(self.store, 'story_save_maps', side_effect=AssertionError('unrelated story read')),
              patch.object(self.store, '_story_ownership', side_effect=AssertionError('unrelated ownership')),
              patch.object(b, 'read_json', wraps=b.read_json) as read):
            result = self.store.save(payload)
        self.assertFalse(any(Path(call.args[0]).name == 'TalkCfg.json' for call in read.call_args_list))
        self.assertEqual(b.read_json(self.cfg / 'EvtCfg.json'), payload['events'])
        self.assertEqual((Path(result['backup']) / 'Cfgs/zh-cn/EvtCfg.json').read_bytes(), prior)
        self.assertEqual(b.read_json(Path(result['backup']) / 'transaction.json')['files'], {'Cfgs/zh-cn/EvtCfg.json': True})
        self.assertEqual((self.cfg / 'TalkCfg.json').read_bytes(), self.before['Cfgs/zh-cn/TalkCfg.json'])
        self.assertEqual(json.loads(self.gen.page(['7001'])['rows'][0][1]), self.talks['7001'])

    def test_social_metadata_guard_keeps_generic_for_any_other_change(self):
        self.events['7']['studioSocial'] = self.social_metadata()
        (self.cfg / 'EvtCfg.json').write_bytes(b.json_bytes(self.events))
        changes = [lambda p: p['events']['7']['studioSocial'].pop('title'),
                   lambda p: p['events']['7']['studioSocial'].update(title=None),
                   lambda p: p['events']['7']['studioSocial'].update(title=123),
                   lambda p: p['events']['7'].pop('studioSocial'),
                   lambda p: p['events']['7'].update(studioSocial=[]),
                   lambda p: p['events']['8'].update(studioSocial={'title': '新增元数据'}),
                   lambda p: p['events']['7']['studioSocial'].pop('futureNested'),
                   lambda p: p['events']['7']['studioSocial'].update(newUnknown='新增未知字段'),
                   lambda p: p['events']['7']['studioSocial'].update(maxcount=1.0),
                   lambda p: p['events']['7']['studioSocial'].update(text='改变进度文字'),
                   lambda p: p['events']['7']['studioSocial'].update(effects=[[1, 520, 7]])]
        for change in changes:
            payload = self.payload(); change(payload)
            with self.subTest(payload=payload), patch.object(self.store, 'story_save_maps', side_effect=RuntimeError('generic')):
                with self.assertRaisesRegex(RuntimeError, 'generic'): self.store.save(payload)

    def test_live_external_change_rejects_title_and_preserves_external_bytes(self):
        payload = self.payload()
        path = self.cfg / 'TalkCfg.json'
        stamp = path.stat()
        external = path.read_bytes().replace('原文'.encode(), '外文'.encode())
        path.write_bytes(external); os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.assertRaises(b.ApiError) as error: self.store.save(payload)
        self.assertEqual(error.exception.code, 'conflict')
        self.assertEqual(path.read_bytes(), external)
        self.assertEqual((self.cfg / 'EvtCfg.json').read_bytes(), self.before['Cfgs/zh-cn/EvtCfg.json'])

    def test_commit_rechecks_revision_after_title_guard(self):
        payload = self.payload()
        original = self.store.commit
        path = self.cfg / 'TalkCfg.json'
        external = path.read_bytes().replace('原文'.encode(), '外文'.encode())
        def change_before_commit(*args, **kwargs):
            path.write_bytes(external)
            return original(*args, **kwargs)
        with patch.object(self.store, 'commit', side_effect=change_before_commit):
            with self.assertRaises(b.ApiError) as error: self.store.save(payload)
        self.assertEqual(error.exception.code, 'conflict')
        self.assertEqual(path.read_bytes(), external)
        self.assertEqual((self.cfg / 'EvtCfg.json').read_bytes(), self.before['Cfgs/zh-cn/EvtCfg.json'])
        self.assertEqual(self.gen.source_state['revision'], payload['revision'])
        self.assertEqual(json.loads(self.gen.page(['7001'])['rows'][0][1]), self.talks['7001'])

    def test_stale_or_damaged_generation_is_not_advanced_by_title_save(self):
        payload = self.payload()
        payload['talkGeneration'] = 'missing-token'
        with self.assertRaises(b.ApiError): self.store.save(payload)
        payload['talkGeneration'] = self.gen.generation
        self.gen.path.joinpath('records.json').unlink()
        with self.assertRaises(OSError): self.store.save(payload)
        self.assertEqual((self.cfg / 'EvtCfg.json').read_bytes(), self.before['Cfgs/zh-cn/EvtCfg.json'])

    def test_existing_atomic_rollback_keeps_original_title_and_generation(self):
        payload = self.payload()
        original = b.atomic_write
        failed = []
        def fail_committed_journal(path, data):
            if Path(path).name == 'transaction.json' and json.loads(data).get('state') == 'committed' and not failed:
                failed.append(True); raise OSError('journal disk failure after target replacement')
            return original(path, data)
        with patch.object(b, 'atomic_write', side_effect=fail_committed_journal):
            with self.assertRaisesRegex(OSError, 'journal disk failure'): self.store.save(payload)
        self.assertTrue(failed)
        self.assertEqual((self.cfg / 'EvtCfg.json').read_bytes(), self.before['Cfgs/zh-cn/EvtCfg.json'])
        self.assertEqual((self.cfg / 'TalkCfg.json').read_bytes(), self.before['Cfgs/zh-cn/TalkCfg.json'])
        self.assertEqual(self.gen.page(['7001'])['revision'], payload['revision'])
        self.assertEqual(json.loads(self.gen.page(['7001'])['rows'][0][1]), self.talks['7001'])


if __name__ == '__main__': unittest.main()
