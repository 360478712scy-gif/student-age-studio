"""A slow portrait-size cache rebuild must not hold the transaction mutex."""
import json,os,sys,tempfile,threading,unittest,urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as b
class PortraitSavePriorityTests(unittest.TestCase):
 def test_save_finishes_while_portrait_metadata_is_pending(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{k:tmp+'/'+v for k,v in [('STUDIO_USER_DATA_ROOT','User'),('STUDIO_CACHE_ROOT','Cache'),('STUDIO_BACKUP_ROOT','Backups'),('STUDIO_DISPLAY_SETTINGS','display.json'),('STUDIO_ERROR_LOG_ROOT','Logs')]}):
   root=Path(tmp);store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json',migrate_cache=False)
   project=store.project(store.create('测试')['id']);revision=store.revision(project);started=threading.Event();release=threading.Event()
   def dimensions(*args):started.set();release.wait(5);return {}
   host=b.StudioServer(('127.0.0.1',0),store);thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
   def post(route,payload):
    req=urllib.request.Request(host.origin+route,json.dumps(payload).encode(),headers={'X-Studio-Token':host.token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=8) as response:return json.load(response)
   try:
    with patch.dict(sys.modules,{'extract_game_assets':SimpleNamespace(portrait_dimensions=dimensions,native_portrait_paths=lambda catalog,paths:set())}),ThreadPoolExecutor(2) as pool:
     portrait=pool.submit(post,'/api/portrait-dimensions',{'projectId':project.id,'paths':[]})
     try:
      self.assertTrue(started.wait(2));save=pool.submit(post,'/api/save',{'projectId':project.id,'revision':revision,'talkPatch':{'version':1,'upsert':{'900001001':{'id':900001001,'content':'保存不等素材'}},'deleted':[]}})
      self.assertTrue(save.result(timeout=2)['ok']);self.assertFalse(portrait.done())
     finally:release.set()
     self.assertEqual(portrait.result(),{})
   finally:host.shutdown();host.server_close();thread.join()
 def test_save_finishes_while_head_thumbnail_is_pending(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'STUDIO_USER_DATA_ROOT':tmp+'/User','STUDIO_CACHE_ROOT':tmp+'/Cache','STUDIO_BACKUP_ROOT':tmp+'/Backups'}):
   root=Path(tmp);store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json',migrate_cache=False)
   project=store.project(store.create('头像')['id']);revision=store.revision(project);started=threading.Event();release=threading.Event()
   path=root/'head.png';path.write_bytes(b'head')
   def crop(*args):started.set();release.wait(5);return path
   host=b.StudioServer(('127.0.0.1',0),store);thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
   def request(route,payload=None):
    req=urllib.request.Request(host.origin+route,json.dumps(payload).encode() if payload else None,headers={'X-Studio-Token':host.token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=8) as response:return response.read()
   try:
    with patch('headshots.head_paths',return_value=[]),patch('headshots.crop_head',side_effect=crop),patch.object(store,'asset',return_value=path),ThreadPoolExecutor(2) as pool:
     portrait=pool.submit(request,'/api/talk-head?projectId='+project.id+'&roleId=1')
     try:
      self.assertTrue(started.wait(2));save=pool.submit(request,'/api/save',{'projectId':project.id,'revision':revision,'talkPatch':{'version':1,'upsert':{'900001001':{'id':900001001,'content':'头像不阻塞保存'}},'deleted':[]}})
      self.assertTrue(json.loads(save.result(timeout=2))['ok']);self.assertFalse(portrait.done())
     finally:release.set()
     self.assertEqual(portrait.result(),b'head')
   finally:host.shutdown();host.server_close();host.media_warmup.close();thread.join();store.close()
if __name__=='__main__':unittest.main()
