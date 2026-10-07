"""External-editor branch changes never hide or destroy native dialogue."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b


class StaleBranchMetadataTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        env = patch.dict(os.environ, {'STUDIO_USER_DATA_ROOT': str(root / 'User'),
                                     'STUDIO_CACHE_ROOT': str(root / 'Cache'),
                                     'STUDIO_BACKUP_ROOT': str(root / 'Backups')})
        env.start(); self.addCleanup(env.stop)
        self.store = b.StudioStore(root / 'Mods', root / 'Workshop', root / 'Game',
                                  asset_settings_path=root / 'assets.json', migrate_cache=False)
        self.addCleanup(self.store.close)
        self.project = self.store.project(self.store.create('External branch QA')['id'])
        self.cfg = self.project.path / 'Cfgs/zh-cn'
        self.state = self.project.path / 'StudentAgeStudio/editor-state.json'
        self.folder = {'kind': 'condition', 'parentTalkId': 1001, 'branchId': 1,
                       'routerId': 1002, 'exitId': 1003, 'endId': 1004, 'baseNext': [1005],
                       'talkIds': [1006], 'continuation': {'kind': 'following'}}
        self.talks = {str(i): {'id': i, 'content': '', 'nextTalk': [], 'nextTalk2': [], 'check': []}
                      for i in range(1001, 1007)}
        self.talks['1001'].update(content='开始', nextTalk=[1002])
        self.talks['1002'].update(check=[[7, 1, 3, 30]], nextTalk=[1006], nextTalk2=[1005])
        self.talks['1003']['nextTalk'] = [1005]
        self.talks['1005']['content'] = '后续正文'
        self.talks['1006'].update(content='保留分支正文', nextTalk=[1003], effect=[[1163, 5, 1]])
        self.write(self.talks)

    def write(self, talks):
        (self.cfg / 'TalkCfg.json').write_bytes(b.json_bytes(talks))
        (self.cfg / 'EvtCfg.json').write_bytes(b.json_bytes({'1': {'id': 1, 'talkId': [1001]}}))
        self.state.parent.mkdir(exist_ok=True)
        self.state.write_bytes(b.json_bytes({'branchFolders': {'1001:branch:1': self.folder},
                                            'future': {'keep': 1}}))

    def test_load_filters_external_changes_without_touching_native_files(self):
        for case in ('router', 'exit', 'end', 'parent', 'parent_route', 'success_route',
                     'failure_route', 'exit_route', 'end_route', 'exit_condition', 'helper_text', 'helper_effect'):
            with self.subTest(case=case):
                talks = copy.deepcopy(self.talks)
                if case in ('router', 'exit', 'end', 'parent'):
                    del talks[str({'router': 1002, 'exit': 1003, 'end': 1004, 'parent': 1001}[case])]
                elif case == 'parent_route': talks['1001']['nextTalk'] = [1005]
                elif case == 'success_route': talks['1002']['nextTalk'] = [1005]
                elif case == 'failure_route': talks['1002']['nextTalk2'] = [1006]
                elif case == 'exit_route': talks['1003']['nextTalk'] = []
                elif case == 'end_route': talks['1004']['nextTalk'] = [1005]
                elif case == 'exit_condition': talks['1003']['check'] = [[7, 1, 3, 30]]
                elif case == 'helper_text': talks['1002']['content'] = '原版编辑器的新正文'
                elif case == 'helper_effect': talks['1003']['effect'] = [[1163, 8, 1]]
                self.write(talks)
                original = (self.cfg / 'TalkCfg.json').read_bytes(), self.state.read_bytes()
                loaded = self.store.load(self.project.id)
                self.assertEqual(loaded['branchFolders'], {})
                self.assertEqual(loaded['talks'], talks)
                self.assertTrue(loaded['warnings'])
                self.assertEqual(((self.cfg / 'TalkCfg.json').read_bytes(), self.state.read_bytes()), original)

    def test_segmented_open_and_metadata_save_keep_repurposed_helper(self):
        talks = copy.deepcopy(self.talks); talks['1002']['content'] = '已经成为普通对话'
        self.write(talks)
        opened = self.store.talk_segments.open(self.project.id)
        self.assertEqual(opened['branchFolders'], {})
        original = (self.cfg / 'TalkCfg.json').read_bytes()
        saved = self.store.save({'projectId': self.project.id, 'revision': opened['revision'],
                                 'eventGrades': {'1': 1}})
        self.assertTrue(saved['ok']); self.assertEqual(saved['branchFolders'], {})
        self.assertEqual((self.cfg / 'TalkCfg.json').read_bytes(), original)
        self.assertEqual(b.read_json(self.state)['future'], {'keep': 1})
        self.assertEqual(b.read_json(self.state)['branchFolders'], {})
        self.assertTrue(saved['warnings'])

    def test_valid_branch_survives_load_and_save(self):
        loaded = self.store.load(self.project.id)
        self.assertEqual(loaded['branchFolders'], {'1001:branch:1': self.folder})
        saved = self.store.save({'projectId': self.project.id, 'revision': loaded['revision'],
                                 'eventGrades': {'1': 1}})
        self.assertEqual(saved['branchFolders'], {'1001:branch:1': self.folder})
        self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json'), self.talks)

    def test_text_save_commits_pending_cleanup_instead_of_bypassing_it(self):
        talks = copy.deepcopy(self.talks)
        del talks['1002']; talks['1001']['nextTalk'] = [1005]
        self.write(talks)
        opened = self.store.talk_segments.open(self.project.id)
        edited = {**talks['1001'], 'content': '正文修改后整理旧分支记录'}
        saved = self.store.save({'projectId': self.project.id, 'revision': opened['revision'],
                                 'talkGeneration': opened['segmentedTalks']['generation'],
                                 'talkPatch': {'version': 1, 'upsert': {'1001': edited}, 'deleted': []}})
        self.assertTrue(saved['ok']); self.assertEqual(saved['branchFolders'], {})
        self.assertEqual(b.read_json(self.state)['branchFolders'], {})
        self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json'), {**talks, '1001': edited})

    def test_authored_failure_override_keeps_bypassed_draft_branch(self):
        talks = copy.deepcopy(self.talks)
        second = {**copy.deepcopy(self.folder), 'branchId': 2, 'routerId': 1007,
                  'exitId': 1008, 'talkIds': []}
        talks['1007'] = {'id': 1007, 'content': '', 'check': [], 'nextTalk': [1008], 'nextTalk2': [1005]}
        talks['1008'] = {'id': 1008, 'content': '', 'check': [], 'nextTalk': [1005], 'nextTalk2': []}
        self.folder['failureNext'] = []; talks['1002']['nextTalk2'] = [1004]
        self.write(talks)
        state = b.read_json(self.state); state['branchFolders']['1001:branch:2'] = second
        self.state.write_bytes(b.json_bytes(state))
        loaded = self.store.load(self.project.id)
        self.assertEqual(loaded['branchFolders'], state['branchFolders'])
        saved = self.store.save({'projectId': self.project.id, 'revision': loaded['revision'],
                                 'eventGrades': {'1': 1}})
        self.assertEqual(saved['branchFolders'], state['branchFolders'])


if __name__ == '__main__': unittest.main()
