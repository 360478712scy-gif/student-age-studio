"""Keep-alive connections must never carry a previous request's unread body into the next request.

The page posts /api/updates/healthy on load, and that route answers without reading its body. On a reused
connection the leftover "{}" became the start of the next request line, the next API call got a 501 HTML
page, and startup stopped at "准备未完成" until the user pressed 重试启动.
"""
import http.client,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as b


class KeepAliveBodyTests(unittest.TestCase):
 def test_unread_post_body_does_not_corrupt_the_next_request(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{k:tmp+'/'+v for k,v in [('STUDIO_USER_DATA_ROOT','User'),('STUDIO_CACHE_ROOT','Cache'),('STUDIO_BACKUP_ROOT','Backups'),('STUDIO_DISPLAY_SETTINGS','display.json'),('STUDIO_ERROR_LOG_ROOT','Logs')]}):
   root=Path(tmp);store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json',migrate_cache=False)
   host=b.StudioServer(('127.0.0.1',0),store);thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
   try:
    headers={'X-Studio-Token':host.token,'Content-Type':'application/json','Host':'127.0.0.1:'+str(host.server_port)}
    connection=http.client.HTTPConnection('127.0.0.1',host.server_port,timeout=20)
    connection.request('POST','/api/updates/healthy',body=b'{}',headers=headers);first=connection.getresponse();first.read()
    self.assertEqual(first.status,200)
    # http.client reconnects transparently if the server closed the connection, as browsers do.
    connection.request('GET','/api/display-settings',headers=headers);second=connection.getresponse();body=second.read()
    self.assertEqual(second.status,200,body[:200]);self.assertIsInstance(json.loads(body),dict)
    connection.close()
   finally:
    host.shutdown();host.server_close()

 def test_read_post_body_keeps_the_connection_alive(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{k:tmp+'/'+v for k,v in [('STUDIO_USER_DATA_ROOT','User'),('STUDIO_CACHE_ROOT','Cache'),('STUDIO_BACKUP_ROOT','Backups'),('STUDIO_DISPLAY_SETTINGS','display.json'),('STUDIO_ERROR_LOG_ROOT','Logs')]}):
   root=Path(tmp);store=b.StudioStore(root/'Mods',root/'Workshop',root/'Game',asset_settings_path=root/'assets.json',migrate_cache=False)
   host=b.StudioServer(('127.0.0.1',0),store);thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
   try:
    headers={'X-Studio-Token':host.token,'Content-Type':'application/json','Host':'127.0.0.1:'+str(host.server_port)}
    connection=http.client.HTTPConnection('127.0.0.1',host.server_port,timeout=20)
    connection.request('POST','/api/display-settings',body=json.dumps({'showRecordIds':True}).encode(),headers=headers);response=connection.getresponse();response.read()
    self.assertEqual(response.status,200);self.assertNotEqual((response.getheader('Connection') or '').lower(),'close')
    connection.request('GET','/api/display-settings',headers=headers);again=connection.getresponse()
    self.assertEqual(again.status,200);self.assertTrue(json.loads(again.read())['showRecordIds'])
    connection.close()
   finally:
    host.shutdown();host.server_close()


if __name__=='__main__':
 unittest.main()
