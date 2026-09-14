"""Explicit talk deltas preserve unloaded records and revision/transaction guarantees."""
import copy
import unittest
from unittest.mock import patch
from test_save_large import LargeSaveTests
import server as b

class TalkPatchTests(LargeSaveTests):
    def request(self):
        row=copy.deepcopy(self.talks['10005']);row['content']='增量修改'
        return dict(projectId=self.ident,revision=self.store.revision(self.project),talkPatch={'version':1,'upsert':{'10005':row},'deleted':[]})
    # Inherited rollback/order/validation tests also exercise the new path.
    def test_one_line_preserves_all_events_rows_unknowns_and_backup(self):
        req=self.request();original=copy.deepcopy(req);result=self.store.save(req)
        expected=copy.deepcopy(self.talks);expected.update(req['talkPatch']['upsert'])
        self.assertEqual(b.read_json(self.cfg/'TalkCfg.json'),expected);self.assertEqual(req,original)
        for name,data in self.before.items():
            if name!='TalkCfg.json':self.assertEqual((self.cfg/name).read_bytes(),data)
        self.assertEqual((b.Path(result['backup'])/'Cfgs/zh-cn/TalkCfg.json').read_bytes(),self.before['TalkCfg.json'])
    def test_original_overrides_keep_hidden_custom_rows_and_catalog(self):
        import original_mode
        base={'1':{'id':1,'content':'原版','nextTalk':[]},'2':{'id':2,'content':'其他原版'}}
        catalog={'tables':{'TalkCfg':base}}
        with patch.object(self.store,'catalog',return_value=catalog), original_mode.scope(self.ident):
            req=self.request();req['talkPatch']={'version':1,'upsert':{'1':{**base['1'],'content':'原版覆盖'}},'deleted':[]}
            self.store.save(req)
        saved=b.read_json(self.cfg/'TalkCfg.json');expected={**self.talks,'1':{**base['1'],'content':'原版覆盖'}}
        self.assertEqual(saved,expected);self.assertEqual(base['1']['content'],'原版');self.assertNotIn('2',saved)
    def test_external_change_rejects_without_touching_any_file(self):
        req=self.request();p=self.cfg/'TalkCfg.json';p.write_bytes(b.json_bytes({**self.talks,'99999':{'id':99999,'content':'内置新增'}}));changed=p.read_bytes()
        with self.assertRaises(b.ApiError) as caught:self.store.save(req)
        self.assertEqual(caught.exception.status,409);self.assertEqual(p.read_bytes(),changed)
    def test_empty_patch_is_not_deletion(self):
        req=self.request();req['talkPatch']['upsert']={};self.store.save(req)
        self.assertEqual((self.cfg/'TalkCfg.json').read_bytes(),self.before['TalkCfg.json'])
    def test_explicit_delete_and_undo_restore(self):
        req=self.request();req['talkPatch']={'version':1,'upsert':{},'deleted':[10019]};result=self.store.save(req)
        self.assertNotIn('10019',b.read_json(self.cfg/'TalkCfg.json'))
        req.update(revision=result['revision'],talkPatch={'version':1,'upsert':{'10019':self.talks['10019'],'10018':self.talks['10018']},'deleted':[]})
        self.store.save(req);self.assertEqual(b.read_json(self.cfg/'TalkCfg.json'),self.talks)
    def test_bad_protocol_fails_before_write(self):
        bad=[None,{}, {'version':2,'upsert':{},'deleted':[]},{'version':1,'upsert':{},'deleted':['bad']},{'version':1,'upsert':{'10005':{'id':10006}},'deleted':[]},{'version':1,'upsert':{'10005':{'id':10005}},'deleted':[10005]}]
        for value in bad:
            with self.subTest(value=value):
                req=self.request();req['talkPatch']=value
                with self.assertRaises(b.ApiError):self.store.save(req)
                for name,data in self.before.items():self.assertEqual((self.cfg/name).read_bytes(),data)
    def test_ambiguous_full_and_partial_rejected(self):
        req=self.request();req['talks']={}
        with self.assertRaises(b.ApiError):self.store.save(req)
    def test_corrupt_source_never_merged(self):
        p=self.cfg/'TalkCfg.json';p.write_text('{invalid');req=self.request()
        with self.assertRaises(b.ApiError):self.store.save(req)
        self.assertEqual(p.read_text(),'{invalid')

if __name__=='__main__':unittest.main()
