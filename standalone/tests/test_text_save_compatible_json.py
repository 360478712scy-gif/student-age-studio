"""Save JSON accepted by the normal reader through the audio-aware text path."""
import copy
import json
import unittest
from unittest.mock import patch
import test_scoped_save
import server as b

class CompatibleTextSaveTests(unittest.TestCase):
    setUp = test_scoped_save.ScopedSaveTests.setUp
    write = test_scoped_save.ScopedSaveTests.write
    save = test_scoped_save.ScopedSaveTests.save

    def cue_snapshot(self):
        path = self.project.path / 'StudentAgeStudio/audio-cues.json'
        b.atomic_write(path, b.json_bytes({'runtimeVersion': 1, 'nativeSnapshot': {'1': 0}}))

    def test_literal_controls_text_save_keeps_unedited_content_and_fields(self):
        self.cue_snapshot()
        path = self.cfg / 'TalkCfg.json'
        raw = b'{"1":{"id":1,"content":"old\\ntext","nextTalk":[2],"future":{"keep":[1,2]}},"2":{"id":2,"content":"literal\nline\ttab\x01control","plugin":{"keep":123}}}'
        path.write_bytes(raw)
        original = b.read_json(path)
        edit = copy.deepcopy(original['1']); edit['content'] = '新正文\n下一行'
        result = self.save({'talkPatch': {'version': 1, 'upsert': {'1': edit}, 'deleted': []}})
        self.assertTrue(result['ok'])
        saved = json.loads(path.read_bytes())
        self.assertEqual(saved['1'], edit)
        self.assertEqual(saved['2'], original['2'])
        backup = result['backup']
        self.assertTrue(backup)
        self.assertTrue(any(p.read_bytes() == raw for p in self.root.rglob('TalkCfg.json') if p != path))
        # Once serialized normally, repeated edits may reuse the fast path.
        edit['content'] = '再次保存'
        self.assertTrue(self.save({'talkPatch': {'version': 1, 'upsert': {'1': edit}, 'deleted': []}})['ok'])
        self.assertEqual(json.loads(path.read_bytes())['1']['content'], '再次保存')

    def test_comment_and_trailing_comma_use_normal_save(self):
        self.cue_snapshot()
        path = self.cfg / 'TalkCfg.json'
        path.write_text('{"1":{"id":1,"content":"old"}, // existing game syntax\n"2":{"id":2,"content":"keep"},}', encoding='utf-8')
        result = self.save({'talkPatch': {'version': 1, 'upsert': {'1': {'id': 1, 'content': 'new'}}, 'deleted': []}})
        self.assertTrue(result['ok'])
        self.assertEqual(json.loads(path.read_bytes())['2']['content'], 'keep')

    def test_valid_snapshot_keeps_text_fast_path(self):
        self.cue_snapshot()
        data = {'projectId': self.project.id, 'revision': self.store.revision(self.project), 'talkPatch': {'version': 1, 'upsert': {'2': {'id': 2, 'content': 'new'}}, 'deleted': []}}
        with patch.object(self.store, 'story_save_maps', side_effect=AssertionError('valid text save must stay fast')):
            self.assertTrue(self.store.save(data)['ok'])
