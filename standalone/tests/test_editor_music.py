import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
import base64
import hashlib
import json
import tempfile
import unittest
import editor_music as music
import server as api
import test_plugin_mode

class MusicTests(unittest.TestCase):
 def setUp(self):
  test_plugin_mode.PluginModeTests.setUp(self)
  mock=patch.object(music,'builtin_tracks',return_value=[]);mock.start();self.addCleanup(mock.stop)
 def test_custom_library_order_dedup_and_restart(self):
  def put(title,track='local',extra=b''):
   return music.access(self.store,api,dict(trackId=track,fileName=title,data=base64.b64encode(b'RIFF'+b'\0'*4+b'WAVEfmt '+extra).decode()))
  put('其他音乐.wav',extra=b'a');put('odoriko.wav','odoriko');put('tooi.wav','tooi-sora')
  data=music.access(self.store,api);self.assertEqual([t['id'] for t in data['tracks'][:2]],['tooi-sora','odoriko'])
  custom=data['tracks'][2];self.assertEqual(custom['name'],'其他音乐');self.assertTrue(music.media(api,custom['id']).is_file())
  put('重复导入.wav',extra=b'a');self.assertEqual(len(music.access(self.store,api)['tracks']),3)
  put('其他音乐.wav',extra=b'b');self.assertEqual(len(music.access(self.store,api)['tracks']),4)
  music.access(self.store,api,dict(mode='shuffle',volume=.2));self.assertEqual(len(music.access(self.store,api)['tracks']),4)
  self.assertEqual(self.protected.read_bytes(),self.before)
  with self.assertRaises(api.ApiError):music.media(api,'../../not-music')

 def test_builtin_order_and_cached_media_preserve_personal_settings(self):
  raw=b'....ftyp'+b'qa audio';digest=hashlib.sha256(raw).hexdigest()
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);module=root/'editor_music.py';bundle=root/'music-tifa.json'
   bundle.write_text(json.dumps({'audio':base64.b64encode(raw).decode()}))
   tracks=[{'id':'tifa-theme','name':'蒂法','artist':'Square','file':bundle.name,'sha256':digest,'bytes':len(raw)}]
   with patch.object(music,'__file__',str(module)),patch.object(music,'builtin_tracks',return_value=tracks):
    music.access(self.store,api,{'volume':.12,'mode':'shuffle'})
    data=music.access(self.store,api);self.assertEqual(data['tracks'][0]['id'],'tifa-theme');self.assertEqual(data['preferences']['volume'],.12)
    self.assertEqual(music.media(api,'tifa-theme').read_bytes(),raw)
    bundle.unlink();self.assertEqual(music.media(api,'tifa-theme').read_bytes(),raw)
   self.assertEqual(self.protected.read_bytes(),self.before)

if __name__=='__main__':unittest.main()
