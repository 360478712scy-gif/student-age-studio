"""Native CFG trigger/save regressions; temporary Mods only, no installed game needed."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as b
import external_dialogues as ext
import external_usages as usage

class ExternalUsesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        env=patch.dict(os.environ,{'STUDIO_CACHE_ROOT':str(root/'Cache')});env.start();self.addCleanup(env.stop)
        self.store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game')
        self.ident=self.store.create('用途测试')['id'];self.project=self.store.project(self.ident)
        self.write('TalkCfg',{'9001':{'id':9001,'content':'开场','nextTalk':[9002],'future':{'keep':9}},'9002':{'id':9002,'content':'下一句','nextTalk':[]}})
        self.write('PersonCfg',{'3':{'id':3,'name':'人物甲'},'4':{'id':4,'name':'人物乙'}})
        self.write('ItemCfg',{'10':{'id':10,'name':'礼物','value':10,'future':7}})
        self.write('PersonGrowCfg',{'3':{'id':3,'minigame':7},'4':{'id':4,'minigame':7}})
        self.write('MinigameCfg',{'7':{'id':7,'name':'已在人物绑定的游戏'}})
        self.write('MinigameActionCfg',{str(700+i):{'id':700+i,'startTalk':0,'winTalk':0,'loseTalk':0,'parms':[3,7],'effect':[[1,100,3]]} for i in range(1,6)})
    def write(self,name,rows):b.atomic_write(self.project.path/'Cfgs/zh-cn'/f'{name}.json',b.json_bytes(rows))
    def read(self,name):return b.read_json(self.project.path/'Cfgs/zh-cn'/f'{name}.json',{})
    def use(self,kind,**kw):return dict(id='use-'+kind,kind=kind,entryId=9001,gender='both',params={},**kw)
    def request(self,uses):
        d=ext.load(self.store,self.ident,b)
        return dict(projectId=self.ident,revision=d['revision'],talks=d['talks'],folders={'one':{'name':'夹子','talkIds':[9001,9002],'uses':uses}})
    def save(self,uses):return ext.save(self.store,self.request(uses),b)
    def test_gift_native_selection_and_next_dialogue(self):
        d=self.save([self.use('gift',npc=3,item=10,giftMode=0)])
        row=next(iter(self.read('GiftEvtCfg').values()))
        # BagMgr.GetGiftEvtCfgId / TryShowGiftEvt uses item, npc slot, then gender slot.
        self.assertEqual(row['item'],10);slot=row['npc'].index(3)
        self.assertEqual(row['talkId'][slot],[9001]);self.assertEqual(row['type'][slot],0);self.assertEqual(row['cond'],[])
        self.assertEqual(self.read('TalkCfg')['9001']['nextTalk'],[9002]);self.assertEqual(self.read('TalkCfg')['9001']['future'],{'keep':9})
        again=self.save(d['folders']['one']['uses']);self.assertEqual(again['folders'],d['folders'])
        self.assertEqual(len(self.read('GiftEvtCfg')),1)
    def test_existing_multi_recipient_gift_preserves_other_slots_and_fields(self):
        self.write('GiftEvtCfg',{'55':{'id':55,'item':10,'npc':[4,3],'talkId':[[8001,8002],[8011,8012]],'type':[1,0],'cond':[],'future':42}})
        d=self.save([self.use('gift',npc=3,item=10,giftMode=1,gender_override='unused')])
        row=self.read('GiftEvtCfg')['55'];self.assertEqual(row['talkId'],[[8001,8002],[9001]])
        self.assertEqual(row['npc'],[4,3]);self.assertEqual(row['future'],42);self.assertEqual(row['type'],[1,1])
        self.save([]);self.assertEqual(self.read('GiftEvtCfg')['55']['talkId'],[[8001,8002],[8011,8012]])
    def test_mini_all_five_levels_all_three_stages_resolve_from_person(self):
        uses=[self.use(kind,npc=3,level=level) for level in range(1,6) for kind in ('mini-start','mini-win','mini-lose')]
        for i,u in enumerate(uses):u['id']=str(i)
        self.save(uses)
        for level in range(1,6):
            row=self.read('MinigameActionCfg')[str(700+level)]
            self.assertEqual([row[k] for k in ('startTalk','winTalk','loseTalk')],[9001]*3)
            self.assertEqual(row['parms'],[3,7]);self.assertEqual(row['effect'],[[1,100,3]])
        self.assertEqual(self.read('PersonGrowCfg')['3']['minigame'],7)
    def test_missing_game_or_stage_and_sixth_level_rejected_without_writes(self):
        before=self.read('MinigameActionCfg')
        for npc,level in ((3,6),(3,0),(999,1)):
            with self.assertRaises(b.ApiError):self.save([self.use('mini-start',npc=npc,level=level)])
        self.write('MinigameActionCfg',{'701':before['701']})
        with self.assertRaises(b.ApiError):self.save([self.use('mini-start',npc=3,level=5)])
        self.assertEqual(self.read('MinigameActionCfg'),{'701':before['701']})
    def test_shared_game_conflict_is_rejected_atomically(self):
        one=self.use('mini-start',npc=3,level=1);two=self.use('mini-start',npc=4,level=1);two['id']='two'
        p=self.request([one,two]);p['talks']['9001']['content']='must rollback'
        with self.assertRaises(b.ApiError):ext.save(self.store,p,b)
        self.assertEqual(self.read('TalkCfg')['9001']['content'],'开场');self.assertEqual(self.read('MinigameActionCfg')['701']['startTalk'],0)
    def test_duplicate_gift_rules_not_silently_shadowed(self):
        self.write('GiftEvtCfg',{str(i):{'id':i,'item':10,'npc':[3],'talkId':[[i]],'cond':[]} for i in (1,2)})
        with self.assertRaises(b.ApiError):self.save([self.use('gift',npc=3,item=10,giftMode=0)])
        self.assertEqual(self.read('GiftEvtCfg')['1']['talkId'],[[1]])
    def test_gender_branch_keeps_other_entry_and_unlinks(self):
        self.write('IntentCfg',{'1':{'id':1,'finishTalk':[8011,8012],'reward':[[1,2,3]]}})
        u=self.use('goal-finish',recordId=1);u['gender']='female';self.save([u])
        self.assertEqual(self.read('IntentCfg')['1']['finishTalk'],[8011,9001])
        self.save([]);self.assertEqual(self.read('IntentCfg')['1']['finishTalk'],[8011,8012])
    def test_negotiation_phase_does_not_shift_other_phases(self):
        self.write('NegotiationCfg',{'1':{'id':1,'talks':[8001,8002,8003],'talks2':[]}})
        self.save([self.use('negotiation-talks2-1',recordId=1)])
        r=self.read('NegotiationCfg')['1'];self.assertEqual(r['talks'],[8001,8002,8003]);self.assertEqual(r['talks2'],[8001,9001,8003])
    def test_answer_parallel_arrays_preserve_other_answers(self):
        self.write('TalkInputMinigameCfg',{'1':{'id':1,'inputs':['甲','乙'],'jumps':[[8001],[8002]],'talkId':[8003]}})
        self.save([self.use('input-match',recordId=1,answer='乙')])
        r=self.read('TalkInputMinigameCfg')['1'];self.assertEqual(r['inputs'],['甲','乙']);self.assertEqual(r['jumps'],[[8001],[9001]]);self.assertEqual(r['talkId'],[8003])
    def test_foreign_edit_conflict_can_detach_without_overwriting(self):
        d=self.save([self.use('mini-start',npc=3,level=1)])
        r=self.read('MinigameActionCfg');r['701']['startTalk']=9999;self.write('MinigameActionCfg',r)
        with self.assertRaises(b.ApiError):self.save(d['folders']['one']['uses'])
        self.save([]);self.assertEqual(self.read('MinigameActionCfg')['701']['startTalk'],9999)
    def test_bound_entry_cannot_be_deleted_without_reassigning(self):
        d=self.save([self.use('mini-start',npc=3,level=1)])
        p=self.request(d['folders']['one']['uses']);del p['talks']['9001'];p['folders']['one']['talkIds']=[9002]
        with self.assertRaises(b.ApiError):ext.save(self.store,p,b)
        self.assertIn('9001',self.read('TalkCfg'))
    def test_existing_event_callback_keeps_folder_visible_after_save(self):
        self.write('EvtCfg',{'7':{'id':7,'talkId':[7001]}})
        rows=self.read('TalkCfg');rows['7001']={'id':7001,'content':'事件','option':[71]};self.write('TalkCfg',rows)
        self.write('OptionCfg',{'71':{'id':71,'talkId':[],'talkId2':[],'future':7}})
        d=self.save([self.use('OptionCfg-success',recordId=71)])
        self.assertIn('9001',d['talks']);self.assertNotIn('7001',d['talks'])
        self.assertEqual(d['folders']['one']['talkIds'],[9001,9002]);self.save(d['folders']['one']['uses'])
        p=self.request([]);p['folders']={};d=ext.save(self.store,p,b)
        self.assertIn('9001',d['talks']);self.assertIn('9002',d['talks']);self.assertEqual(d['folders'],{})
    def test_stale_revision_rejected(self):
        p=self.request([self.use('mini-start',npc=3,level=1)])
        self.write('ItemCfg',{'10':{'id':10,'value':11}})
        with self.assertRaises(b.ApiError) as e:ext.save(self.store,p,b)
        self.assertEqual(e.exception.status,409);self.assertEqual(self.read('MinigameActionCfg')['701']['startTalk'],0)
    def test_reserved_dead_cfg_not_offered_as_working_trigger(self):
        with self.assertRaises(b.ApiError):self.save([self.use('love-greeting',recordId=1)])

    def test_rename_updates_real_refs_and_binding_ledger(self):
        self.save([self.use('mini-start',npc=3,level=1)])
        self.store.record_ids.rename({'projectId':self.ident,'revision':self.store.revision(self.project),'table':'TalkCfg','oldId':9001,'newId':9011})
        d=ext.load(self.store,self.ident,b);u=d['folders']['one']['uses'][0]
        self.assertEqual(u['entryId'],9011);self.assertEqual(u['_target']['written'],9011)
        self.assertEqual(self.read('MinigameActionCfg')['701']['startTalk'],9011)
        p=dict(projectId=self.ident,revision=d['revision'],talks=d['talks'],folders=d['folders'])
        ext.save(self.store,p,b)
        for table,field,value in [('TalkInputMinigameCfg','jumps',[[9001,99]]),('NegotiationCfg','talks',[99,9001,44]),('LoveDrawCfg','talkId',[9001])]:
            revised=self.store.record_ids.rewrite(table,{'1':{'id':1,field:value}},{'TalkCfg':{'9001':9011}})
            self.assertNotIn('9001',str(revised))
    def test_readonly_cannot_bind(self):
        readonly=self.store.workshop/'ReadOnly';(readonly/'Cfgs/zh-cn').mkdir(parents=True)
        b.atomic_write(readonly/'manifest.json',b.json_bytes({'name':'只读模组'}))
        b.atomic_write(readonly/'Cfgs/zh-cn/TalkCfg.json',b.json_bytes(self.read('TalkCfg')))
        project=next(p for p in self.store.projects() if p.readonly)
        with self.assertRaises(b.ApiError):ext.save(self.store,dict(projectId=project.id,revision=self.store.revision(project),talks=self.read('TalkCfg'),folders={}),b)
    def test_person_binding_change_moves_stage_entry_without_editing_game_choice(self):
        d=self.save([self.use('mini-start',npc=3,level=1)])
        self.write('PersonGrowCfg',{'3':{'id':3,'minigame':8}})
        self.write('MinigameCfg',{'7':{'id':7},'8':{'id':8}})
        rows=self.read('MinigameActionCfg');rows['801']={'id':801,'startTalk':77};self.write('MinigameActionCfg',rows)
        self.save(d['folders']['one']['uses'])
        self.assertEqual(self.read('MinigameActionCfg')['701']['startTalk'],0)
        self.assertEqual(self.read('MinigameActionCfg')['801']['startTalk'],9001)

if __name__=='__main__':unittest.main()
