"""Unfinished JSON drafts persist while generated native/UP records stay intact."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as b
import save_review


class UnfinishedSaveDraftTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        env = patch.dict(os.environ, {'STUDIO_USER_DATA_ROOT': str(root / 'User'), 'STUDIO_CACHE_ROOT': str(root / 'Cache')})
        env.start(); self.addCleanup(env.stop)
        self.store = b.StudioStore(root / 'Mods', root / 'Workshop', root / 'Game', asset_settings_path=root / 'assets.json', migrate_cache=False)
        self.addCleanup(self.store.close)
        self.ident = self.store.create('unfinished')['id']; self.project = self.store.project(self.ident)
        self.cfg = self.project.path / 'Cfgs/zh-cn'
        self.rows = {'1': {'id': 1, 'content': 'before', 'nextTalk': [2], 'audio': 0, 'effect': [[1163, 99, 7]], 'future': {'keep': [1, None]}},
                     '2': {'id': 2, 'content': 'tail', 'nextTalk': [], 'effect': None}}
        self.write('TalkCfg', self.rows)
        self.write('AudioCfg', {'7': {'id': 7, 'name': 'music', 'type': 1, 'url': 'music/a'}})
        self.write('ItemCfg', {'10': {'id': 10, 'name': 'item', 'talkId': 0, 'future': {'keep': 8}}})

    def write(self, name, rows):
        (self.cfg / (name + '.json')).write_bytes(b.json_bytes(rows))

    def save(self, **payload):
        return save_review.perform(self.store.save, {'projectId': self.ident, 'revision': self.store.revision(self.project), **payload}, b.ApiError)

    def group(self, **changes):
        return {'id': 'music', 'audioId': 7, 'talkIds': [1], 'loop': True, **changes}

    def metadata(self):
        return b.read_json(self.project.path / 'StudentAgeStudio/audio-cues.json')

    def test_event_binding_draft_references_follow_renumbering(self):
        draft={'actions':[{'id':45,'mode':'direct'}], 'interactions':[{'id':31,'talkId':1,'npc':7,'future':1}],
               'gifts':[{'id':81,'npc':7,'item':10,'index':0}],
               'social':{'actionId':45,'previousStartTalk':1,'conditions':[[3,3,1]],'effects':[]},'future':1}
        maps={'TalkCfg':{'1':100},'ActionCfg':{'45':145},'InteractCfg':{'31':131},'PersonCfg':{'7':107},
              'GiftEvtCfg':{'81':181},'ItemCfg':{'10':110}}
        row=self.store.record_ids.rewrite('EvtCfg',{'7':{'id':7,'studioEventBindingDraft':draft}},maps)['7']['studioEventBindingDraft']
        self.assertEqual(row['actions'][0]['id'],145)
        self.assertEqual(row['interactions'][0],{'id':131,'talkId':100,'npc':107,'future':1})
        self.assertEqual(row['gifts'][0],{'id':181,'npc':107,'item':110,'index':0})
        self.assertEqual(row['social']['previousStartTalk'],100)
        self.assertEqual(row['social']['conditions'],[[3,3,100]])
        self.assertEqual(row['future'],1)
        self.assertEqual(draft['interactions'][0]['talkId'],1)

    def test_missing_audio_object_and_invalid_loop_persist_with_text(self):
        for cue in ({'sfx': {'1': [None]}, 'bgm': []}, {'sfx': {}, 'bgm': [self.group(loop='unfinished')]}, {'sfx': {}, 'bgm': [self.group(talkIds=[])]}):
            with self.subTest(cue=cue):
                cue['future'] = {'raw': [None, 'keep']}
                row = {**self.rows['1'], 'content': 'unfinished saved'}
                result = self.save(talkPatch={'version': 1, 'upsert': {'1': row}, 'deleted': []}, audioCues=cue)
                self.assertTrue(result['ok']); self.assertTrue(result['warnings'])
                self.assertEqual(self.metadata()['sfx'], cue['sfx']); self.assertEqual(self.metadata()['bgm'], cue['bgm'])
                self.assertEqual(self.metadata()['future'], cue['future'])
                self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json')['1'], row)
                self.assertEqual(self.store.load(self.ident)['audioCues']['future'], cue['future'])

    def test_missing_talk_and_overlapping_bgm_are_advisory(self):
        for groups in ([self.group(talkIds=[999])], [self.group(), self.group(id='second')]):
            result = self.store.save({'projectId': self.ident, 'revision': self.store.revision(self.project), 'audioCues': {'sfx': {}, 'bgm': groups}})
            self.assertTrue(result['ok']); self.assertTrue(result['warnings'])
            self.assertEqual(self.metadata()['bgm'], groups)
            self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json'), self.rows)

    def test_up_compile_failure_preserves_native_commands_and_raw_draft(self):
        config = self.project.path / 'BetterAudio/BetterAudio.json'; config.parent.mkdir()
        original = b.json_bytes({'audios': [], 'musics': [], 'future': {'keep': 3}}); config.write_bytes(original)
        cues = {'sfx': {}, 'bgm': [self.group(loop=False, volume=.4)], 'future': 'draft'}
        changed = {**self.rows['1'], 'content': 'new text'}
        with patch('up_audio.compile', side_effect=ValueError('unfinished UP alias')):
            result = self.save(talkPatch={'version': 1, 'upsert': {'1': changed}, 'deleted': []}, audioCues=cues)
        self.assertTrue(result['ok']); self.assertTrue(result['warnings'])
        self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json')['1'], changed)
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(self.metadata()['bgm'], cues['bgm'])
        self.assertEqual(self.metadata()['future'], 'draft')

    def test_valid_json_bad_up_structure_is_saved_but_unparseable_file_is_not_overwritten(self):
        config = self.project.path / 'BetterAudio/BetterAudio.json'; config.parent.mkdir()
        broken_shape = b.json_bytes({'audios': None, 'future': 'keep'}); config.write_bytes(broken_shape)
        cues = {'sfx': {}, 'bgm': [self.group(volume=.4)]}
        self.assertTrue(self.save(audioCues=cues)['ok'])
        self.assertEqual(config.read_bytes(), broken_shape)
        before = (self.cfg / 'TalkCfg.json').read_bytes(); prior = (self.project.path / 'StudentAgeStudio/audio-cues.json').read_bytes()
        config.write_bytes(b'{unparseable')
        with self.assertRaises(b.ApiError): self.save(audioCues=cues)
        self.assertEqual(config.read_bytes(), b'{unparseable')
        self.assertEqual((self.cfg / 'TalkCfg.json').read_bytes(), before)
        self.assertEqual((self.project.path / 'StudentAgeStudio/audio-cues.json').read_bytes(), prior)

    def test_empty_item_name_and_incomplete_parameters_persist(self):
        row = {'id': 10, 'name': '', 'effect': [[1]], 'future': {'raw': None}}
        result = save_review.perform(self.store.table_save, {'projectId': self.ident, 'revision': self.store.revision(self.project), 'name': 'ItemCfg', 'scope': 'local', 'rows': {'10': row}}, b.ApiError)
        self.assertTrue(result['ok'])
        saved = b.read_json(self.cfg / 'ItemCfg.json')['10']
        self.assertEqual(saved['name'], ''); self.assertEqual(saved['effect'], [[1]]); self.assertEqual(saved['future'], row['future'])

    def test_empty_folder_name_and_missing_use_parameters_persist_without_binding(self):
        drafts = [
            {'one': {'name': '', 'talkIds': [1, 2], 'uses': [], 'future': {'keep': 7}}},
            {'one': {'name': 'draft', 'talkIds': [1, 2], 'uses': [{'id': 'use-item', 'kind': 'item', 'recordId': 10, 'entryId': 1, 'params': None, 'future': 'keep'}]}},
            {'one': {'name': 'draft', 'talkIds': [1, 2], 'uses': [None]}},
            {'one': {'name': 'draft', 'talkIds': [1, 2], 'uses': None}},
        ]
        item_before = (self.cfg / 'ItemCfg.json').read_bytes()
        for groups in drafts:
            with self.subTest(groups=groups):
                result = self.save(externalDialogueFolders=groups, externalDialogueIds=[1, 2])
                self.assertTrue(result['ok']); self.assertTrue(result['warnings'])
                self.assertEqual(b.read_json(self.project.path / 'StudentAgeStudio/editor-state.json')['externalDialogueFolders'], groups)
                self.assertEqual((self.cfg / 'ItemCfg.json').read_bytes(), item_before)
                import external_dialogues
                self.assertEqual(external_dialogues.load(self.store,self.ident,b,metadata=True)['folders'],groups)

    def test_missing_folder_talk_reopens_without_discarding_draft_reference(self):
        import external_dialogues
        groups={'one':{'name':'unfinished','talkIds':[1,999,1],'uses':[],'future':'keep'}}
        result=self.save(externalDialogueFolders=groups,externalDialogueIds=[1,2])
        self.assertTrue(result['ok']);self.assertTrue(result['warnings'])
        self.assertEqual(external_dialogues.load(self.store,self.ident,b,metadata=True)['folders'],groups)

    def test_failed_external_sequence_does_not_change_native_links(self):
        groups = {'one': {'name': 'draft', 'talkIds': [2, 1], 'sequence': True,
                           'uses': [{'id': 'item', 'kind': 'item', 'recordId': 10, 'entryId': 2, 'params': None}]}}
        result = self.save(externalDialogueFolders=groups, externalDialogueIds=[1, 2])
        self.assertTrue(result['ok'])
        self.assertEqual(b.read_json(self.cfg / 'TalkCfg.json'), self.rows)
        self.assertEqual(b.read_json(self.project.path / 'StudentAgeStudio/editor-state.json')['externalDialogueFolders'], groups)

    def test_external_null_uses_can_be_completed_and_compiled(self):
        unfinished={'one':{'name':'draft','talkIds':[1,2],'uses':None,'future':'keep'}}
        self.assertTrue(self.save(externalDialogueFolders=unfinished,externalDialogueIds=[1,2])['ok'])
        complete=copy.deepcopy(unfinished)
        complete['one']['uses']=[{'id':'item','kind':'item','recordId':10,'entryId':1,'params':{}}]
        result=self.save(externalDialogueFolders=complete,externalDialogueIds=[1,2])
        self.assertTrue(result['ok']);self.assertFalse(result['warnings'])
        self.assertEqual(b.read_json(self.cfg/'ItemCfg.json')['10']['talkId'],1)
        self.assertEqual(b.read_json(self.project.path/'StudentAgeStudio/editor-state.json')['externalDialogueFolders']['one']['future'],'keep')

    def test_external_binding_does_not_swallow_unparseable_target_file(self):
        path=self.cfg/'ItemCfg.json';path.write_bytes(b'{unparseable')
        before=(self.cfg/'TalkCfg.json').read_bytes()
        groups={'one':{'name':'complete','talkIds':[1,2],'uses':[{'id':'item','kind':'item','recordId':10,'entryId':1,'params':{}}]}}
        with self.assertRaises(b.ApiError):
            self.save(talkPatch={'version':1,'upsert':{'1':{**self.rows['1'],'content':'must not commit'}},'deleted':[]},externalDialogueFolders=groups,externalDialogueIds=[1,2])
        self.assertEqual(path.read_bytes(),b'{unparseable')
        self.assertEqual((self.cfg/'TalkCfg.json').read_bytes(),before)

    def test_audio_malformed_ownership_can_be_completed_without_removing_manual_up(self):
        path=self.project.path/'StudentAgeStudio/audio-cues.json';path.parent.mkdir(exist_ok=True)
        for ledger in ({'nativeSnapshot':None,'upAudio':None},{'nativeSnapshot':{},'upAudio':{'effects':None,'aliases':None}}):
            with self.subTest(ledger=ledger):
                path.write_bytes(b.json_bytes({'version':1,'sfx':{'1':[None]},'bgm':[],'future':'keep',**ledger}))
                result=self.save(audioCues={'sfx':{},'bgm':[self.group()]})
                self.assertTrue(result['ok']);self.assertTrue(result['warnings'])
                self.assertEqual(b.read_json(self.cfg/'TalkCfg.json')['1']['audio'],7)
                self.assertEqual(b.read_json(self.cfg/'TalkCfg.json')['1']['effect'],self.rows['1']['effect'])
                self.assertEqual(self.metadata()['future'],'keep');self.assertIsInstance(self.metadata()['nativeSnapshot'],dict)

    def test_social_missing_roles_or_self_parent_save_without_parent_binding_changes(self):
        self.write('PersonCfg',{'3':{'id':3,'name':'person'}})
        post={'1':{'id':1,'role':3,'comments':[[101,0]],'options':[],'future':'keep'}}
        original={'id':101,'roles':[3],'parent':0,'comments':[],'options':[],'future':{'keep':7}}
        self.write('KZoneContentCfg',post);self.write('KZoneCommentCfg',{'101':original})
        before=(self.cfg/'KZoneContentCfg.json').read_bytes()
        for update in ({'roles':[]},{'parent':101},{'comments':5},{'comments':[[101,-1]]}):
            row={**original,**update}
            result=save_review.perform(self.store.table_save,{'projectId':self.ident,'revision':self.store.revision(self.project),'name':'KZoneCommentCfg','scope':'local','rows':{'101':row}},b.ApiError)
            self.assertTrue(result['ok'])
            self.assertEqual(b.read_json(self.cfg/'KZoneCommentCfg.json')['101'],row)
            self.assertEqual((self.cfg/'KZoneContentCfg.json').read_bytes(),before)


if __name__ == '__main__': unittest.main()
