import copy,json,unittest
from unittest.mock import patch
from pathlib import Path
from test_scoped_save import ScopedSaveTests
import server as b
import external_dialogues as ext
import text_record_save as text_save

class EventUpdateTests(unittest.TestCase):
 setUp=ScopedSaveTests.setUp
 write=ScopedSaveTests.write
 save=ScopedSaveTests.save
 # Keep this suite focused; inherited cases run in their own existing suite.
 def test_record_save_warm_reads_only_changed_record(self):
  source='{"1": {"id":1,"content":"旧的文字","nextTalk":[2],"future":1.23000},\n"2":{"id":2,"content":"保留 2","unknown":{"x":true}}}\n'
  (self.cfg/'TalkCfg.json').write_text(source)
  first=json.loads(source)['1'];first['content']='首次';self.save({'talkPatch':{'version':1,'upsert':{'1':first},'deleted':[]}})
  original=(self.cfg/'TalkCfg.json').read_bytes();first['content']='第二次修改更长的中文'
  old_index=text_save._CACHE[str((self.cfg/'TalkCfg.json').resolve())][1]
  with patch.object(b,'read_json',wraps=b.read_json) as read:
   self.save({'talkPatch':{'version':1,'upsert':{'1':first},'deleted':[]}})
  self.assertFalse(any(Path(c.args[0]).parent==self.cfg for c in read.call_args_list))
  actual=(self.cfg/'TalkCfg.json').read_bytes()
  self.assertEqual(actual,original.replace('首次'.encode(),'第二次修改更长的中文'.encode()))
  self.assertIn(b'1.23000',actual)
  self.assertEqual(text_save._CACHE[str((self.cfg/'TalkCfg.json').resolve())][1]['1'][0],old_index['1'][0])
  # A same-mtime external edit must invalidate the byte offsets.
  self.write('TalkCfg',{'1':{'id':1,'content':'外部新文件'},'2':{'id':2,'content':'保留'}})
  self.save({'talkPatch':{'version':1,'upsert':{'1':{'id':1,'content':'索引重建'}},'deleted':[]}})
  self.assertEqual(b.read_json(self.cfg/'TalkCfg.json')['2']['content'],'保留')
 def test_event_gift_shared_folder_and_external_entry(self):
  self.write('PersonCfg',{'3':{'id':3,'name':'人物'}})
  self.write('GiftEvtCfg',{})
  event={'id':1,'type':110,'title':'送礼事件','talkId':[1], 'maxcount':1,'rate':1,'studioGiftCounterSlot':-1,'condition':[], 'studioGiftBindings':[{'id':8,'index':0,'npc':3}]}
  native={'8':{'id':8,'item':10,'npc':[3],'talkId':[[1]],'type':[0],'cond':[[111,-1,1,-1,0]],'future':{'keep':1}}}
  self.save({'events':{'1':event},'giftEvents':native})
  metadata=ext.load(self.store,self.project.id,b,metadata=True);folder=metadata['folders']['gift-event-1']
  self.assertEqual(folder['talkIds'],[1,2]);self.assertFalse(folder['sequence']);u=folder['uses'][0]
  self.assertEqual((u['npc'],u['item'],u['giftMode'],u['entryId']),(3,10,0,1))
  folder['uses'][0]['entryId']=2
  self.save({'externalDialogueFolders':metadata['folders'],'externalDialogueIds':metadata['talkIds']})
  native=b.read_json(self.cfg/'GiftEvtCfg.json');events=b.read_json(self.cfg/'EvtCfg.json')
  self.assertEqual(native['8']['talkId'],[[2]]);self.assertEqual(events['1']['talkId'],[2]);self.assertEqual(native['8']['future'],{'keep':1});self.assertEqual(len(native),1)
  # Repeat a text edit and reopen: the use remains linked, no duplicate rules.
  self.save({'talkPatch':{'version':1,'upsert':{'2':{'id':2,'content':'共享改文'}},'deleted':[]}})
  meta=ext.load(self.store,self.project.id,b,metadata=True)
  self.assertEqual(meta['folders']['gift-event-1']['uses'][0]['entryId'],2)
 def test_two_gender_gift_entries_survive_reopen_save(self):
  self.write('PersonCfg',{'3':{'id':3,'name':'人物'}})
  event={'id':1,'type':110,'title':'两性别','talkId':[1,2],'studioGiftCounterSlot':-1,'maxcount':1,'studioGiftBindings':[{'id':8,'index':0,'npc':3}]}
  native={'8':{'id':8,'item':10,'npc':[3],'talkId':[[1,2]],'type':[0],'cond':[[111,-1,1,-1,0]]}}
  self.save({'events':{'1':event},'giftEvents':native})
  meta=ext.load(self.store,self.project.id,b,metadata=True)
  self.assertEqual(len(meta['folders']['gift-event-1']['uses']),2)
  self.save({'externalDialogueFolders':meta['folders'],'externalDialogueIds':meta['talkIds']})
  self.assertEqual(b.read_json(self.cfg/'GiftEvtCfg.json')['8']['talkId'],[[1,2]])

 def test_background_hash_completion_reuses_scanned_catalog(self):
  import io
  def fixture_png():
   out=io.BytesIO();b.Image.new("RGBA",(8,12),(100,50,20,128)).save(out,"PNG");return out.getvalue()
  catalog=self.store.asset_catalog
  paths=[self.project.path/'a.png',self.project.path/'b.png']
  for path in paths:path.write_bytes(fixture_png())
  rows=[dict(assetId=str(i),name='场景'+str(i),kind='background',_path=path,sourceId=i) for i,path in enumerate(paths,1)]
  query=dict(projectId=self.project.id,revision=self.store.revision(self.project),source='mod',sourceProjectId=self.project.id,kind='background')
  catalog._hash_running=True
  with patch.object(catalog,'_configured',return_value=rows) as scan:
   first=catalog._entries(query);self.assertEqual(len(first['items']),2)
   for path in paths:catalog.image_hashes[(str(path),b.file_fingerprint(path))]='identical-pixels'
   catalog._hash_generation+=1
   second=catalog._entries(query);self.assertEqual(len(second['items']),1);self.assertEqual(scan.call_count,1)
   paths[0].write_bytes(paths[0].read_bytes()+b'changed')
   catalog._entries(query);self.assertEqual(scan.call_count,2)
 def test_text_save_failure_and_stale_revision_keep_source(self):
  original=(self.cfg/'TalkCfg.json').read_bytes()
  payload={'projectId':self.project.id,'revision':self.store.revision(self.project),'talkPatch':{'version':1,'upsert':{'2':{'id':2,'content':'失败的编辑'}},'deleted':[]}}
  replace=b.os.replace;failed=False
  def fail_once(src,dst):
   nonlocal failed
   if Path(dst)==self.cfg/'TalkCfg.json' and not failed:
    failed=True;raise OSError('injected disk failure')
   return replace(src,dst)
  with patch.object(b.os,'replace',side_effect=fail_once):
   with self.assertRaises((OSError,b.ApiError)):self.store.save(payload)
  self.assertEqual((self.cfg/'TalkCfg.json').read_bytes(),original)
  self.write('FutureCfg',{'1':{'id':1,'value':'external'}})
  with self.assertRaises(b.ApiError) as error:self.store.save(payload)
  self.assertEqual(error.exception.status,409);self.assertEqual((self.cfg/'TalkCfg.json').read_bytes(),original)

 def test_directory_watch_reuses_names_and_detects_changes(self):
  directory=self.root/'Images';directory.mkdir();(directory/'one.png').write_bytes(b'one')
  catalog=self.store.asset_catalog;folder={'path':str(directory)}
  first=catalog._folder_watch(folder)
  with patch('asset_catalog.os.scandir',side_effect=AssertionError('unchanged directory should reuse names')):
   self.assertEqual(catalog._folder_watch(folder),first)
  (directory/'one.png').write_bytes(b'different size');self.assertNotEqual(catalog._folder_watch(folder),first)
  (directory/'two.png').write_bytes(b'two');after=catalog._folder_watch(folder)
  self.assertTrue(any(p.endswith('two.png') for p,_ in after))
  (directory/'one.png').unlink();self.assertFalse(any(p.endswith('one.png') for p,_ in catalog._folder_watch(folder)))
