"""Integration edge cases found while adapting ruoxingzhi's PR 3 to 1.3.11."""
import errno,json,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as b
import test_scoped_save as scoped
import test_original_dialogue as native_fixture
import original_dialogue,original_mode,event_ownership

class IntegrationSafetyTests(unittest.TestCase):
 setUp=scoped.ScopedSaveTests.setUp
 write=scoped.ScopedSaveTests.write
 save=scoped.ScopedSaveTests.save
 def test_shared_options_survive_event_deletion(self):
  talks={'1':{'id':1,'option':[9]},'2':{'id':2,'option':[9]},'3':{'id':3}}
  events={'10':{'id':10,'talkId':[1]},'20':{'id':20,'talkId':[2]}}
  options={'9':{'id':9,'talkId':[3]}}
  self.assertEqual(event_ownership.deletion(events,talks,options,{},None,['10']),({'1'},set()))
  self.write('TalkCfg',talks);self.write('OptionCfg',options);self.write('EvtCfg',events)
  self.save({'events':{'20':events['20']}})
  self.assertEqual(set(b.read_json(self.cfg/'TalkCfg.json')),{'2','3'})
  self.assertIn('9',b.read_json(self.cfg/'OptionCfg.json'))
 def test_explicit_table_deletion_still_works(self):
  self.write('EvtCfg',{})
  result=self.store.table_save({'projectId':self.project.id,'revision':self.store.revision(self.project),'name':'TalkCfg','scope':'local','externalDialogues':True,'rows':{'2':{'id':2,'content':'第二句'}}})
  self.assertNotIn('1',b.read_json(self.cfg/'TalkCfg.json'))
 def test_prune_keeps_current_and_unfinished_snapshots(self):
  root=self.project.path/'StudentAgeStudio/Backups';root.mkdir(parents=True,exist_ok=True)
  for i in range(22):
   p=root/('20260919-000000-'+format(i,'010x'));p.mkdir();(p/'transaction.json').write_text(json.dumps({'state':'committed'}),encoding='utf-8')
  current=root/'20260919-000000-0000000000'
  pending=root/'20260919-000001-0000000000';pending.mkdir();(pending/'transaction.json').write_text('{"state":"prepared"}',encoding='utf-8')
  self.store._prune_commit_backups(self.project,current=current)
  self.assertTrue(current.exists());self.assertTrue(pending.exists());self.assertEqual(len(list(root.iterdir())),21)
 def test_failed_restore_does_not_stop_remaining_files(self):
  changes={f'Cfgs/zh-cn/{n}.json':b'{"v":2}' for n in ['A','B','C']}
  for n in ['A','B','C']:(self.cfg/(n+'.json')).write_bytes(b'{"v":1}')
  real=b.replace_file;failing=[False]
  def replace(src,dst):
   dst=Path(dst)
   if dst==self.cfg/'C.json':failing[0]=True;raise OSError(errno.ENOSPC,'full')
   if failing[0] and dst==self.cfg/'B.json':raise PermissionError('locked')
   return real(src,dst)
  self.store.commit_warnings=[]
  with patch.object(b,'replace_file',side_effect=replace):
   with self.assertRaises(b.ApiError) as caught:self.store.commit(self.project,changes,raw=True)
  self.assertEqual(caught.exception.code,'rollback_failed');self.assertEqual((self.cfg/'A.json').read_bytes(),b'{"v":1}')
  snapshots=list((self.project.path/'StudentAgeStudio/Backups').glob('*/Cfgs/zh-cn/B.json'))
  self.assertTrue(snapshots);self.assertEqual(snapshots[-1].read_bytes(),b'{"v":1}')

class OriginalSafetyTests(unittest.TestCase):
 setUp=native_fixture.OriginalDialogueTests.setUp
 write=native_fixture.OriginalDialogueTests.write
 def test_invalid_json_can_open_but_cannot_save(self):
  target=self.project.path/original_mode.STATE;target.parent.mkdir(exist_ok=True,parents=True);target.write_bytes(b'{broken')
  with original_mode.scope(self.ident):
   doc=self.store.load(self.ident);self.assertTrue(any('记录损坏' in s for s in doc['warnings']))
   with self.assertRaises(b.ApiError):self.store.commit(self.store.project(self.ident),{'Cfgs/zh-cn/EvtCfg.json':b'{}'})
  self.assertEqual(target.read_bytes(),b'{broken')
 def test_idle_closes_without_another_access(self):
  h=self.store.original_dialogue;h.close()
  with patch.object(original_dialogue,'IDLE_CLOSE_SECONDS',.04):
   self.assertTrue(h.available());deadline=time.monotonic()+2
   while h._connection is not None and time.monotonic()<deadline:time.sleep(.01)
   self.assertIsNone(h._connection)
  self.assertTrue(h.available())
 def test_writer_closes_active_reader_before_replace(self):
  h=self.store.original_dialogue;self.assertTrue(h.available());old=h._connection
  original_dialogue.write(self.store.game,{'123':{'id':123,'content':'new'}},{})
  self.assertIsNone(h._connection);self.assertEqual(h.rows('TalkCfg',[123])['123']['content'],'new');self.assertIsNot(h._connection,old)
