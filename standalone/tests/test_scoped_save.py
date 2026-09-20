"""Selective saves agree with the full path and do not read unrelated JSON."""
import copy,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as b
class ScopedSaveTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  env=patch.dict(os.environ,{'STUDIO_CACHE_ROOT':str(self.root/'Cache'),'STUDIO_USER_DATA_ROOT':str(self.root/'User'),'STUDIO_BACKUP_ROOT':str(self.root/'Backups')});env.start();self.addCleanup(env.stop)
  self.store=b.StudioStore(self.root/'Mods',self.root/'Workshop',self.root/'Game',asset_settings_path=self.root/'assets.json')
  def finish_background_index():
   # The real hash worker writes its index asynchronously; finish before the
   # environment and temporary directory are removed by later cleanups.
   deadline=time.monotonic()+5
   while self.store.asset_catalog.hash_progress()['running'] and time.monotonic()<deadline:time.sleep(.01)
   self.assertFalse(self.store.asset_catalog.hash_progress()['running'])
   self.store.close()
  self.addCleanup(finish_background_index)
  self.project=self.store.project(self.store.create('Scoped save')['id']);self.cfg=self.project.path/'Cfgs/zh-cn'
  self.write('TalkCfg',{'1':{'id':1,'content':'原文','nextTalk':[2],'future':{'keep':[1,2]}},'2':{'id':2,'content':'第二句'}})
  self.write('EvtCfg',{'1':{'id':1,'talkId':[1]}});self.write('OptionCfg',{})
  self.write('ItemCfg',{'10':{'id':10,'name':'物品','icon':'Mods/test/old.png','future':[1,2]}})
  self.write('BookCfg',{});self.write('ShopCfg',{})
  self.write('FutureCfg',{'1':{'id':1,'keep':'不读也不改'}})
 def write(self,name,rows):(self.cfg/(name+'.json')).write_bytes(b.json_bytes(rows))
 def save(self,data):return self.store.save({'projectId':self.project.id,'revision':self.store.revision(self.project),**data})
 def test_regular_patch_avoids_unrelated_tables(self):
  row=b.read_json(self.cfg/'TalkCfg.json')['1'];row['content']='新文'
  with patch.object(b,'read_json',wraps=b.read_json) as read:self.save({'talkPatch':{'version':1,'upsert':{'1':row},'deleted':[]}})
  self.assertFalse(any(Path(c.args[0]).name in ('FutureCfg.json','ItemCfg.json') for c in read.call_args_list))
  self.assertEqual(b.read_json(self.cfg/'TalkCfg.json')['1']['future'],{'keep':[1,2]})
 def test_scoped_and_full_save_are_equivalent(self):
  cfg_before={p.name:p.read_bytes() for p in self.cfg.iterdir()}
  state=self.project.path/'StudentAgeStudio/editor-state.json'
  for kind in ('text','add','option','premise'):
   with self.subTest(kind=kind):
    for name,data in cfg_before.items():(self.cfg/name).write_bytes(data)
    state.unlink(missing_ok=True)
    if kind=='premise':state.write_bytes(b.json_bytes({'premises':{'1':{'id':1,'name':'前提','eventId':1,'slot':1000000,'talkId':1}}}))
    state_before=state.read_bytes() if state.exists() else None
    talks=b.read_json(self.cfg/'TalkCfg.json');talks['1']['content']='改文'
    payload={'talks':talks}
    if kind=='add':talks['3']={'id':3,'content':'增加','nextTalk':[]};talks['2']['nextTalk']=[3]
    if kind=='option':payload['options']={'5':{'id':5,'content':'选项','talkId':[2]}};talks['1']['option']=[5]
    self.save(copy.deepcopy(payload));scoped={p.name:p.read_bytes() for p in self.cfg.iterdir()};scoped_state=b.read_json(state,{})
    for name,data in cfg_before.items():(self.cfg/name).write_bytes(data)
    if state_before is None:state.unlink(missing_ok=True)
    else:state.write_bytes(state_before)
    with patch.object(self.store,'story_save_maps',side_effect=lambda project,payload:self.store.readable_maps(project)):self.save(copy.deepcopy(payload))
    self.assertEqual(scoped,{p.name:p.read_bytes() for p in self.cfg.iterdir()});self.assertEqual(scoped_state,b.read_json(state,{}))
 def test_warm_save_never_opens_or_rewrites_unrelated_json(self):
  self.store.revision(self.project)
  untouched={p:(p.read_bytes(),b.file_fingerprint(p)) for p in self.cfg.iterdir() if p.name!='TalkCfg.json'}
  original_open=Path.open;opened=[]
  def tracked(path,*args,**kwargs):
   if path.parent==self.cfg:opened.append(path.name)
   return original_open(path,*args,**kwargs)
  with patch.object(Path,'open',tracked):self.save({'talkPatch':{'version':1,'upsert':{'1':{'id':1,'content':'只改这句','nextTalk':[2]}},'deleted':[]}})
  self.assertNotIn('FutureCfg.json',opened);self.assertNotIn('ItemCfg.json',opened)
  for path,(data,stamp) in untouched.items():self.assertEqual(path.read_bytes(),data);self.assertEqual(b.file_fingerprint(path),stamp)
 def test_deletion_uses_full_reference_pass(self):
  with patch.object(b,'read_json',wraps=b.read_json) as read:self.save({'talkPatch':{'version':1,'upsert':{},'deleted':[2]}})
  self.assertTrue(any(Path(c.args[0]).name=='FutureCfg.json' for c in read.call_args_list))
 def test_warehouse_image_save_skips_dialogue_and_keeps_unknown_fields(self):
  tables={n:b.read_json(self.cfg/(n+'.json')) for n in ('ItemCfg','BookCfg','ShopCfg')};tables['ItemCfg']['10']['icon']='Mods/test/new.png'
  with patch.object(b,'read_json',wraps=b.read_json) as read:self.store.warehouse_save({'projectId':self.project.id,'revision':self.store.revision(self.project),'tables':tables,'migrations':[]})
  self.assertFalse(any(Path(c.args[0]).name in ('TalkCfg.json','FutureCfg.json') for c in read.call_args_list))
  self.assertEqual(b.read_json(self.cfg/'ItemCfg.json')['10']['future'],[1,2])
 def test_command_menu_only_reads_premise_metadata(self):
  folder=self.project.path/'StudentAgeStudio';folder.mkdir(exist_ok=True)
  (folder/'editor-state.json').write_bytes(b.json_bytes({'premises':{'1':{'id':1,'name':'保留前提','talkId':1}}}))
  self.store.revision(self.project)
  with patch.object(b,'read_json',wraps=b.read_json) as read:result=self.store.premise_state(self.project.id)
  self.assertEqual(result['premises']['1']['name'],'保留前提')
  self.assertFalse(any(Path(c.args[0]).parent==self.cfg for c in read.call_args_list))
 def test_workshop_counts_reuse_unchanged_file(self):
  self.store.workshop_info(self.project.id)
  self.write('ItemCfg',{'11':{'id':11},'12':{'id':12}})
  with patch.object(b,'read_json',wraps=b.read_json) as read:info=self.store.workshop_info(self.project.id)
  self.assertFalse(any(Path(c.args[0]).name=='TalkCfg.json' for c in read.call_args_list))
  self.assertEqual(next(t['localCount'] for t in info['tables'] if t['name']=='ItemCfg'),2)
 def test_conflict_guard_survives_scoped_save(self):
  revision=self.store.revision(self.project);self.write('FutureCfg',{'1':{'id':1,'keep':'外部改动'}})
  with self.assertRaises(b.ApiError) as error:self.store.save({'projectId':self.project.id,'revision':revision,'talkPatch':{'version':1,'upsert':{},'deleted':[]}})
  self.assertEqual(error.exception.status,409)
 def test_revision_only_rereads_changed_file_and_detects_restored_mtime(self):
  old=self.store.revision(self.project);unchanged=self.cfg/'FutureCfg.json';original_open=Path.open;opened=[]
  def tracked(path,*args,**kwargs):
   if args and args[0]=='rb':opened.append(path)
   return original_open(path,*args,**kwargs)
  target=self.cfg/'ItemCfg.json';stat=target.stat();target.write_bytes(target.read_bytes().replace(b'old.png',b'new.png'));os.utime(target,ns=(stat.st_atime_ns,stat.st_mtime_ns))
  with patch.object(Path,'open',tracked):new=self.store.revision(self.project)
  self.assertNotEqual(old,new);self.assertNotIn(unchanged,opened);self.assertIn(target,opened)
  self.store._revision_cache.clear();self.store._revision_file_digests.clear();self.assertEqual(new,self.store.revision(self.project))
 def test_item_only_change_can_keep_story_generation_and_dirty_delta(self):
  descriptor=self.store.talk_segments.open(self.project.id);token=descriptor['segmentedTalks']['generation'];old=descriptor['revision']
  self.write('ItemCfg',{'10':{'id':10,'name':'新物品'}})
  # Ordinary feature writes advance the I/O guard through the HTTP generation header,
  # but must not pretend the story document has already received that revision.
  self.store.talk_segments.saved(self.project,token,self.store.revision(self.project))
  result=self.store.talk_segments.refresh_revision(self.project.id,token,old)
  self.assertTrue(result['unchangedStory']);self.assertNotEqual(result['revision'],old)
  page=self.store.talk_segments.get(self.project.id,token).page(['1'])
  self.assertEqual(page['revision'],result['revision'])
  row=json.loads(page['rows'][0][1]);row['content']='保留的剧情草稿'
  self.store.save({'projectId':self.project.id,'revision':result['revision'],'talkGeneration':token,'talkPatch':{'version':1,'upsert':{'1':row},'deleted':[]}})
  self.assertEqual(b.read_json(self.cfg/'TalkCfg.json')['1']['content'],'保留的剧情草稿')
  self.assertEqual(b.read_json(self.cfg/'ItemCfg.json')['10']['name'],'新物品')
 def test_changed_story_or_metadata_does_not_advance_generation(self):
  for name in ('TalkCfg','PersonCfg','EvtCfg','editor-state'):
   with self.subTest(name=name):
    descriptor=self.store.talk_segments.open(self.project.id);token=descriptor['segmentedTalks']['generation'];old=descriptor['revision']
    if name=='editor-state':(self.project.path/'StudentAgeStudio').mkdir(exist_ok=True);(self.project.path/'StudentAgeStudio/editor-state.json').write_bytes(b.json_bytes({'order':[2,1]}))
    else:self.write(name,{'1':{'id':1,'content':'外部改动','name':'新名字'}})
    # The immutable draft stays readable, but must not adopt an external revision.
    self.assertEqual(self.store.talk_segments.get(self.project.id,token).page(['1'])['revision'],old)
    self.assertFalse(self.store.talk_segments.refresh_revision(self.project.id,token,old)['unchangedStory'])
    self.store.talk_segments.saved(self.project,token,self.store.revision(self.project))
    self.assertFalse(self.store.talk_segments.refresh_revision(self.project.id,token,old)['unchangedStory'])
 def test_unrelated_refresh_rejects_wrong_revision_and_damaged_cache(self):
  descriptor=self.store.talk_segments.open(self.project.id);token=descriptor['segmentedTalks']['generation'];old=descriptor['revision'];generation=self.store.talk_segments.get(self.project.id,token)
  self.write('ItemCfg',{'10':{'id':10,'name':'新物品'}})
  self.assertFalse(self.store.talk_segments.refresh_revision(self.project.id,token,'wrong')['unchangedStory'])
  (generation.path/'records.json').write_bytes(b'{}')
  self.assertFalse(self.store.talk_segments.refresh_revision(self.project.id,token,old)['unchangedStory'])
 def test_item_thumbnails_keep_full_image_for_import_and_skip_people(self):
  from PIL import Image
  import urllib.parse
  image=self.project.path/'item.png';Image.new('RGBA',(1600,1200),(40,100,200,128)).save(image)
  self.write('ItemCfg',{'10':{'id':10,'name':'图片','icon':'Mods/'+self.project.path.name+'/item.png'}})
  query={'projectId':self.project.id,'revision':self.store.revision(self.project),'kind':'item','source':'mod','sourceProjectId':self.project.id}
  with patch.object(self.store.asset_catalog,'_people',side_effect=AssertionError('item must not load people')):result=self.store.asset_catalog.list(query)
  args=dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(result['items'][0]['previewUrl']).query))
  full=self.store.asset_catalog.preview(args);thumb=self.store.asset_catalog.preview({**args,'thumbnail':'1'})
  self.assertEqual(full,image);self.assertNotEqual(full,thumb)
  self.assertEqual(self.store.asset(self.project.id,args['path']) if 'path' in args else self.store.asset(self.project.id,'Mods/'+self.project.path.name+'/item.png'),image)
  self.assertEqual(self.store.asset(self.project.id,'Mods/'+self.project.path.name+'/item.png',thumbnail=True),thumb)
  with Image.open(thumb) as im:self.assertLessEqual(im.width,480);self.assertLessEqual(im.height,320)
  with Image.open(full) as im:self.assertEqual(im.size,(1600,1200))
if __name__=='__main__':unittest.main()
