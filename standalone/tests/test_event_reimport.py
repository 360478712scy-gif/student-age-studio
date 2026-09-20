"""Original-event deletion/reimport and explicit save acknowledgements."""
import copy
import unittest
import server as b
import save_review
import test_original_dialogue as fixture
from test_original_dialogue import ORIGINAL_EVENTS, ORIGINAL_TALKS

class EventReimportTests(unittest.TestCase):
    setUp = fixture.OriginalDialogueTests.setUp
    write = fixture.OriginalDialogueTests.write

    def restore(self):
        return self.store.restore_original_event({'projectId':self.ident,'revision':self.store.revision(self.project),'eventId':1001})

    def test_delete_save_reimport_restores_graph_and_options(self):
        data=self.store.load(self.ident)
        self.store.save({'projectId':self.ident,'revision':data['revision'],'events':{'1500000':data['events']['1500000']},'deletedIds':[1001001,1001002,1001003]})
        self.assertIn('1001001', b.flat_deletions(b.read_json(self.project.path/'StudentAgeStudio/deleted-talks.json',{})))
        self.restore()
        loaded=self.store.load(self.ident)
        for key in ['1001001','1001002','1001003']:
            for field,value in ORIGINAL_TALKS[key].items():self.assertEqual(loaded['talks'][key][field],value)
        self.assertIn('100101',loaded['options'])
        self.assertEqual(loaded['events']['1001']['talkId'],[1001001])
        self.store.save({'projectId':self.ident,'revision':loaded['revision'],'talks':loaded['talks']})

    def test_orphan_empty_overrides_can_be_explicitly_reimported(self):
        self.write('TalkCfg',{k:b.inert_talk(k,[]) for k in ['1001001','1001002','1001003']})
        self.write('EvtCfg',{'1001':{**ORIGINAL_EVENTS['1001'],'talkId':[]}})
        self.restore()
        data=self.store.load(self.ident)
        self.assertEqual(data['events']['1001']['talkId'],[1001001])
        self.assertEqual(data['talks']['1001001']['content'],'原版一')

    def test_reimport_preserves_real_local_edits_and_other_events(self):
        self.write('TalkCfg',{'1001002':{**ORIGINAL_TALKS['1001002'],'content':'用户修改'},'1003001':{**ORIGINAL_TALKS['1003001'],'content':'别的剧情'}})
        self.restore()
        loaded=self.store.load(self.ident)
        self.assertEqual(loaded['talks']['1001002']['content'],'用户修改')
        self.assertEqual(loaded['talks']['1003001']['content'],'别的剧情')

    def test_first_import_in_clean_mod(self):
        self.write('TalkCfg',{});self.write('EvtCfg',{})
        self.restore()
        self.assertEqual(self.store.load(self.ident)['talks']['1001001']['content'],'原版一')

    def test_hidden_tombstones_do_not_block_later_full_save(self):
        self.write('TalkCfg',{'1001001':b.inert_talk('1001001',[]),'1500000001':{'id':1500000001,'content':'保留'}})
        target=self.project.path/'StudentAgeStudio/deleted-talks.json';target.parent.mkdir(exist_ok=True);target.write_bytes(b.json_bytes({'1001001':[]}))
        data=self.store.load(self.ident)
        self.store.save({'projectId':self.ident,'revision':data['revision'],'talks':data['talks']})
        self.assertEqual(b.read_json(self.cfg/'TalkCfg.json')['1001001'],b.inert_talk('1001001',[]))

    def test_external_revision_requires_fresh_explicit_confirmation(self):
        payload={'projectId':self.ident,'revision':self.store.revision(self.project),'talkPatch':{'version':1,'upsert':{'1500000001':{'id':1500000001,'content':'用户草稿'}},'deleted':[]}}
        self.write('TalkCfg',{'1500000001':{'id':1500000001,'content':'外部修改'}})
        with self.assertRaises(b.ApiError) as first:save_review.perform(self.store.save,copy.deepcopy(payload),b.ApiError)
        self.assertEqual(first.exception.code,'save_warnings')
        self.write('TalkCfg',{'1500000001':{'id':1500000001,'content':'再次修改'}})
        with self.assertRaises(b.ApiError) as second:save_review.perform(self.store.save,{**payload,'_confirmedSaveWarnings':first.exception.warnings},b.ApiError)
        self.assertNotEqual(first.exception.warnings,second.exception.warnings)
        save_review.perform(self.store.save,{**payload,'_confirmedSaveWarnings':second.exception.warnings},b.ApiError)
        self.assertEqual(b.read_json(self.cfg/'TalkCfg.json')['1500000001']['content'],'用户草稿')

    def test_missing_rows_ask_then_preserve_disk_rows(self):
        original=(self.cfg/'TalkCfg.json').read_bytes()
        payload={'projectId':self.ident,'revision':self.store.revision(self.project),'talks':{'1500000001':{'id':1500000001,'content':'新正文'}}}
        with self.assertRaises(b.ApiError) as error:save_review.perform(self.store.save,payload,b.ApiError)
        self.assertEqual(error.exception.code,'save_warnings')
        self.assertEqual((self.cfg/'TalkCfg.json').read_bytes(),original)
        save_review.perform(self.store.save,{**payload,'_confirmedSaveWarnings':error.exception.warnings},b.ApiError)
        rows=b.read_json(self.cfg/'TalkCfg.json')
        self.assertEqual(rows['1003001']['content'],'模组改写的丙')
        self.assertEqual(rows['1500000001']['content'],'新正文')

    def test_segmented_external_edit_confirmation_preserves_unsubmitted_rows(self):
        descriptor=self.store.talk_segments.open(self.ident)
        token=descriptor['segmentedTalks']['generation']
        payload={'projectId':self.ident,'revision':descriptor['revision'],'talkGeneration':token,
                 'talkPatch':{'version':1,'upsert':{'1500000001':{'id':1500000001,'content':'确认的草稿'}},'deleted':[]}}
        rows=b.read_json(self.cfg/'TalkCfg.json');rows['1003001']['content']='外部修改其他句'
        self.write('TalkCfg',rows)
        generation=self.store.talk_segments.get(self.ident,token)
        self.assertEqual(__import__('json').loads(generation.page(['1003001'])['rows'][0][1])['content'],'模组改写的丙')
        with self.assertRaises(b.ApiError) as error:save_review.perform(self.store.save,copy.deepcopy(payload),b.ApiError)
        self.assertEqual(error.exception.code,'save_warnings')
        save_review.perform(self.store.save,{**payload,'_confirmedSaveWarnings':error.exception.warnings},b.ApiError)
        saved=b.read_json(self.cfg/'TalkCfg.json')
        self.assertEqual(saved['1500000001']['content'],'确认的草稿')
        self.assertEqual(saved['1003001']['content'],'外部修改其他句')

    def test_semantic_manifest_warning_can_be_confirmed(self):
        payload={'projectId':self.ident,'revision':self.store.revision(self.project),'manifest':{'description':'字'*20001}}
        before=(self.project.path/'manifest.json').read_bytes()
        with self.assertRaises(b.ApiError) as error:save_review.perform(self.store.manifest_save,payload,b.ApiError)
        self.assertEqual(error.exception.code,'save_warnings')
        self.assertEqual(before,(self.project.path/'manifest.json').read_bytes())
        save_review.perform(self.store.manifest_save,{**payload,'_confirmedSaveWarnings':error.exception.warnings},b.ApiError)
        self.assertEqual(b.read_json(self.project.path/'manifest.json')['description'],'字'*20001)

    def test_raw_json_save_can_acknowledge_external_edit(self):
        payload={'projectId':self.ident,'revision':self.store.revision(self.project),
                 'path':'Cfgs/zh-cn/TalkCfg.json','text':'{"1500000001":{"id":1500000001,"content":"JSON 草稿"}}'}
        self.write('TalkCfg',{'1500000001':{'id':1500000001,'content':'外部'}})
        with self.assertRaises(b.ApiError) as error:save_review.perform(self.store.json_save,payload,b.ApiError)
        self.assertEqual(error.exception.code,'save_warnings')
        save_review.perform(self.store.json_save,{**payload,'_confirmedSaveWarnings':error.exception.warnings},b.ApiError)
        self.assertEqual(b.read_json(self.cfg/'TalkCfg.json')['1500000001']['content'],'JSON 草稿')

    def test_romance_semantic_warning_retains_authored_values(self):
        import romance_settings
        row={'enabled':True,'male':False,'female':False,'minGrade':7,'minRelation':4,'minFavor':1,'favorWeight':.5,'attrWeight':.5}
        writer=lambda payload:romance_settings.validate({'3':row},{'3':{}},set(),{},b)
        with self.assertRaises(b.ApiError) as error:save_review.perform(writer,{},b.ApiError)
        self.assertEqual(error.exception.code,'save_warnings')
        result=save_review.perform(writer,{'_confirmedSaveWarnings':error.exception.warnings},b.ApiError)
        self.assertEqual(result['3'],row)
