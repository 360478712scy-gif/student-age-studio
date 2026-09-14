import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
"""Isolated save-boundary regression, not a reproduction of a reporter's mod."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server as b

class StorySpaceIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        env=patch.dict(os.environ,{'STUDIO_CACHE_ROOT':str(root/'Cache'),'STUDIO_USER_DATA_ROOT':str(root/'User')});env.start();self.addCleanup(env.stop)
        self.store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json')
        self.ident=self.store.create('保存隔离验证')['id'];self.project=self.store.project(self.ident)
        self.cfg=self.project.path/'Cfgs/zh-cn'
        self.write('TalkCfg',{'9001':{'id':9001,'content':'原对话','nextTalk':[],'roles':[]}})
        self.write('EvtCfg',{'9':{'id':9,'title':'剧情','talkId':[9001]}})
        self.write('KZoneProfileCfg',{'3':{'id':3,'name':'人物空间','desc':'原签名','font':106,'fontColor':208,'fontSize':56,'icon':777,'future':{'keep':[1,2]}}})
        self.write('KZoneAvatarCfg',{'777':{'id':777,'icon':'kzone_head/custom'}})
        self.write('KZoneFontCfg',{'106':{'id':106,'font':'custom-font'},'208':{'id':208,'colors':['#abcdef']}})
        self.write('KZoneMessageBoardCfg',{'300':{'id':300,'roles':[0,3],'content':'原留言'}})
        self.protected={p.name:p.read_bytes() for p in self.cfg.glob('KZone*.json')}
    def write(self,name,rows):
        # Noncanonical whitespace makes accidental rewrites observable byte for byte.
        (self.cfg/(name+'.json')).write_text(b.json.dumps(rows,ensure_ascii=False,indent=4)+'\n',encoding='utf-8')
    def request(self):
        d=self.store.load(self.ident);talks=copy.deepcopy(d['talks']);talks['9001']['content']='只改剧情'
        return dict(projectId=self.ident,revision=d['revision'],talks=talks)
    def assert_preserved(self):
        for name,value in self.protected.items():self.assertEqual((self.cfg/name).read_bytes(),value,name)
    def test_story_content_only_preserves_all_space_bytes(self):
        result=self.store.save(self.request());self.assert_preserved()
        transaction=b.read_json(Path(result['backup'])/'transaction.json')
        self.assertFalse(any('KZone' in str(f) for f in transaction['files']))
    def test_story_renumber_with_colliding_font_and_avatar_values(self):
        req=self.request();req['idMappings']={'TalkCfg':{'106':1106,'208':1208,'777':1777}}
        self.store.save(req);self.assert_preserved()
    def test_story_event_removal_preserves_space_bytes(self):
        self.store.save(dict(projectId=self.ident,revision=self.store.revision(self.project),events={}))
        self.assert_preserved()
    def test_external_edit_same_length_restored_mtime_rejects_stale_story(self):
        req=self.request();p=self.cfg/'KZoneProfileCfg.json';stat=p.stat()
        p.write_bytes(p.read_bytes().replace(b'106',b'107'));os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        before={p.name:p.read_bytes() for p in self.cfg.glob('*.json')}
        with self.assertRaises(b.ApiError) as error:self.store.save(req)
        self.assertEqual(error.exception.status,409)
        for name,value in before.items():self.assertEqual((self.cfg/name).read_bytes(),value)
    def test_saved_then_external_then_fresh_story_preserves_new_profile(self):
        self.store.save(self.request());p=self.cfg/'KZoneProfileCfg.json'
        p.write_bytes(p.read_bytes().replace(b'106',b'107'))
        self.protected[p.name]=p.read_bytes();req=self.request();req['talks']['9001']['content']='下一次剧情编辑'
        self.store.save(req);self.assert_preserved()

    def test_unexpected_story_profile_rewrite_rejected_atomically(self):
        request=self.request();request['idMappings']={'TalkCfg':{'9001':9002}}
        original=self.store.record_ids.rewrite
        def faulty(name,rows,mappings):
            result=original(name,rows,mappings)
            if name=='KZoneProfileCfg':result['3']['font']=0
            return result
        before={p.name:p.read_bytes() for p in self.cfg.glob('*.json')}
        with patch.object(self.store.record_ids,'rewrite',side_effect=faulty):
            with self.assertRaises(b.ApiError) as error:self.store.save(request)
        self.assertEqual(error.exception.code,'save_scope')
        for name,value in before.items():self.assertEqual((self.cfg/name).read_bytes(),value)
