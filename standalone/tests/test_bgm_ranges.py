"""Native audio round trips: range boundaries, continuation and external edits."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as b
from native_audio import export, reconcile

class BgmRanges(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        env=patch.dict(os.environ,{'STUDIO_USER_DATA_ROOT':str(root/'User'),'STUDIO_CACHE_ROOT':str(root/'Cache')});env.start();self.addCleanup(env.stop)
        self.store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json')
        self.id=self.store.create('BGM ranges')['id'];self.project=self.store.project(self.id);self.cfg=self.project.path/'Cfgs/zh-cn'
        self.rows={str(i):{'id':i,'content':'line '+str(i),'audio':0,'nextTalk':[i+1] if i<8 else [],'nextTalk2':[],'option':[]} for i in range(1,9)}
        self.write('TalkCfg',self.rows);self.write('EvtCfg',{'1':{'id':1,'title':'BGM','talkId':[1]}})
        self.write('AudioCfg',{'7':{'id':7,'type':1,'url':'bgm/a'},'8':{'id':8,'type':1,'url':'bgm/b'}})
    def write(self,name,rows):(self.cfg/(name+'.json')).write_bytes(b.json_bytes(rows))
    def group(self,name,audio,ids):return {'id':name,'audioId':audio,'talkIds':ids,'loop':True,'volume':1}
    def save(self,**payload):return self.store.save({'projectId':self.id,'revision':self.store.revision(self.project),**payload})
    def native(self):return {k:r['audio'] for k,r in b.read_json(self.cfg/'TalkCfg.json').items()}
    def test_save_repeat_reopen_and_text_change_keep_only_entry_directive(self):
        cues={'version':1,'sfx':{},'bgm':[self.group('first',7,[1,2,3,4])]}
        self.save(audioCues=cues)
        self.assertEqual(self.native(),{str(i):7 if i==1 else 0 for i in range(1,9)})
        loaded=self.store.load(self.id);self.assertEqual(loaded['audioCues']['bgm'][0]['talkIds'],[1,2,3,4])
        # Live draft's continuation zeros must not drop the music on a later save.
        row=copy.deepcopy(self.rows['1']);row['content']='edited again'
        self.save(talkPatch={'version':1,'upsert':{'1':row},'deleted':[]})
        self.assertEqual(self.native()['1'],7)
        self.save(audioCues=cues)
        self.assertEqual(self.native()['1'],7)
        self.assertTrue(all(self.native()[str(i)]==0 for i in range(2,9)))
    def test_shorten_remove_and_continue_do_not_leave_replay_commands(self):
        self.save(audioCues={'sfx':{},'bgm':[self.group('a',7,list(range(1,9)))]})
        self.save(audioCues={'sfx':{},'bgm':[self.group('a',7,[1,2,3]),self.group('zero',0,[4,5]),self.group('b',8,[6,7])]})
        self.assertEqual(self.native(),{'1':7,'2':0,'3':0,'4':0,'5':0,'6':8,'7':0,'8':0})
        self.assertEqual([g['audioId'] for g in self.store.load(self.id)['audioCues']['bgm']],[7,0,8])
        self.save(audioCues={'sfx':{},'bgm':[]})
        self.assertEqual(set(self.native().values()),{0})
    def test_external_native_editor_change_wins(self):
        self.save(audioCues={'sfx':{},'bgm':[self.group('a',7,[1,2,3]),self.group('zero',0,[4])]})
        rows=b.read_json(self.cfg/'TalkCfg.json');rows['1']['audio']=0;rows['4']['audio']=8;self.write('TalkCfg',rows)
        cues=self.store.load(self.id)['audioCues'];self.assertEqual(cues['bgm'][0]['talkIds'],[2,3]);self.assertEqual(len(cues['bgm']),1)
        self.save(talkPatch={'version':1,'upsert':{'5':{**rows['5'],'content':'only text'}},'deleted':[]})
        self.assertEqual(self.native()['1'],0);self.assertEqual(self.native()['4'],8)
    def test_branches_and_independent_entry_keep_bgm(self):
        rows=copy.deepcopy(self.rows);rows['1']['nextTalk']=[2,3];rows['2']['nextTalk']=[4];rows['3']['nextTalk']=[4]
        cues={'sfx':{},'bgm':[self.group('a',7,[1,2,4]),self.group('b',8,[3])]}
        export(cues,{},rows,{}, {},{'1':{'talkId':[1]},'2':{'talkId':[2]}},{})
        self.assertEqual([rows[str(i)]['audio'] for i in range(1,5)],[7,7,8,7])
    def test_same_music_after_zero_or_gap_does_not_restart(self):
        self.save(audioCues={'sfx':{},'bgm':[self.group('a',7,[1,2]),self.group('zero',0,[3]),self.group('a2',7,[5,6]),self.group('b',8,[7,8])]})
        self.assertEqual(self.native(),{'1':7,'2':0,'3':0,'4':0,'5':0,'6':0,'7':8,'8':0})

    def test_silence_is_real_reusable_mod_audio_and_zero_continues_it(self):
        import wave
        first=self.store.silent_bgm({'projectId':self.id,'revision':self.store.revision(self.project)})
        self.assertEqual(first['row']['type'],1)
        with wave.open(str(self.project.path/first['assetPath']),'rb') as audio:
            self.assertEqual(audio.getnframes()/audio.getframerate(),2)
            self.assertFalse(any(audio.readframes(audio.getnframes())))
        again=self.store.silent_bgm({'projectId':self.id,'revision':first['revision']})
        self.assertEqual(first['id'],again['id']);self.assertTrue(again['reused'])
        self.assertEqual(first['revision'],again['revision'])
        self.save(audioCues={'sfx':{},'bgm':[self.group('music',7,[1]),self.group('silent',first['id'],[2,3]),self.group('continue',0,[4,5]),self.group('back',8,[6,7,8])]})
        self.assertEqual(self.native(),{'1':7,'2':first['id'],'3':0,'4':0,'5':0,'6':8,'7':0,'8':0})
        self.assertEqual(self.store.load(self.id)['audioCues']['bgm'][1]['audioId'],first['id'])
        with self.assertRaises(b.ApiError):self.store.silent_bgm({'projectId':self.id,'revision':first['revision']})

    def test_zero_not_allowed_as_sound_effect_or_invalid_volume(self):
        for cues in [{'sfx':{'1':[{'audioId':0}]},'bgm':[]},{'sfx':{},'bgm':[{**self.group('zero',0,[1]),'volume':2}]}]:
            with self.assertRaises(b.ApiError):self.save(audioCues=cues)

if __name__=='__main__':unittest.main()
