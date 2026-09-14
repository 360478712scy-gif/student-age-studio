"""Large-table save integrity and no-op fast paths in disposable mods."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import copy
import os
import tempfile
import unittest
from unittest.mock import patch
import server as b

class LargeSaveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = patch.dict(os.environ, {'STUDIO_CACHE_ROOT':str(root/'Cache'), 'STUDIO_USER_DATA_ROOT':str(root/'User')})
        env.start(); self.addCleanup(env.stop)
        self.store = b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json')
        self.ident = self.store.create('Large save')['id']; self.project = self.store.project(self.ident)
        self.cfg = self.project.path/'Cfgs/zh-cn'
        self.talks = {str(i):{'id':i,'content':'原对话','nextTalk':[i+1] if i%20!=19 else [],'roleIds':[], 'roles':[], 'future':{'keep':[i,{'text':'未知嵌套字段'}]}} for i in range(10000,11000)}
        self.events = {str(i):{'id':i,'talkId':[10000+(i-100)*20], 'future':{'keep':True}} for i in range(100,150)}
        for name, rows in [('TalkCfg',self.talks),('EvtCfg',self.events),('KZoneProfileCfg',{'3':{'id':3,'font':9,'icon':7,'future':{'keep':True}}})]:
            (self.cfg/(name+'.json')).write_bytes(b.json_bytes(rows))
        self.before = {p.name:p.read_bytes() for p in self.cfg.glob('*.json')}
    def request(self):
        rows = copy.deepcopy(self.talks); rows['10005']['content'] = '只改这一句'
        return dict(projectId=self.ident,revision=self.store.revision(self.project),talks=rows)
    def test_one_line_preserves_all_events_rows_unknowns_and_backup(self):
        req = self.request(); original = copy.deepcopy(req)
        result = self.store.save(req)
        self.assertEqual(req, original)
        self.assertEqual(b.read_json(self.cfg/'TalkCfg.json'),req['talks'])
        for name,data in self.before.items():
            if name!='TalkCfg.json':self.assertEqual((self.cfg/name).read_bytes(),data)
        self.assertEqual((Path(result['backup'])/'Cfgs/zh-cn/TalkCfg.json').read_bytes(),self.before['TalkCfg.json'])
        self.assertEqual(len(self.store.load(self.ident)['talks']),len(self.talks))
        req['revision']=result['revision'];self.assertIsNone(self.store.save(req)['backup'])
    def test_order_preserves_missing_tail_without_duplicates(self):
        state=self.project.path/'StudentAgeStudio/editor-state.json';state.parent.mkdir(exist_ok=True)
        order=list(map(int,self.talks));state.write_bytes(b.json_bytes({'order':order+order[:2]}))
        req=self.request();req['order']=list(reversed(order[:20]));self.store.save(req)
        expected=list(reversed(order[:20]))+order[20:]
        self.assertEqual(b.read_json(state)['order'],expected)
        self.assertEqual(list(b.read_json(self.cfg/'TalkCfg.json')),list(map(str,expected)))
    def test_failed_replace_rolls_back_all_changed_files(self):
        req=self.request();state=self.project.path/'StudentAgeStudio/editor-state.json'
        original=b.replace_file;failed=False
        def fail_once(src,dst):
            nonlocal failed
            if Path(dst)==self.cfg/'TalkCfg.json' and not failed:
                failed=True;raise OSError('simulated full disk')
            return original(src,dst)
        with patch.object(b,'replace_file',side_effect=fail_once):
            with self.assertRaises(OSError):self.store.save(req)
        self.assertTrue(failed)
        for name,data in self.before.items():self.assertEqual((self.cfg/name).read_bytes(),data)
        self.assertFalse(state.exists())
        self.assertTrue(self.store.save(req)['ok'])
    def test_validation_does_not_change_original_row_ids_or_nested_values(self):
        rows={'10000':{'id':55,'future':{'id':9}}};p=self.cfg/'TalkCfg.json';p.write_bytes(b.json_bytes(rows))
        loaded,bad=self.store.readable_maps(self.project)
        self.assertFalse(bad);self.assertEqual(loaded['TalkCfg.json'],rows)
        loaded['TalkCfg.json']['10000']['future']['id']=0
        self.assertEqual(b.read_json(p),rows)
    def test_no_named_premises_skips_recursive_writer_scan(self):
        state={};maps={'TalkCfg.json':self.talks}
        with patch.object(b,'premise_writers',side_effect=AssertionError('unnecessary scan')):
            self.assertEqual(b.reconcile_premises(state,{},maps,copy.deepcopy(maps)),set())
        self.assertEqual(maps['TalkCfg.json'],self.talks)
    def test_named_writer_removal_still_strips_readers(self):
        previous={'premises':{'1':{'eventId':100,'slot':7}}}
        original={'EvtCfg.json':{'100':{'id':100}},'TalkCfg.json':{'1':{'id':1,'effect':[[50,2,100,7,1]]}}}
        maps=copy.deepcopy(original);maps['TalkCfg.json']['1']['effect']=[];maps['TalkCfg.json']['1']['check']=[[111,2,100,7,0]]
        state=copy.deepcopy(previous);removed=b.reconcile_premises(state,previous,maps,original)
        self.assertEqual(removed,{(100,7)});self.assertEqual(state['premises'],{});self.assertEqual(maps['TalkCfg.json']['1']['check'],[])
        self.assertEqual(original['TalkCfg.json']['1']['effect'],[[50,2,100,7,1]])

if __name__=='__main__':unittest.main()
