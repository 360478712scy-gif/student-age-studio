"""Cached previews stay bounded without weakening save/import conflict guards."""
import os,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs
import test_scoped_save as fixture
import server as b
from media_warmup import MediaWarmup

class AssetSessionTests(unittest.TestCase):
 setUp=fixture.ScopedSaveTests.setUp
 write=fixture.ScopedSaveTests.write
 def catalog(self):
  self.image=self.project.path/'image.png';b.Image.new('RGB',(16,12),'red').save(self.image)
  self.write('BgCfg',{'100':{'id':100,'name':'AA','url':'Mods/'+self.project.path.name+'/image.png'}})
  self.query={'projectId':self.project.id,'revision':self.store.revision(self.project),'source':'mod','sourceProjectId':self.project.id,'kind':'background'}
  self.assets=self.store.asset_catalog;data=self.assets.list(self.query)
  self.preview={k:v[0] for k,v in parse_qs(urlparse(data['items'][0]['previewUrl']).query).items()}|{'thumbnail':'1'}
  self.addCleanup(self.store.close)
  return data
 def test_cached_preview_never_checks_unrelated_configurations(self):
  self.catalog();self.write('FutureCfg',{'1':{'id':1,'keep':'external'}})
  with patch.object(self.store,'revision',side_effect=AssertionError('full revision scan for thumbnail')):
   self.assertTrue(self.assets.preview(self.preview).is_file())
  with self.assertRaises(b.ApiError) as e:self.store.save({'projectId':self.project.id,'revision':self.query['revision'],'talkPatch':{'version':1,'upsert':{},'deleted':[]}})
  self.assertEqual(e.exception.status,409)
 def test_changed_definition_still_rejects_preview_with_restored_mtime(self):
  self.catalog();path=self.cfg/'BgCfg.json';stamp=path.stat();path.write_bytes(path.read_bytes().replace(b'AA',b'BB'));os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
  with self.assertRaises(b.ApiError) as e:self.assets.preview(self.preview)
  self.assertEqual(e.exception.status,409)
 def test_changed_picture_still_rejects_cached_preview(self):
  self.catalog();b.Image.new('RGB',(16,12),'blue').save(self.image)
  with self.assertRaises(b.ApiError) as e:self.assets.preview(self.preview)
  self.assertEqual(e.exception.status,409)
 def test_obsolete_catalogues_do_not_accumulate_after_saves(self):
  self.catalog()
  for i in range(20):
   self.write('TalkCfg',{'1':{'id':1,'content':str(i)}});self.query['revision']=self.store.revision(self.project);self.assets.list(self.query)
   self.assertEqual(len(self.assets.cache),1)
 def test_wrong_revision_and_expired_catalogue_are_rejected(self):
  self.catalog()
  for delta in [{'revision':'unrecognized'},{'catalogKey':'missing'}]:
   with self.assertRaises(b.ApiError):self.assets.preview({**self.preview,**delta})
 def test_picker_polls_do_not_continuously_wake_background_scan(self):
  warmer=MediaWarmup(SimpleNamespace());warmer.thread=SimpleNamespace(is_alive=lambda:True)
  warmer._scan_not_before=time.monotonic()+30
  for _ in range(100):warmer.request_scan()
  self.assertFalse(warmer.wake.is_set())
  warmer._scan_not_before=0;warmer._scan_active=True;warmer.request_scan();self.assertFalse(warmer.wake.is_set())
  warmer._scan_active=False;warmer.request_scan();self.assertTrue(warmer.wake.is_set())

 def test_new_files_are_seen_when_directory_timestamp_does_not_advance(self):
  import asset_catalog as module
  root=self.project.path/'Images';root.mkdir();(root/'one.png').write_bytes(b'one')
  original=module.file_fingerprint;fixed=original(root)
  with patch.object(module,'_DIRECTORY_NAMES_REUSABLE',False),patch.object(module,'file_fingerprint',side_effect=lambda p:fixed if p==root else original(p)):
   assets=self.store.asset_catalog;folder={'path':str(root)};assets._folder_watch(folder)
   (root/'two.png').write_bytes(b'two')
   self.assertTrue(any(p.endswith('two.png') for p,_ in assets._folder_watch(folder)))
